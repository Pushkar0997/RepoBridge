"""
Grounded summary generation.

**Grounding is the point of this module.** Everything else is secondary. The summary must
never claim or imply RepoBridge read something it did not, and a reader must be able to
check that claim without trusting either the model or the prompt.

How that is enforced, in order of strength:

1. **The response carries provenance, not just the prompt.** `SummaryResult.provenance`
   is a machine-readable record of what was read and what was not: file counts, chunk
   counts, skip reasons, cap effects, truncation. It is computed from the run's own
   inventory *before* the model is called and travels with the prose. A reader checks the
   summary against it; nothing about the model's behaviour can alter it.
2. **Content is refused when there is none.** A degraded run, or a run with zero chunks,
   never reaches the provider. `summarise()` returns a NO_CONTENT result saying so. The
   model cannot invent a summary from metadata because it is never asked to.
3. **The prompt states the inventory explicitly**, including what was excluded and why,
   and instructs the model to acknowledge the limits. This is the weakest of the three,
   because a model can ignore instructions. It is included because it demonstrably helps,
   not because it is relied upon.

The provider call is isolated in `_call_gemini` so a second provider is cheap to add
later. No adapter abstraction is built yet: one real integration first.
"""

from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import httpx

from repobridge.config import (
    DEFAULT_SUMMARIZATION_CONFIG,
    SummarizationConfig,
    get_gemini_api_key,
)

logger = logging.getLogger(__name__)


class SummaryStatus(str, Enum):
    OK = "ok"
    #: nothing was extracted, so there is nothing to summarise. Not a failure.
    NO_CONTENT = "no_content"
    #: the provider could not be reached, or refused. The run survives.
    PROVIDER_ERROR = "provider_error"
    #: no API key configured. Also not a failure of the run.
    NOT_CONFIGURED = "not_configured"


class SummarizationError(Exception):
    """
    A provider failure, safe to show a caller.

    Never carries the API key: the key is only ever placed in a request header, and
    provider response bodies are summarised by status code rather than echoed.
    """


@dataclass(frozen=True)
class ChunkRef:
    """The subset of a chunk this module needs. Keeps it decoupled from storage rows."""

    source_path: str
    chunk_index: int
    chunk_type: str
    text: str
    token_estimate: int
    cell_index: int | None = None


@dataclass
class SummaryResult:
    status: SummaryStatus
    text: str | None = None
    model: str | None = None
    #: what was read and what was not -- computed from the inventory, not from the model
    provenance: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    prompt_tokens_estimated: int = 0

    @property
    def is_grounded_output(self) -> bool:
        return self.status is SummaryStatus.OK and bool(self.text)


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

#: Filenames that describe a repository to a newcomer, most explanatory first.
_ORIENTING_NAMES = (
    "readme",
    "index",
    "overview",
    "introduction",
    "getting-started",
    "getting_started",
    "architecture",
    "design",
    "contributing",
    "changelog",
)

#: Directories whose content explains the project, rather than supporting it.
_EXPLANATORY_DIRECTORIES = ("docs", "doc", "documentation", "guides", "examples")

#: Directories that exist for tooling or process, not for explaining the project.
_PERIPHERAL_DIRECTORIES = (".github", ".circleci", ".azure", "ci", "scripts", "tests", "test")


def rank_chunks(chunks: Sequence[ChunkRef]) -> list[ChunkRef]:
    """
    Order chunks by how much they explain the repository.

    The problem this solves, recorded as an open item in plan.md under Milestone 5: chunk
    order is path order, which is roughly alphabetical, so a budget-limited summary of a
    large repository would be grounded in whatever sorts first -- typically `.github/` --
    while the README never reaches the model.

    The ranking, in order of weight:

    1. **Root-level README and orienting docs first.** A README is written for exactly the
       question a summary answers. This is the single highest-signal file in most
       repositories and it is worth privileging explicitly rather than hoping.
    2. **Shallower paths before deeper ones.** Depth correlates with specificity: top-level
       files describe the project, files eight directories down describe an implementation
       detail.
    3. **Explanatory directories (`docs/`) ahead of peripheral ones (`.github/`, `tests/`).**
       Both are legitimate content; only one answers "what is this repository".
    4. **Prose before code.** Markdown and notebook markdown state intent; code states
       mechanism. Both matter, prose is denser per token for a summary.
    5. **Path, then chunk index, as a tiebreak** -- so the order is deterministic and a
       file's own chunks stay in their original sequence.

    Deliberately *not* ranked by file size: a large file is not a more explanatory one, and
    size-ranking would promote generated data over a hand-written README.
    """

    def sort_key(chunk: ChunkRef) -> tuple:
        path = chunk.source_path
        lowered = path.lower()
        segments = lowered.split("/")
        depth = len(segments) - 1
        stem = posixpath.splitext(segments[-1])[0]

        orienting = next(
            (i for i, name in enumerate(_ORIENTING_NAMES) if stem.startswith(name)),
            len(_ORIENTING_NAMES),
        )
        # a root README outranks a nested one
        orienting_rank = orienting if orienting < len(_ORIENTING_NAMES) else 99

        directory_rank = 1  # ordinary source
        if any(seg in _EXPLANATORY_DIRECTORIES for seg in segments[:-1]):
            directory_rank = 0
        elif any(seg in _PERIPHERAL_DIRECTORIES for seg in segments[:-1]):
            directory_rank = 2

        is_prose = 0 if chunk.chunk_type in {"markdown", "notebook_markdown", "text"} else 1

        return (
            orienting_rank,
            depth if orienting_rank < 99 else 0,  # among orienting files, prefer shallow
            directory_rank,
            depth,
            is_prose,
            path,
            chunk.chunk_index,
        )

    return sorted(chunks, key=sort_key)


def select_within_budget(
    chunks: Sequence[ChunkRef], max_tokens: int
) -> tuple[list[ChunkRef], int]:
    """
    Take ranked chunks until the token budget is spent.

    Returns the selected chunks *in ranked order* and the estimated token total.

    The estimate is `chars // 4` (see `ExtractionConfig.chars_per_token`), which is crude:
    it under-counts code and badly under-counts non-Latin scripts, so a run could exceed
    the intended budget. The budget is far below the model's 1M-token context, so the
    practical risk is spending more than expected, not a rejected request.
    """
    selected: list[ChunkRef] = []
    used = 0
    for chunk in chunks:
        cost = max(chunk.token_estimate, 1)
        if used + cost > max_tokens:
            continue  # a later, smaller chunk may still fit
        selected.append(chunk)
        used += cost
    return selected, used


# --------------------------------------------------------------------------
# provenance and prompt
# --------------------------------------------------------------------------


def build_provenance(
    *,
    run_summary: dict[str, Any],
    skipped_by_reason: dict[str, int],
    chunks_total: int,
    chunks_included: int,
    tokens_estimated: int,
    budget: int,
) -> dict[str, Any]:
    """
    What was read and what was not, computed from the run's inventory.

    This is the enforcement mechanism. It is derived before the provider is called and is
    returned alongside the prose, so a reader can check any claim in the summary against
    the record without trusting the model or the prompt.
    """
    selected = run_summary.get("selected_count", 0)
    files_read = run_summary.get("files_read", 0)
    not_fetched = run_summary.get("files_not_fetched", 0)
    read_failed = run_summary.get("files_read_failed", 0)

    limitations: list[str] = []
    if run_summary.get("tree_truncated"):
        limitations.append(
            "GitHub truncated the file listing itself, so files exist in this repository "
            "that RepoBridge never saw and cannot account for."
        )
    if not_fetched:
        limitations.append(
            f"{not_fetched} selected file(s) were not read because this run reads at most "
            f"{run_summary.get('read_cap')} files."
        )
    if read_failed:
        limitations.append(f"{read_failed} selected file(s) could not be read or decoded.")
    if chunks_included < chunks_total:
        limitations.append(
            f"{chunks_included} of {chunks_total} extracted chunks fit the token budget; "
            f"{chunks_total - chunks_included} were not sent to the model."
        )
    if skipped_by_reason:
        detail = ", ".join(f"{count} {reason}" for reason, count in skipped_by_reason.items())
        limitations.append(f"Skipped without reading: {detail}.")

    return {
        "files_selected": selected,
        "files_read": files_read,
        "files_read_failed": read_failed,
        "files_not_fetched": not_fetched,
        "read_cap": run_summary.get("read_cap"),
        "tree_entry_count": run_summary.get("tree_entry_count"),
        "tree_truncated": bool(run_summary.get("tree_truncated")),
        "skipped_count": run_summary.get("skipped_count", 0),
        "skipped_by_reason": dict(skipped_by_reason),
        "chunks_total": chunks_total,
        "chunks_included": chunks_included,
        "chunks_excluded": max(0, chunks_total - chunks_included),
        "token_budget": budget,
        "tokens_estimated": tokens_estimated,
        "token_estimate_method": "chars//4 heuristic, not a tokenizer",
        "is_partial": chunks_included < chunks_total
        or bool(not_fetched)
        or bool(run_summary.get("tree_truncated")),
        "read_of_selected": f"read {files_read} of {selected} selected files",
        "chunks_of_total": f"sent {chunks_included} of {chunks_total} extracted chunks",
        "limitations": limitations,
    }


SYSTEM_INSTRUCTIONS = """\
You are summarising a software repository for someone deciding whether it is relevant to \
them. You are given an inventory of exactly what was read, followed by the extracted text.

Rules, in order of importance:

1. Ground every claim in the extracted content below. If the content does not support a \
statement, do not make it.
2. Never claim or imply that anything was read which the inventory says was not read. Do \
not speculate about the contents of skipped, unread or truncated files.
3. If coverage is partial, say so in your own words, near the start, and be specific about \
what is missing according to the inventory.
4. Do not invent file names, modules, dependencies, licences or authors. Only name things \
that appear in the content or the inventory.
5. If the content is too sparse to characterise the repository, say that plainly instead \
of padding.

Write 2-5 short paragraphs of plain prose. No preamble, no headings, no bullet lists, no \
markdown formatting. Cover: what the repository is for, how it is organised, and what the \
limits of this reading are."""


def build_prompt(
    *,
    repo: str,
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    chunks: Sequence[ChunkRef],
) -> str:
    """Inventory first, then content. The inventory is what the model must not contradict."""
    lines: list[str] = [SYSTEM_INSTRUCTIONS, "", "=" * 60, f"REPOSITORY: {repo}"]

    if metadata.get("description"):
        lines.append(f"Description (from GitHub metadata): {metadata['description']}")
    if metadata.get("language"):
        lines.append(f"Primary language (from GitHub metadata): {metadata['language']}")
    lines.append(f"Ref analysed: {metadata.get('resolved_ref') or 'unknown'}")

    lines += [
        "",
        "WHAT WAS READ",
        f"- The repository tree listed {provenance['tree_entry_count']} entries.",
        f"- {provenance['files_selected']} were selected as readable text.",
        f"- {provenance['read_of_selected']}.",
        f"- Those files produced {provenance['chunks_total']} text chunks; "
        f"{provenance['chunks_of_total']}.",
        "",
        "WHAT WAS NOT READ",
    ]
    if provenance["limitations"]:
        lines += [f"- {item}" for item in provenance["limitations"]]
    else:
        lines.append("- Nothing. Every selected file was read and every chunk is included below.")

    lines += [
        "",
        "You must not describe anything listed above as not read.",
        "=" * 60,
        "",
        "EXTRACTED CONTENT",
        "",
    ]

    for chunk in chunks:
        location = f"{chunk.source_path}"
        if chunk.cell_index is not None:
            location += f" (notebook cell {chunk.cell_index})"
        elif chunk.chunk_index:
            location += f" (chunk {chunk.chunk_index})"
        lines += [f"--- {location} [{chunk.chunk_type}] ---", chunk.text, ""]

    return "\n".join(lines)


# --------------------------------------------------------------------------
# provider: Google Gemini (AI Studio). Isolated deliberately.
# --------------------------------------------------------------------------


async def _call_gemini(prompt: str, cfg: SummarizationConfig, api_key: str) -> str:
    """
    One request to Gemini's generateContent endpoint.

    The only place the API key is used. It goes in a header, never a URL or a log, and
    provider error bodies are reported by status code rather than echoed -- an error body
    can contain the request, and the request contains repository content.
    """
    url = f"{cfg.api_base_url}/models/{cfg.model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": cfg.max_output_tokens},
    }

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.RequestError as exc:
        raise SummarizationError(
            f"Could not reach the summarisation provider ({type(exc).__name__})."
        ) from exc

    if resp.status_code == 429:
        raise SummarizationError(
            "The summarisation provider rate-limited this request. The run is stored; "
            "the summary can be generated later."
        )
    if resp.status_code >= 400:
        # deliberately no body: it can echo the prompt back
        raise SummarizationError(
            f"The summarisation provider returned status {resp.status_code}."
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise SummarizationError("The summarisation provider returned a non-JSON body.") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        raise SummarizationError(
            f"The summarisation provider returned no candidates (reason: {blocked})."
            if blocked
            else "The summarisation provider returned no candidates."
        )

    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        finish = candidates[0].get("finishReason")
        raise SummarizationError(
            f"The summarisation provider returned an empty summary (finishReason: {finish})."
        )
    return text


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


async def summarise(
    *,
    repo: str,
    metadata: dict[str, Any],
    run_summary: dict[str, Any],
    skipped_by_reason: dict[str, int],
    chunks: Sequence[ChunkRef],
    cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG,
    call_provider=None,
) -> SummaryResult:
    """
    Produce a grounded summary, or say plainly why there is none.

    `call_provider` is injectable so tests never touch the network; it defaults to Gemini.

    A run with no chunks -- degraded, or nothing extractable -- returns NO_CONTENT without
    calling the provider at all. Summarising from metadata alone is exactly the invention
    this module exists to prevent.
    """
    ranked = rank_chunks(chunks)
    included, tokens = select_within_budget(ranked, cfg.max_prompt_tokens)
    provenance = build_provenance(
        run_summary=run_summary,
        skipped_by_reason=skipped_by_reason,
        chunks_total=len(chunks),
        chunks_included=len(included),
        tokens_estimated=tokens,
        budget=cfg.max_prompt_tokens,
    )

    if not chunks:
        return SummaryResult(
            status=SummaryStatus.NO_CONTENT,
            provenance=provenance,
            error=(
                "No content was extracted from this repository, so there is nothing to "
                "summarise. Summarising from repository metadata alone would not be "
                "grounded in anything RepoBridge actually read."
            ),
        )

    api_key = get_gemini_api_key(cfg)
    if not api_key:
        return SummaryResult(
            status=SummaryStatus.NOT_CONFIGURED,
            provenance=provenance,
            error=(
                f"No summarisation API key configured. Set {cfg.api_key_env_var} to enable "
                "summaries. The run and its extracted content are stored regardless."
            ),
        )

    prompt = build_prompt(
        repo=repo, metadata=metadata, provenance=provenance, chunks=included
    )
    caller = call_provider or (lambda p: _call_gemini(p, cfg, api_key))

    try:
        text = await caller(prompt)
    except SummarizationError as exc:
        logger.warning("Summarisation failed for %s: %s", repo, exc)
        return SummaryResult(
            status=SummaryStatus.PROVIDER_ERROR,
            provenance=provenance,
            error=str(exc),
            prompt_tokens_estimated=tokens,
            model=cfg.model,
        )
    except Exception as exc:  # noqa: BLE001 - a provider fault must not lose the run
        logger.warning("Summarisation failed for %s: %s", repo, type(exc).__name__)
        return SummaryResult(
            status=SummaryStatus.PROVIDER_ERROR,
            provenance=provenance,
            error=f"Summarisation failed unexpectedly ({type(exc).__name__}).",
            prompt_tokens_estimated=tokens,
            model=cfg.model,
        )

    return SummaryResult(
        status=SummaryStatus.OK,
        text=text,
        model=cfg.model,
        provenance=provenance,
        prompt_tokens_estimated=tokens,
    )
