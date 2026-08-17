from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from repobridge.config import DEFAULT_GITHUB_CONFIG, GitHubConfig, get_github_token
from repobridge.core.input import NormalizedRepoURL

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """
    A GitHub retrieval failure that is safe to show to a caller.

    `status_code` is the HTTP status GitHub returned, or None when the request never
    completed (network error, DNS failure, timeout). Callers use that distinction:
    None means "we could not tell", not "GitHub said no".

    `is_rate_limit` is set explicitly so callers do not have to re-sniff status codes.
    A 403 may or may not be a rate limit; only this client can tell.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        is_rate_limit: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.is_rate_limit = is_rate_limit


def _build_headers(cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": cfg.api_version,
    }
    token = get_github_token(cfg)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limited(resp: httpx.Response) -> bool:
    """
    GitHub signals rate limiting two different ways:

    - primary limits: 403 or 429 with X-RateLimit-Remaining: 0
    - secondary limits: 403 with Retry-After, and X-RateLimit-Remaining is NOT 0

    Both must be recognised. Matching on response body text is unreliable, so we
    match on headers only.
    """
    if resp.status_code not in (403, 429):
        return False
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return resp.headers.get("Retry-After") is not None


def _rate_limit_message(resp: httpx.Response, context: str) -> str:
    is_primary = resp.headers.get("X-RateLimit-Remaining") == "0"
    if is_primary:
        parts = [f"GitHub API rate limit exceeded while {context}."]
    else:
        parts = [f"GitHub secondary rate limit hit while {context}."]

    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        parts.append(f"Retry after {retry_after} seconds.")

    raw_reset = resp.headers.get("X-RateLimit-Reset")
    if raw_reset:
        try:
            reset_at = datetime.fromtimestamp(int(raw_reset), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
        else:
            parts.append(f"The limit resets at {reset_at:%Y-%m-%d %H:%M:%S} UTC.")

    return " ".join(parts)


async def _get(url: str, *, headers: dict[str, str], timeout: float, context: str) -> httpx.Response:
    """
    Perform a GET, converting transport-level failures into GitHubClientError.

    Without this, an httpx.ConnectError / TimeoutException would escape uncaught and
    surface through the API as a 500 with a traceback.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("Network failure while %s: %s", context, type(exc).__name__)
        raise GitHubClientError(
            f"Could not reach the GitHub API while {context} ({type(exc).__name__}). "
            "Check your network connection and try again.",
            status_code=None,
        ) from exc


def _raise_for_error(resp: httpx.Response, *, context: str, not_found_message: str) -> None:
    """
    Translate an error response into GitHubClientError.

    GitHub's raw response body is logged but never included in the message: it goes
    straight into the HTTP response the caller sees.
    """
    if resp.status_code == 404:
        raise GitHubClientError(not_found_message, status_code=404)

    if _is_rate_limited(resp):
        raise GitHubClientError(
            _rate_limit_message(resp, context),
            status_code=resp.status_code,
            is_rate_limit=True,
        )

    if resp.status_code >= 400:
        logger.debug(
            "GitHub API error %s while %s: %s", resp.status_code, context, resp.text[:500]
        )
        raise GitHubClientError(
            f"GitHub API returned status {resp.status_code} while {context}.",
            status_code=resp.status_code,
        )


async def fetch_repo_metadata(
    normalized: NormalizedRepoURL, cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG
) -> dict[str, Any]:
    """
    Fetch basic repository metadata from GitHub REST API.
    """
    context = "fetching repository metadata"
    url = f"{cfg.api_base_url}/repos/{normalized.owner}/{normalized.name}"

    resp = await _get(
        url,
        headers=_build_headers(cfg),
        timeout=cfg.metadata_timeout,
        context=context,
    )
    _raise_for_error(
        resp,
        context=context,
        not_found_message="Repository not found on GitHub.",
    )
    return resp.json()


async def fetch_repo_tree(
    normalized: NormalizedRepoURL,
    ref: str | None = None,
    cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG,
) -> dict[str, Any]:
    """
    Fetch the Git tree for the given repo and ref using GitHub's git/tree API.
    v0.1: we fetch the recursive tree for the default branch or given ref.

    Note: GitHub silently returns a partial tree for very large repositories and sets
    `truncated` in the response body. Callers must check it.
    """
    context = "fetching the repository tree"
    # GitHub's git trees API: /repos/{owner}/{repo}/git/trees/{ref}?recursive=1
    target_ref = ref or "HEAD"
    url = (
        f"{cfg.api_base_url}/repos/{normalized.owner}/{normalized.name}"
        f"/git/trees/{target_ref}?recursive=1"
    )

    resp = await _get(
        url,
        headers=_build_headers(cfg),
        timeout=cfg.tree_timeout,
        context=context,
    )
    _raise_for_error(
        resp,
        context=context,
        not_found_message="Git tree not found for the given ref.",
    )
    return resp.json()
