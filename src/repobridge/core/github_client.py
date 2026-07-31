from __future__ import annotations

from typing import Any

import httpx

from src.repobridge.config import GitHubConfig, get_github_token
from src.repobridge.core.input import NormalizedRepoURL


class GitHubClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def _build_headers() -> dict[str, str]:
    cfg = GitHubConfig()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": cfg.api_version,
    }
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_repo_metadata(normalized: NormalizedRepoURL) -> dict[str, Any]:
    """
    Fetch basic repository metadata from GitHub REST API.
    """
    cfg = GitHubConfig()
    url = f"{cfg.api_base_url}/repos/{normalized.owner}/{normalized.name}"
    headers = await _build_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 404:
        raise GitHubClientError("Repository not found on GitHub.", status_code=404)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise GitHubClientError("GitHub API rate limit exceeded.", status_code=403)
    if resp.status_code >= 400:
        raise GitHubClientError(
            f"GitHub API error {resp.status_code}: {resp.text}",
            status_code=resp.status_code,
        )

    return resp.json()


async def fetch_repo_tree(normalized: NormalizedRepoURL, ref: str | None = None) -> dict[str, Any]:
    """
    Fetch the Git tree for the given repo and ref using GitHub's git/tree API.
    v0.1: we fetch the recursive tree for the default branch or given ref.
    """
    cfg = GitHubConfig()
    # GitHub's git trees API: /repos/{owner}/{repo}/git/trees/{ref}?recursive=1
    target_ref = ref or "HEAD"
    url = f"{cfg.api_base_url}/repos/{normalized.owner}/{normalized.name}/git/trees/{target_ref}?recursive=1"
    headers = await _build_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 404:
        raise GitHubClientError("Git tree not found for the given ref.", status_code=404)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        raise GitHubClientError("GitHub API rate limit exceeded while fetching tree.", status_code=403)
    if resp.status_code >= 400:
        raise GitHubClientError(
            f"GitHub API error {resp.status_code}: {resp.text}",
            status_code=resp.status_code,
        )

    return resp.json()