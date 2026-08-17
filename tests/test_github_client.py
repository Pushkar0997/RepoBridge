"""
Unit tests for the GitHub client.

All traffic is faked with httpx.MockTransport; these tests never touch the network.

Note on the monkeypatch: config injection (added so tests can supply their own
GitHubConfig) does not give us a seam for the HTTP transport, because the client still
builds its own httpx.AsyncClient per call. Injecting a transport would mean putting a
test-only field on GitHubConfig, so the monkeypatch stays.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from repobridge.config import GitHubConfig
from repobridge.core import github_client
from repobridge.core.github_client import (
    GitHubClientError,
    fetch_repo_metadata,
    fetch_repo_tree,
)
from repobridge.core.input import NormalizedRepoURL

REPO = NormalizedRepoURL(owner="octo", name="demo")

# A config pointed at a fake host, to prove the injected config is actually used.
TEST_CONFIG = GitHubConfig(api_base_url="https://fake.test", metadata_timeout=1.0, tree_timeout=1.0)


def _install(monkeypatch, handler) -> None:
    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client.httpx, "AsyncClient", _MockedAsyncClient)


def _raises(handler):
    """Handler that simulates a transport-level failure."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise handler(request)

    return handle


# --------------------------------------------------------------------------
# config injection
# --------------------------------------------------------------------------


def test_build_headers_is_not_a_coroutine_function():
    assert not inspect.iscoroutinefunction(github_client._build_headers)


def test_build_headers_uses_injected_config_api_version():
    cfg = GitHubConfig(api_version="1999-01-01")
    headers = github_client._build_headers(cfg)
    assert headers["X-GitHub-Api-Version"] == "1999-01-01"
    assert headers["Accept"] == "application/vnd.github+json"


def test_build_headers_omits_authorization_without_token(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    assert "Authorization" not in github_client._build_headers()


def test_build_headers_sets_authorization_from_env(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", "token-from-env")
    assert github_client._build_headers()["Authorization"] == "Bearer token-from-env"


async def test_injected_config_base_url_is_used(monkeypatch):
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"full_name": "octo/demo"})

    _install(monkeypatch, handle)
    await fetch_repo_metadata(REPO, TEST_CONFIG)
    assert seen == ["https://fake.test/repos/octo/demo"]


# --------------------------------------------------------------------------
# network errors
# --------------------------------------------------------------------------


async def test_metadata_network_error_becomes_client_error(monkeypatch):
    _install(monkeypatch, _raises(lambda req: httpx.ConnectError("boom", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    err = excinfo.value
    # no status_code: the request never completed, GitHub did not say no
    assert err.status_code is None
    assert "Could not reach the GitHub API" in err.message
    assert "ConnectError" in err.message
    # message is a sentence, not a dump
    assert "Traceback" not in err.message


async def test_tree_network_error_becomes_client_error(monkeypatch):
    _install(monkeypatch, _raises(lambda req: httpx.ConnectTimeout("slow", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "main", TEST_CONFIG)

    assert excinfo.value.status_code is None
    assert "ConnectTimeout" in excinfo.value.message


async def test_timeout_is_also_caught(monkeypatch):
    _install(monkeypatch, _raises(lambda req: httpx.ReadTimeout("timed out", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.status_code is None


# --------------------------------------------------------------------------
# rate limits
# --------------------------------------------------------------------------


async def test_429_with_remaining_zero_is_rate_limit(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Too Many Requests"}
        ),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "rate limit exceeded" in excinfo.value.message.lower()
    assert excinfo.value.status_code == 429


async def test_403_with_remaining_zero_is_rate_limit(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(
            403, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Forbidden"}
        ),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "rate limit exceeded" in excinfo.value.message.lower()
    assert excinfo.value.status_code == 403


async def test_rate_limit_message_includes_reset_time(monkeypatch):
    # 2030-01-01 00:00:00 UTC
    _install(
        monkeypatch,
        lambda req: httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"},
            json={"message": "Forbidden"},
        ),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "2030-01-01 00:00:00 UTC" in excinfo.value.message


async def test_unparseable_reset_header_does_not_break_message(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "not-a-number"},
            json={"message": "Forbidden"},
        ),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "rate limit exceeded" in excinfo.value.message.lower()
    assert "resets at" not in excinfo.value.message


async def test_403_that_is_not_a_rate_limit_gets_generic_message(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "4999"},
            json={"message": "Forbidden: account suspended"},
        ),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    message = excinfo.value.message
    assert "rate limit" not in message.lower()
    assert "403" in message
    assert excinfo.value.status_code == 403


async def test_403_with_rate_limit_wording_in_body_but_no_header_is_not_rate_limit(monkeypatch):
    """The old implementation matched on body text; that was fragile."""
    _install(
        monkeypatch,
        lambda req: httpx.Response(403, json={"message": "API rate limit exceeded for 1.2.3.4"}),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "rate limit" not in excinfo.value.message.lower()


# --------------------------------------------------------------------------
# response bodies must not leak
# --------------------------------------------------------------------------

SECRET = "ghp_SUPERSECRETTOKENVALUE1234567890"


async def test_500_body_is_not_echoed_in_message(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(500, text=f"internal failure, token={SECRET}"),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert SECRET not in excinfo.value.message
    assert SECRET not in str(excinfo.value)
    assert "500" in excinfo.value.message


async def test_tree_500_body_is_not_echoed_in_message(monkeypatch):
    _install(
        monkeypatch,
        lambda req: httpx.Response(500, text=f"internal failure, token={SECRET}"),
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "main", TEST_CONFIG)

    assert SECRET not in excinfo.value.message


# --------------------------------------------------------------------------
# not found / success paths still work
# --------------------------------------------------------------------------


async def test_metadata_404(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(404, json={"message": "Not Found"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.status_code == 404
    assert "Repository not found" in excinfo.value.message


async def test_tree_404(monkeypatch):
    _install(monkeypatch, lambda req: httpx.Response(404, json={"message": "Not Found"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "nope", TEST_CONFIG)

    assert excinfo.value.status_code == 404


async def test_tree_defaults_to_head_when_no_ref(monkeypatch):
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"truncated": False, "tree": []})

    _install(monkeypatch, handle)
    await fetch_repo_tree(REPO, None, TEST_CONFIG)
    assert seen == ["/repos/octo/demo/git/trees/HEAD"]


async def test_tree_success_returns_payload(monkeypatch):
    payload = {"sha": "abc", "truncated": False, "tree": [{"path": "a.py", "type": "blob"}]}
    _install(monkeypatch, lambda req: httpx.Response(200, json=payload))

    result = await fetch_repo_tree(REPO, "main", TEST_CONFIG)
    assert result == payload
