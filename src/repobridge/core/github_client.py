from __future__ import annotations

import base64
import binascii
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx

from urllib.parse import quote

from repobridge.config import (
    DEFAULT_EXTRACTION_CONFIG,
    DEFAULT_GITHUB_CONFIG,
    ExtractionConfig,
    GitHubConfig,
    get_github_token,
)
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

    `rate_limit` carries the *structured* form of what the message says in prose: which
    quota, how much of it is left, and when it resets. Diagnostics needs those as fields
    rather than as a sentence -- "rate-limit conditions are visible in diagnostics"
    (`evals.md`, moved from Milestone 2) is only useful if the reader can tell whether to
    wait four minutes or to authenticate.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        is_rate_limit: bool = False,
        rate_limit: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.is_rate_limit = is_rate_limit
        self.rate_limit = rate_limit or {}


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


def _rate_limit_details(resp: httpx.Response) -> dict:
    """
    The failing response's own rate-limit headers, as fields.

    **The per-response headers are the authoritative source**, not the `/rate_limit`
    endpoint: `smoke.md` Run 1 measured that endpoint reporting `remaining: 4995` while a
    real request's own `X-RateLimit-Remaining` header read `4978`, and every run since has
    seen it stale. `_is_rate_limited` already reads these headers to make the decision;
    this records what it saw so a reader can act on it.

    `X-RateLimit-Resource` is the one that answers "which quota" -- core, search, graphql
    -- which matters because exhausting one leaves the others usable.
    """
    detail: dict = {
        "kind": "primary" if resp.headers.get("X-RateLimit-Remaining") == "0" else "secondary",
        "resource": resp.headers.get("X-RateLimit-Resource"),
        "limit": resp.headers.get("X-RateLimit-Limit"),
        "remaining": resp.headers.get("X-RateLimit-Remaining"),
        "used": resp.headers.get("X-RateLimit-Used"),
        "retry_after_seconds": resp.headers.get("Retry-After"),
        "authenticated": bool(get_github_token()),
    }

    raw_reset = resp.headers.get("X-RateLimit-Reset")
    if raw_reset:
        detail["reset_epoch"] = raw_reset
        try:
            reset_at = datetime.fromtimestamp(int(raw_reset), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
        else:
            detail["reset_at"] = f"{reset_at:%Y-%m-%d %H:%M:%S} UTC"

    return {k: v for k, v in detail.items() if v is not None}


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

    # The actionable half. An unauthenticated caller is on 60 requests an hour and the
    # fix is one environment variable, but the error never said so -- it named the limit
    # and the reset time and left the reader to know that a token exists. Only added when
    # there is no token: telling an authenticated user to authenticate is noise.
    if is_primary and not get_github_token():
        parts.append(
            "This request was unauthenticated, which is a 60-requests-per-hour limit "
            f"shared across your IP. Setting {DEFAULT_GITHUB_CONFIG.token_env_var} raises "
            "it to 5,000 per hour."
        )

    return " ".join(parts)


@asynccontextmanager
async def open_client(
    timeout: float,
    max_connections: int = 10,
) -> "httpx.AsyncClient":
    """
    A client to be shared across many requests in one run.

    One client per request means one TCP+TLS handshake per request. A 107-file read paid
    107 of them, which is why 8x concurrency only bought 2x throughput. Sharing a client
    reuses connections; `max_connections` should match or exceed the caller's concurrency
    bound so the pool is not the bottleneck.
    """
    limits = httpx.Limits(
        max_connections=max_connections, max_keepalive_connections=max_connections
    )
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        yield client


async def _get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    context: str,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """
    Perform a GET, converting transport-level failures into GitHubClientError.

    Without this, an httpx.ConnectError / TimeoutException would escape uncaught and
    surface through the API as a 500 with a traceback.

    `client` lets a caller share one connection pool across many requests. When omitted a
    client is created for this single request, which is right for the one-off metadata and
    tree calls and wrong for a run that reads 200 files.
    """
    try:
        if client is not None:
            return await client.get(url, headers=headers)
        async with httpx.AsyncClient(timeout=timeout) as own_client:
            return await own_client.get(url, headers=headers)
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
            rate_limit=_rate_limit_details(resp),
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


async def fetch_file_content(
    normalized: NormalizedRepoURL,
    path: str,
    ref: str | None = None,
    cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG,
    extraction_cfg: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG,
    client: httpx.AsyncClient | None = None,
) -> str:
    """
    Fetch one file's decoded text via GitHub's contents API.

    One call per file, per spec.md section 7.4 and the 2026-08-18 amendment recording why
    the tarball alternative was rejected. Callers cap how many times this is invoked; this
    function does not, because it has no view of the run.

    Raises GitHubClientError for HTTP failures and for content that is not decodable UTF-8
    text -- a binary file that slipped past classification is a per-file failure, not a
    reason to end a run.
    """
    context = f"reading {path}"
    quoted = quote(path)
    url = f"{cfg.api_base_url}/repos/{normalized.owner}/{normalized.name}/contents/{quoted}"
    if ref:
        url = f"{url}?ref={quote(ref, safe='')}"

    resp = await _get(
        url,
        headers=_build_headers(cfg),
        timeout=extraction_cfg.content_timeout,
        context=context,
        client=client,
    )
    _raise_for_error(
        resp,
        context=context,
        not_found_message=f"File '{path}' was not found at this ref.",
    )

    payload = resp.json()
    if isinstance(payload, list):
        # the contents API returns a list for directories
        raise GitHubClientError(f"'{path}' is a directory, not a file.", status_code=None)

    encoding = payload.get("encoding")
    raw = payload.get("content")
    if encoding != "base64" or raw is None:
        # files at/above 1MB come back with no inline content; our selection cap is 1MB,
        # so this is unexpected rather than routine -- say so plainly.
        raise GitHubClientError(
            f"GitHub returned no inline content for '{path}' (encoding={encoding!r}).",
            status_code=resp.status_code,
        )

    try:
        data = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise GitHubClientError(f"Content for '{path}' was not valid base64: {exc}") from exc

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubClientError(
            f"'{path}' is not UTF-8 text and cannot be read as content ({exc.reason})."
        ) from exc
