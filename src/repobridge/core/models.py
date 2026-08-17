from __future__ import annotations

from pydantic import BaseModel, HttpUrl, Field


class AnalyzeRequest(BaseModel):
  repo_url: HttpUrl = Field(..., description="Public GitHub repository URL.")
  branch_or_ref: str | None = Field(
    default=None,
    description="Optional branch, tag, or commit to analyze. Defaults to repo's default branch.",
  )
  # No github_token field: v0.1 reads the token from REPOBRIDGE_GITHUB_TOKEN only.
  # See specs/001-repobridge-v0.1/spec.md section 5.