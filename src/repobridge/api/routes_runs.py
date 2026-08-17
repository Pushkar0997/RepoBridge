from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

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


@router.post("/analyze", response_class=JSONResponse)
async def analyze_repo(request: AnalyzeRequest):
    """
    Validate the incoming GitHub repo URL, normalize owner/repo, then fetch repository
    metadata and the git tree for the resolved ref.

    v0.1: this endpoint does not yet perform full analysis (no selection, extraction, or
    persistence); it confirms the repo is reachable and reports what the tree lookup saw.

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
        # Surface GitHub API errors cleanly
        raise HTTPException(
            status_code=_status_for(e),
            detail={"message": e.message},
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
        if tree_truncated:
            # Truncation must never be discoverable only by noticing a boolean.
            tree_error = (
                "GitHub truncated the tree response for this repository, so the file "
                f"listing is incomplete. {tree_entry_count} entries were returned; the "
                "repository contains more."
            )

    # Step 5: build response
    return {
        "repo_url": str(request.repo_url),
        "owner": normalized.owner,
        "name": normalized.name,
        "branch_or_ref": request.branch_or_ref,
        "resolved_ref": resolved_ref,
        "tree_preview": tree_preview,
        "tree_entry_count": tree_entry_count,
        "tree_truncated": tree_truncated,
        "tree_error": tree_error,
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