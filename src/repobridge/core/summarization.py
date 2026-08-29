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

`_call_gemini` retries transient upstream failures (503/500, and per-minute 429s) with
bounded exponential backoff, and deliberately does *not* retry a daily-quota 429 -- see
its docstring. Retrying changes nothing about grounding: the provenance is computed
before the first attempt and is identical whichever attempt succeeds.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import httpx

from repobridge.config import (
    SummarizationConfig,
    get_gemini_api_key,
    get_summarization_config,
)
from repobridge.core.diagnostics import redact
from repobridge.core.ranking import path_rank_key

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

    `detail` is the structured form of what happened, for diagnostics: the status, how many
    attempts were made, and -- the case worth seeing in a timeline -- whether a 429 was
    identified as a *daily* quota and deliberately not retried. That decision currently
    surfaces only inside a prose error string, which is exactly the "vague diagnostics"
    `evals.md` names as a failure signal.
    """

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


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
    #: structured form of `error`, for diagnostics. Empty on success.
    error_detail: dict[str, Any] = field(default_factory=dict)
    prompt_tokens_estimated: int = 0

    @property
    def is_grounded_output(self) -> bool:
        return self.status is SummaryStatus.OK and bool(self.text)


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

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

    Signals 1-4 live in `core/ranking.py` and are shared with `rank_files`, which orders
    what a capped run *reads*. The two stages must agree about what explains a repository;
    keeping two copies of these rules was how they would come to disagree.

    The one signal derived differently here: prose-ness comes from the chunk's own type, so
    a notebook's markdown cells rank above its code cells. `rank_files` has only the
    extension to go on, because the file has not been read yet.
    """
    prose_types = {"markdown", "notebook_markdown", "text"}

    def sort_key(chunk: ChunkRef) -> tuple:
        return path_rank_key(
            chunk.source_path, is_prose=chunk.chunk_type in prose_types
        ) + (chunk.chunk_index,)

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


#: Statuses worth another attempt. 503 is the common one on this tier -- identical
#: calls alternate between 200 and 503 -- and 500 is an upstream fault. 429 is here
#: only for the per-minute case; the per-day case is detected and never retried.
#: Every other 4xx is a request that will not become valid by repeating it.
RETRYABLE_STATUSES = frozenset({429, 500, 503})

#: A quota id or metric containing this marks a limit that resets at the *quota day*
#: boundary, not after the `retryDelay` the same response advertises. Measured: a
#: daily-quota 429 returns `retryDelay: ~58s` while the real reset is hours away.
_DAILY_QUOTA_MARKER = "perday"

#: Google's quota identifiers are constants like
#: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Anything that does not look
#: like one is left out of the message rather than echoed: an error body can carry
#: the prompt back, and the prompt is repository content.
_QUOTA_ID_SHAPE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _error_details(body: Any) -> list[dict]:
    """The `error.details` list of a Google API error body, or empty."""
    if not isinstance(body, dict):
        return []
    details = (body.get("error") or {}).get("details")
    return [d for d in details if isinstance(d, dict)] if isinstance(details, list) else []


def _daily_quota_id(body: Any) -> str | None:
    """
    The quota id when this error is a *per-day* quota exhaustion, else None.

    This is the one rate limit that must not be retried. The free tier's daily 429
    carries a `retryDelay` of about a minute, which is misleading: the allowance does
    not return until the quota day rolls over, so a retry budget spent against it buys
    nothing but a later identical failure.
    """
    for detail in _error_details(body):
        if not str(detail.get("@type", "")).endswith("QuotaFailure"):
            continue
        violations = detail.get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            quota_id = str(violation.get("quotaId") or "")
            metric = str(violation.get("quotaMetric") or "")
            if _DAILY_QUOTA_MARKER in quota_id.lower() or _DAILY_QUOTA_MARKER in metric.lower():
                return quota_id if _QUOTA_ID_SHAPE.match(quota_id) else "a per-day quota"
    return None


def _seconds_from_duration(raw: Any) -> float | None:
    """Parse a protobuf duration string such as `58s` or `1.5s`."""
    text = str(raw or "").strip()
    if not text.endswith("s"):
        return None
    try:
        value = float(text[:-1])
    except ValueError:
        return None
    return value if value >= 0 else None


def _suggested_delay(resp: httpx.Response, body: Any) -> float | None:
    """
    What the provider asked us to wait, in seconds, or None.

    `Retry-After` wins because it is the HTTP-level contract; Google's `RetryInfo`
    detail is the fallback. Only the numeric-seconds form of `Retry-After` is read: the
    HTTP-date form is not worth parsing for a local tool, and falling through to
    exponential backoff is a safe answer when it appears.
    """
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header.strip()))
        except ValueError:
            pass
    for detail in _error_details(body):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            seconds = _seconds_from_duration(detail.get("retryDelay"))
            if seconds is not None:
                return seconds
    return None


def _backoff_delay(attempt: int, cfg: SummarizationConfig) -> float:
    """
    Exponential backoff with equal jitter, bounded by `retry_max_delay`.

    Equal jitter (half fixed, half random) rather than full jitter: full jitter can
    return a near-zero wait, which defeats the point of backing off at all when the
    upstream is briefly overloaded.
    """
    ceiling = min(cfg.retry_max_delay, cfg.retry_initial_delay * (2 ** (attempt - 1)))
    half = ceiling / 2
    return half + random.uniform(0.0, half)


def _decode(resp: httpx.Response) -> Any:
    """Response JSON, or None. A non-JSON error body is not worth failing over."""
    try:
        return resp.json()
    except ValueError:
        return None


def _text_from_candidates(data: dict) -> str:
    """The generated text, or a specific error explaining why there is none."""

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


async def _call_gemini(
    prompt: str,
    cfg: SummarizationConfig,
    api_key: str,
    *,
    sleep=asyncio.sleep,
) -> str:
    """
    Ask Gemini's generateContent endpoint for a summary, retrying transient failures.

    The only place the API key is used. It goes in a header, never a URL or a log, and
    provider error bodies are reported by status code rather than echoed -- an error body
    can contain the request, and the request contains repository content.

    **Retry policy.** At most `cfg.max_attempts` attempts, on 503/500/429 only, with
    exponential backoff plus jitter, honouring `Retry-After`/`RetryInfo` when the
    provider supplies one. Two things bound it:

    - **A total wait budget** (`cfg.retry_budget_seconds`). A delay that does not fit in
      what is left of the budget is not slept at all: the wait would be spent and the
      request still not attempted within the time the caller has.
    - **A daily-quota 429 fails immediately.** It advertises a `retryDelay` of about a
      minute while the real reset is at the quota-day boundary, so retrying it spends
      the budget against a wall it cannot clear. See `_daily_quota_id`.

    Everything else -- 400, 401, 404 -- fails on the first response. Repeating a request
    the provider has already rejected as invalid cannot change the answer.

    `sleep` is injectable so tests exercise the schedule without waiting on it.
    """
    url = f"{cfg.api_base_url}/models/{cfg.model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": cfg.max_output_tokens},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    attempts = max(1, cfg.max_attempts)
    budget_left = max(0.0, cfg.retry_budget_seconds)
    last_error: SummarizationError | None = None

    # One client across attempts: a retry should reuse the connection, not re-handshake.
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except httpx.RequestError as exc:
                # Not retried: this slice covers upstream status codes only, and a
                # transport failure has not been observed against this provider.
                raise SummarizationError(
                    f"Could not reach the summarisation provider ({type(exc).__name__})."
                ) from exc

            if resp.status_code < 400:
                data = _decode(resp)
                if data is None:
                    raise SummarizationError(
                        "The summarisation provider returned a non-JSON body."
                    )
                return _text_from_candidates(data)

            body = _decode(resp)

            if resp.status_code == 429:
                quota_id = _daily_quota_id(body)
                if quota_id:
                    # fail fast, deliberately: no wait inside one run can clear this
                    raise SummarizationError(
                        "The summarisation provider's daily request quota is exhausted "
                        f"for model '{cfg.model}' ({quota_id}). It does not reset after "
                        "the retry delay the provider advertises; it resets at the "
                        "quota-day boundary, so no retry was attempted. The quota is per "
                        f"model: set {cfg.model_env_var} to another model to continue "
                        "today. The run and its extracted content are stored, and the "
                        "summary can be generated later.",
                        {
                            "kind": "daily_quota",
                            "quota_id": quota_id,
                            "status_code": 429,
                            "model": cfg.model,
                            "attempts": attempt,
                            "retry_decision": "fail_fast",
                            "advertised_retry_delay_seconds": _suggested_delay(resp, body),
                            "resets": "at the provider's quota-day boundary, not after the "
                                      "advertised delay",
                        },
                    )
                last_error = SummarizationError(
                    "The summarisation provider rate-limited this request. The run is "
                    "stored; the summary can be generated later.",
                    {
                        "kind": "rate_limit",
                        "status_code": 429,
                        "model": cfg.model,
                        "attempts": attempt,
                        "retry_decision": "retry" if attempt < attempts else "attempts_exhausted",
                    },
                )
            else:
                # deliberately no body: it can echo the prompt back
                last_error = SummarizationError(
                    f"The summarisation provider returned status {resp.status_code}.",
                    {
                        "kind": "provider_status",
                        "status_code": resp.status_code,
                        "model": cfg.model,
                        "attempts": attempt,
                        "retry_decision": (
                            "retry" if resp.status_code in RETRYABLE_STATUSES
                            and attempt < attempts else "not_retryable"
                            if resp.status_code not in RETRYABLE_STATUSES
                            else "attempts_exhausted"
                        ),
                    },
                )

            if resp.status_code not in RETRYABLE_STATUSES or attempt == attempts:
                raise last_error

            delay = min(
                _suggested_delay(resp, body) or _backoff_delay(attempt, cfg),
                cfg.retry_max_delay,
            )
            if delay > budget_left:
                logger.warning(
                    "Not retrying summarisation: a %.1fs wait exceeds the %.1fs left of "
                    "the retry budget (status %s).",
                    delay,
                    budget_left,
                    resp.status_code,
                )
                raise last_error

            budget_left -= delay
            logger.info(
                "Summarisation attempt %s/%s returned status %s; retrying in %.1fs.",
                attempt,
                attempts,
                resp.status_code,
                delay,
            )
            await sleep(delay)

    # unreachable: the loop either returns or raises
    raise last_error or SummarizationError(
        "The summarisation provider could not be reached."
    )


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
    cfg: SummarizationConfig | None = None,
    call_provider=None,
) -> SummaryResult:
    """
    Produce a grounded summary, or say plainly why there is none.

    `call_provider` is injectable so tests never touch the network; it defaults to Gemini.

    `cfg` defaults to `None` rather than to `DEFAULT_SUMMARIZATION_CONFIG`, and is then
    resolved with `get_summarization_config()`. A default argument is evaluated once at
    definition time, so binding the default instance here would silently ignore
    `REPOBRIDGE_GEMINI_MODEL` for any caller that omitted `cfg` -- the same shape of bug
    that froze the extraction cap at import.

    A run with no chunks -- degraded, or nothing extractable -- returns NO_CONTENT without
    calling the provider at all. Summarising from metadata alone is exactly the invention
    this module exists to prevent.
    """
    cfg = cfg if cfg is not None else get_summarization_config()
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
        # redacted: the message is built from the provider's own error body, which is
        # the one string here that this code did not write (CONTRACT I-6)
        logger.warning("Summarisation failed for %s: %s", repo, redact(str(exc)))
        return SummaryResult(
            status=SummaryStatus.PROVIDER_ERROR,
            provenance=provenance,
            error=str(exc),
            error_detail=getattr(exc, "detail", {}) or {},
            prompt_tokens_estimated=tokens,
            model=cfg.model,
        )
    except Exception as exc:  # noqa: BLE001 - a provider fault must not lose the run
        logger.warning("Summarisation failed for %s: %s", repo, type(exc).__name__)
        return SummaryResult(
            status=SummaryStatus.PROVIDER_ERROR,
            provenance=provenance,
            error=f"Summarisation failed unexpectedly ({type(exc).__name__}).",
            error_detail={"kind": "unexpected", "exception": type(exc).__name__},
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
