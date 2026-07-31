from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.repobridge.core.input import normalize_github_repo_url, RepoURLValidationError
from src.repobridge.core.models import AnalyzeRequest

router = APIRouter(prefix="/api", tags=["runs"])


@router.post("/analyze", response_class=JSONResponse)
async def analyze_repo(request: AnalyzeRequest):
  """
  Validate the incoming GitHub repo URL and return normalized owner/repo.

  v0.1: this endpoint only validates and normalizes; actual analysis will be wired in later milestones.
  """
  try:
    normalized = normalize_github_repo_url(str(request.repo_url))
  except RepoURLValidationError as e:
    raise HTTPException(status_code=400, detail={"message": e.message})

  return {
    "repo_url": str(request.repo_url),
    "owner": normalized.owner,
    "name": normalized.name,
    "branch_or_ref": request.branch_or_ref,
  }