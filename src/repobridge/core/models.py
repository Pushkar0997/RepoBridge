from __future__ import annotations

from pydantic import BaseModel, HttpUrl, Field


class AnalyzeRequest(BaseModel):
  repo_url: HttpUrl = Field(..., description="Public GitHub repository URL.")
  branch_or_ref: str | None = Field(
    default=None,
    description="Optional branch, tag, or commit to analyze. Defaults to repo's default branch.",
  )
  github_token: str | None = Field(
    default=None,
    description="Optional GitHub personal access token for higher rate limits. Kept local.",
  )