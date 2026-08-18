from __future__ import annotations

import json
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.core.input import (
    normalize_github_repo_url,
    RepoURLValidationError,
)
from repobridge.config import get_extraction_config, get_summarization_config
from repobridge.core.models import AnalyzeRequest
from repobridge.core.extraction import ExtractionResult, fetch_and_extract
from repobridge.core.github_client import (
    fetch_file_content,
    open_client,
    fetch_repo_metadata,
    fetch_repo_tree,
    GitHubClientError,
)
from repobridge.core.selection import ClassificationResult, classify_tree
from repobridge.core.summarization import ChunkRef, SummaryResult, summarise
from repobridge.infra import storage
from repobridge.infra.db import get_session

router = APIRouter(prefix="/api", tags=["runs"])


def _status_for(error: GitHubClientError) -> int:
    """
    Map a GitHub failure onto the status *this* API should return.

    GitHub's status code is not automatically ours: an upstream 500 does not mean
    RepoBridge failed, and a rate limit is not "you are forbidden".
    """
    if error.is_rate_limit:
        return 429
    if error.status_code is None:
        # Never reached GitHub at all (network error, DNS, timeout).
        return 502
    if error.status_code >= 500:
        # Upstream is broken; we are the gateway.
        return 502
    # Genuine client-side answers from GitHub (404, and 401/403 that are real auth
    # failures) are meaningful as-is.
    return error.status_code

# How many tree entries to echo back inline. The full tree is not returned in
# v0.1; this is a preview so callers can sanity-check what was retrieved.
TREE_PREVIEW_LIMIT = 50

# How many classified files to sample per status. Classification runs over the whole
# tree, but the response carries aggregates plus a sample: kubernetes/kubernetes has
# 37,393 entries and nobody wants those inline.
CLASSIFICATION_SAMPLE_LIMIT = 50

#: A summarisation provider: given a prompt, return the generated text.
SummaryProvider = Callable[[str], Awaitable[str]]


def get_summary_provider() -> SummaryProvider | None:
    """
    The summarisation provider for this request.

    Production returns None, which leaves `summarise()` to call its configured Gemini
    endpoint. It exists as a dependency, rather than as a module-level variable a test
    reassigns, so the seam is part of the route's declared interface: a test overrides
    it with `app.dependency_overrides[get_summary_provider]`, scoped to the app and
    undone by clearing the mapping, with no mutable global left in production code.
    """
    return None


def _extraction_payload(result: ExtractionResult | None) -> dict | None:
    """
    Aggregates plus a capped sample, same contract as `_classification_payload`.

    `read_of_selected` is the honesty field: a capped run must say "read 200 of 11,215"
    as plainly as the tree page says "showing 100 of 37,393".
    """
    if result is None:
        return None
    return {
        "selected_total": result.selected_total,
        "files_read": len(result.read),
        "files_failed": len(result.failed),
        "files_not_fetched": len(result.not_fetched),
        "read_cap": result.cap,
        "cap_applied": result.cap_applied,
        "read_of_selected": f"read {len(result.read)} of {result.selected_total} selected files",
        "accounts_for_every_selected_file": result.accounts_for_every_selected_file(),
        "chunk_count": len(result.chunks),
        "sample_limit": CLASSIFICATION_SAMPLE_LIMIT,
        "failed_sample": [
            {"path": f.path, "error": f.error}
            for f in result.failed[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "not_fetched_sample": [
            {"path": f.path, "error": f.error}
            for f in result.not_fetched[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
    }


def _summary_payload(result: SummaryResult) -> dict:
    """
    The prose plus the provenance that makes it checkable.

    `provenance` is always present, including on NO_CONTENT and PROVIDER_ERROR: a reader
    should be able to see what *would* have been summarised even when nothing was.
    """
    return {
        "status": result.status.value,
        "text": result.text,
        "model": result.model,
        "error": result.error,
        "prompt_tokens_estimated": result.prompt_tokens_estimated,
        "provenance": result.provenance,
    }


def _classification_payload(result: ClassificationResult) -> dict:
    """
    Aggregate counts plus a capped sample.

    Field names say which is which: `*_count` covers every entry, `*_sample` is capped
    at CLASSIFICATION_SAMPLE_LIMIT. The counts, not the samples, are the source of truth.
    """
    return {
        "total_entries": result.total_entries,
        "directories": result.directories,
        "selected_count": len(result.selected),
        "skipped_count": len(result.skipped),
        "failed_count": len(result.failed),
        "skipped_count_by_reason": result.counts_by_reason(),
        "accounts_for_every_entry": result.accounts_for_every_entry(),
        "sample_limit": CLASSIFICATION_SAMPLE_LIMIT,
        "selected_sample": [
            {"path": f.path, "extension": f.extension, "size": f.size}
            for f in result.selected[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "skipped_sample": [
            {
                "path": f.path,
                "reason": f.reason.value if f.reason else None,
                "message": f.message,
            }
            for f in result.skipped[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
        "failed_sample": [
            {"path": f.path, "message": f.message}
            for f in result.failed[:CLASSIFICATION_SAMPLE_LIMIT]
        ],
    }


@router.post("/analyze", response_class=JSONResponse)
async def analyze_repo(
    request: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
    provider: SummaryProvider | None = Depends(get_summary_provider),
):
    """
    Validate the incoming GitHub repo URL, normalize owner/repo, then fetch repository
    metadata and the git tree for the resolved ref.

    v0.1: retrieval, classification, content extraction, persistence and summarisation.
    The run is stored and its id returned as `run_id`.

    Summarisation runs last and cannot fail the request: a provider error, an exhausted
    quota or a missing key is recorded on the run, which stays `completed`. The summary
    can be generated afterwards from stored content via
    `POST /api/runs/{run_id}/summarize`, with no re-fetching.

    Reading is capped at `ExtractionConfig.max_files_per_run`; selected files beyond the
    cap are recorded as `not_fetched`, never dropped. See the 2026-08-18 amendment in
    spec.md section 7.4 for why per-file reads were chosen over a tarball.

    Error policy for the tree step:
    - An explicit branch_or_ref that GitHub cannot resolve is a caller error -> HTTP 404.
      A caller who asked for a specific branch must never receive a 200 implying it exists.
    - Any other tree failure (rate limit, other GitHub errors) is a degraded run -> HTTP 200
      with metadata intact and `tree_error` explaining what did not come through.

    `resolved_ref` is null unless the tree call actually succeeded against that ref. The ref
    we intended to use is always derivable by the caller as `branch_or_ref` when they supplied
    one, else `metadata.default_branch`, so no separate "attempted" field is reported.
    """
    # Step 1: validate and normalize URL
    try:
        normalized = normalize_github_repo_url(str(request.repo_url))
    except RepoURLValidationError as e:
        raise HTTPException(status_code=400, detail={"message": e.message})

    # Step 2: fetch basic metadata from GitHub
    try:
        metadata = await fetch_repo_metadata(normalized)
    except GitHubClientError as e:
        # Record the attempt before failing the request. A repo that never resolved is
        # otherwise the one outcome that leaves no trace, and it is exactly what a user
        # comes back to ask about.
        failed_run_id = await storage.create_failed_run(
            session,
            repo_url=str(request.repo_url),
            owner=normalized.owner,
            name=normalized.name,
            branch_or_ref=request.branch_or_ref,
            error=e.message,
        )
        # the run_id travels with the error so a caller can open the failed run: it is
        # still a run, and it is the record of what went wrong
        raise HTTPException(
            status_code=_status_for(e),
            detail={"message": e.message, "run_id": failed_run_id},
        )

    # Step 3: decide which ref to ask GitHub for.
    # Explicit request wins; otherwise fall back to the repo's default branch.
    # This is what we *attempt*; it is not reported as resolved until GitHub confirms it.
    requested_ref = request.branch_or_ref
    attempted_ref = requested_ref or metadata.get("default_branch") or "HEAD"

    # Step 4: fetch the tree for that ref
    resolved_ref: str | None = None
    tree_preview: list[dict] = []
    tree_entry_count = 0
    tree_truncated = False
    tree_error: str | None = None
    # None, not an empty summary: if the tree never arrived there is nothing to
    # classify, and zero counts would read as "we looked and found nothing".
    classification: dict | None = None
    classification_result: ClassificationResult | None = None

    try:
        tree = await fetch_repo_tree(normalized, attempted_ref)
    except GitHubClientError as e:
        if requested_ref and e.status_code == 404:
            # The caller named a ref that does not exist. Do not pretend this succeeded.
            raise HTTPException(
                status_code=404,
                detail={
                    "message": (
                        f"Branch or ref '{requested_ref}' was not found in "
                        f"{normalized.owner}/{normalized.name}."
                    )
                },
            )
        # Metadata succeeded, so report the run as degraded rather than failed.
        # resolved_ref stays None: we never confirmed the ref exists, and the response
        # must not assert a resolution that did not happen.
        tree_error = f"Tree retrieval failed: {e.message}"
    else:
        # GitHub answered for this ref, so it is now genuinely resolved.
        resolved_ref = attempted_ref
        entries = tree.get("tree") or []
        # Deliberately not called a "total": when GitHub truncates, this is only
        # what the API chose to return.
        tree_entry_count = len(entries)
        tree_truncated = bool(tree.get("truncated", False))
        tree_preview = [
            {
                "path": entry.get("path"),
                "type": entry.get("type"),
                "size": entry.get("size"),
                "mode": entry.get("mode"),
            }
            for entry in entries[:TREE_PREVIEW_LIMIT]
        ]
        # Classify every entry GitHub returned, not just the previewed ones.
        classification_result = classify_tree(entries)
        classification = _classification_payload(classification_result)

        if tree_truncated:
            # Truncation must never be discoverable only by noticing a boolean.
            tree_error = (
                "GitHub truncated the tree response for this repository, so the file "
                f"listing is incomplete. {tree_entry_count} entries were returned; the "
                "repository contains more. Classification below covers only those."
            )

    # Step 5: read and extract the selected files, capped. Runs only when a tree
    # arrived; a degraded run has nothing selected to read.
    extraction: ExtractionResult | None = None
    if classification_result is not None and classification_result.selected:
        extraction_cfg = get_extraction_config()

        # One client for the whole run: a client per file means a TCP+TLS handshake per
        # file, which dominated the read time before pooling.
        async with open_client(
            extraction_cfg.content_timeout,
            max_connections=extraction_cfg.max_concurrent_reads,
        ) as client:

            async def _fetch(path: str) -> str:
                return await fetch_file_content(
                    normalized, path, resolved_ref, client=client
                )

            extraction = await fetch_and_extract(
                [f.path for f in classification_result.selected],
                _fetch,
                extraction_cfg,
            )

    # Step 6: persist. A degraded run is stored too, with its error and whatever
    # metadata succeeded -- a run that vanished because it failed would be the worst
    # outcome for a tool whose pitch is that it tells you what went wrong.
    run_id = await storage.create_run(
        session,
        repo_url=str(request.repo_url),
        owner=normalized.owner,
        name=normalized.name,
        branch_or_ref=request.branch_or_ref,
        resolved_ref=resolved_ref,
        metadata=metadata,
        tree_entry_count=tree_entry_count,
        tree_truncated=tree_truncated,
        tree_error=tree_error,
        classification=classification_result,
    )

    if extraction is not None:
        await storage.persist_extraction(session, run_id, extraction)

    # Step 7: summarise, grounded in what was actually read.
    # A run with no chunks never reaches the provider -- see core/summarization.py.
    summary = await summarise(
        repo=f"{normalized.owner}/{normalized.name}",
        metadata={**metadata, "resolved_ref": resolved_ref},
        run_summary={
            "tree_entry_count": tree_entry_count,
            "tree_truncated": tree_truncated,
            "selected_count": len(classification_result.selected) if classification_result else 0,
            "skipped_count": len(classification_result.skipped) if classification_result else 0,
            "files_read": len(extraction.read) if extraction else 0,
            "files_read_failed": len(extraction.failed) if extraction else 0,
            "files_not_fetched": len(extraction.not_fetched) if extraction else 0,
            "read_cap": extraction.cap if extraction else None,
        },
        skipped_by_reason=(
            classification_result.counts_by_reason() if classification_result else {}
        ),
        chunks=[
            ChunkRef(
                source_path=c.source_path,
                chunk_index=c.chunk_index,
                chunk_type=c.chunk_type.value,
                text=c.text,
                token_estimate=c.token_estimate(),
                cell_index=c.cell_index,
            )
            for c in (extraction.chunks if extraction else [])
        ],
        cfg=get_summarization_config(),
        call_provider=provider,
    )
    await storage.persist_summary(session, run_id, summary)

    # Step 8: build response
    return {
        "run_id": run_id,
        "repo_url": str(request.repo_url),
        "owner": normalized.owner,
        "name": normalized.name,
        "branch_or_ref": request.branch_or_ref,
        "resolved_ref": resolved_ref,
        "tree_preview": tree_preview,
        "tree_entry_count": tree_entry_count,
        "tree_truncated": tree_truncated,
        "tree_error": tree_error,
        "classification": classification,
        "extraction": _extraction_payload(extraction),
        "summary": _summary_payload(summary),
        "metadata": {
            "full_name": metadata.get("full_name"),
            "private": metadata.get("private"),
            "default_branch": metadata.get("default_branch"),
            "description": metadata.get("description"),
            "archived": metadata.get("archived"),
            "fork": metadata.get("fork"),
            "stargazers_count": metadata.get("stargazers_count"),
            "language": metadata.get("language"),
        },
    }

def _run_summary(run) -> dict:
    """One run as JSON. Counts come from the stored run row."""
    return {
        "run_id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "repo_url": run.repo_url,
        "owner": run.owner,
        "name": run.name,
        "branch_or_ref": run.branch_or_ref,
        "resolved_ref": run.resolved_ref,
        "status": run.status,
        # the failure that ended the run, if one did; null on completed and degraded runs
        "error": run.error,
        "metadata": {
            "default_branch": run.default_branch,
            "description": run.description,
            "language": run.language,
            "private": run.private,
            "archived": run.archived,
            "fork": run.fork,
            "stargazers_count": run.stargazers_count,
        },
        "tree_entry_count": run.tree_entry_count,
        "tree_truncated": run.tree_truncated,
        "tree_error": run.tree_error,
        "classification": {
            "total_entries": run.tree_entry_count,
            "directories": run.directories,
            "selected_count": run.selected_count,
            "skipped_count": run.skipped_count,
            "failed_count": run.failed_count,
        },
        "summary": {
            "status": run.summary_status,
            "text": run.summary_text,
            "model": run.summary_model,
            "error": run.summary_error,
            "prompt_tokens_estimated": run.summary_prompt_tokens,
            "provenance": json.loads(run.summary_provenance) if run.summary_provenance else None,
        },
        "extraction": {
            "selected_total": run.selected_count,
            "files_read": run.files_read,
            "files_failed": run.files_read_failed,
            "files_not_fetched": run.files_not_fetched,
            "read_cap": run.read_cap,
            "cap_applied": bool(run.files_not_fetched),
            "chunk_count": run.chunk_count,
            # the honesty line, stored so it reads the same long after the config changed
            "read_of_selected": (
                f"read {run.files_read} of {run.selected_count} selected files"
            ),
        },
    }


@router.get("/runs", response_class=JSONResponse)
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Recent runs, newest first."""
    runs, total = await storage.list_runs(session, limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_run_summary(r) for r in runs],
    }


@router.get("/runs/{run_id}", response_class=JSONResponse)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    """
    One stored run.

    `stored_identity_holds` is recomputed from the rows rather than read off the run's
    denormalised counts, so a drifted count cannot report itself as consistent.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    summary = _run_summary(run)
    by_status = await storage.reconstruct_counts(session, run_id)
    stored_total = sum(by_status.values())
    summary["stored_rows"] = {
        "by_status": by_status,
        "total": stored_total,
        "skipped_count_by_reason": await storage.counts_by_reason(session, run_id),
        # a degraded run stored no entries, so the identity is vacuous there
        "stored_identity_holds": (
            stored_total == run.tree_entry_count if run.status == "completed" else None
        ),
    }
    return summary


@router.get("/runs/{run_id}/summary", response_class=JSONResponse)
async def get_run_summary(run_id: str, session: AsyncSession = Depends(get_session)):
    """
    The stored summary and the provenance recorded with it.

    Returned together deliberately: the prose is only trustworthy to the extent a reader
    can check it against what was actually read.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    return {
        "run_id": run.id,
        "repo": f"{run.owner}/{run.name}",
        "run_status": run.status,
        "status": run.summary_status,
        "text": run.summary_text,
        "model": run.summary_model,
        "error": run.summary_error,
        "prompt_tokens_estimated": run.summary_prompt_tokens,
        "provenance": json.loads(run.summary_provenance) if run.summary_provenance else None,
    }


async def _summarise_from_storage(
    session: AsyncSession, run, provider: SummaryProvider | None
) -> SummaryResult:
    """
    Summarise a stored run from its stored inventory alone.

    Nothing here touches GitHub or re-reads a file. The chunks are the ones extraction
    already stored, and every provenance input is read back from the run row and the
    entry rows:

    - the counts come from the `analysis_runs` row written when the run was analysed,
    - `skipped_by_reason` is recomputed from `analysis_files`, the same query the
      diagnostics view uses,
    - the chunks come from `analysis_chunks` in their stored order.

    So the grounding contract is identical to the one `/api/analyze` produces: the same
    `build_provenance` inputs go in, and a summary generated an hour later still
    describes the reading that actually happened, not a fresh one.
    """
    chunks = await storage.chunks_for_summary(session, run.id)
    return await summarise(
        repo=f"{run.owner}/{run.name}",
        metadata={
            "description": run.description,
            "language": run.language,
            "resolved_ref": run.resolved_ref,
        },
        run_summary={
            "tree_entry_count": run.tree_entry_count,
            "tree_truncated": run.tree_truncated,
            "selected_count": run.selected_count,
            "skipped_count": run.skipped_count,
            "files_read": run.files_read,
            "files_read_failed": run.files_read_failed,
            "files_not_fetched": run.files_not_fetched,
            "read_cap": run.read_cap,
        },
        skipped_by_reason=await storage.counts_by_reason(session, run.id),
        chunks=chunks,
        cfg=get_summarization_config(),
        call_provider=provider,
    )


@router.post("/runs/{run_id}/summarize", response_class=JSONResponse)
async def resummarise_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    provider: SummaryProvider | None = Depends(get_summary_provider),
):
    """
    Re-generate the summary for a stored run, without re-fetching anything.

    **Why this exists.** Summarisation is the one stage that fails independently of the
    work that fed it. A transient provider 503, or a daily quota that ran out between
    extraction and generation, would otherwise leave a run permanently without a summary
    -- and the only recovery would be re-analysing the repository, spending GitHub calls
    to re-read files RepoBridge already has, on a provider quota measured in hundreds of
    requests per day.

    **What it does not do.** No GitHub call, no file read, no re-classification. The
    stored chunks are the input, and the stored inventory is the provenance. A summary
    produced here describes the reading that happened at analysis time, which is the only
    reading it can honestly describe.

    The result replaces the stored summary. That is the point: the old one was an error
    or an absence. The previous provenance is replaced along with it, so the pair stays
    consistent -- prose and provenance are only meaningful together.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    summary = await _summarise_from_storage(session, run, provider)
    await storage.persist_summary(session, run_id, summary)

    return {
        "run_id": run.id,
        "repo": f"{run.owner}/{run.name}",
        "run_status": run.status,
        **_summary_payload(summary),
    }
