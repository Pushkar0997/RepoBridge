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
            status_code=e.status_code or 502,
            detail={"message": e.message},
        )

    # Step 3: resolve the ref we will actually ask GitHub for.
    # Explicit request wins; otherwise fall back to the repo's default branch.
    requested_ref = request.branch_or_ref
    resolved_ref = requested_ref or metadata.get("default_branch") or "HEAD"

    # Step 4: fetch the tree for that ref
    tree_preview: list[dict] = []
    tree_entry_count = 0
    tree_truncated = False
    tree_error: str | None = None

    try:
        tree = await fetch_repo_tree(normalized, resolved_ref)
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
        tree_error = f"Tree retrieval failed: {e.message}"
    else:
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