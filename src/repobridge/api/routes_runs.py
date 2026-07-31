from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.repobridge.core.input import (
    normalize_github_repo_url,
    RepoURLValidationError,
)
from src.repobridge.core.models import AnalyzeRequest
from src.repobridge.core.github_client import (
    fetch_repo_metadata,
    GitHubClientError,
)

router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/analyze", response_class=JSONResponse)
async def analyze_repo(request: AnalyzeRequest):
    """
    Validate the incoming GitHub repo URL, normalize owner/repo, and fetch basic metadata.
    v0.1: this endpoint does not yet perform full analysis; it just confirms the repo is reachable and returns metadata.
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

    # Step 3: build response
    return {
        "repo_url": str(request.repo_url),
        "owner": normalized.owner,
        "name": normalized.name,
        "branch_or_ref": request.branch_or_ref,
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