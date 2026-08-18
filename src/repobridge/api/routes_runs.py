from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.core.input import (
    normalize_github_repo_url,
    RepoURLValidationError,
)
from repobridge.core.models import AnalyzeRequest
from repobridge.core.github_client import (
    fetch_repo_metadata,
    fetch_repo_tree,
    GitHubClientError,
)
from repobridge.core.selection import ClassificationResult, classify_tree
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
    request: AnalyzeRequest, session: AsyncSession = Depends(get_session)
):
    """
    Validate the incoming GitHub repo URL, normalize owner/repo, then fetch repository
    metadata and the git tree for the resolved ref.

    v0.1: retrieval, classification and persistence. Extraction and summarisation are not
    built yet. The run is stored and its id returned as `run_id`.

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

    # Step 5: persist. A degraded run is stored too, with its error and whatever
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

    # Step 6: build response
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
