"""
Unit tests for the GitHub client.

All traffic is faked with httpx.MockTransport via the `install_transport` fixture in
conftest.py; these tests never touch the network.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from repobridge.config import DEFAULT_GITHUB_CONFIG, GitHubConfig, get_github_token
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


def _raises(exc_factory):
    """Handler that simulates a transport-level failure."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise exc_factory(request)

    return handle


def _responds(status: int, *, headers: dict | None = None, json=None, text=None):
    def handle(request: httpx.Request) -> httpx.Response:
        kwargs = {"headers": headers or {}}
        if text is not None:
            kwargs["text"] = text
        else:
            kwargs["json"] = json if json is not None else {"message": "x"}
        return httpx.Response(status, **kwargs)

    return handle


# --------------------------------------------------------------------------
# config injection
# --------------------------------------------------------------------------


def test_build_headers_is_not_a_coroutine_function():
    assert not inspect.iscoroutinefunction(github_client._build_headers)


def test_build_headers_uses_injected_config_api_version():
    headers = github_client._build_headers(GitHubConfig(api_version="1999-01-01"))
    assert headers["X-GitHub-Api-Version"] == "1999-01-01"
    assert headers["Accept"] == "application/vnd.github+json"


def test_build_headers_omits_authorization_without_token(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    assert "Authorization" not in github_client._build_headers()


def test_build_headers_sets_authorization_from_env(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", "token-from-env")
    assert github_client._build_headers()["Authorization"] == "Bearer token-from-env"


def test_get_github_token_honours_custom_env_var(monkeypatch):
    """A config with a different token_env_var must actually take effect."""
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SOME_OTHER_TOKEN_VAR", "token-from-custom-var")
    cfg = GitHubConfig(token_env_var="SOME_OTHER_TOKEN_VAR")

    assert get_github_token(cfg) == "token-from-custom-var"
    # and the default config, whose var is unset, still sees nothing
    assert get_github_token(DEFAULT_GITHUB_CONFIG) is None


def test_build_headers_honours_custom_env_var(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SOME_OTHER_TOKEN_VAR", "token-from-custom-var")
    cfg = GitHubConfig(token_env_var="SOME_OTHER_TOKEN_VAR")

    assert github_client._build_headers(cfg)["Authorization"] == "Bearer token-from-custom-var"


async def test_injected_config_base_url_is_used(install_transport):
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"full_name": "octo/demo"})

    install_transport(handle)
    await fetch_repo_metadata(REPO, TEST_CONFIG)
    assert seen == ["https://fake.test/repos/octo/demo"]


# --------------------------------------------------------------------------
# network errors
# --------------------------------------------------------------------------


async def test_metadata_network_error_becomes_client_error(install_transport):
    install_transport(_raises(lambda req: httpx.ConnectError("boom", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    err = excinfo.value
    # no status_code: the request never completed, GitHub did not say no
    assert err.status_code is None
    assert err.is_rate_limit is False
    assert "Could not reach the GitHub API" in err.message
    assert "ConnectError" in err.message
    assert "Traceback" not in err.message


async def test_tree_network_error_becomes_client_error(install_transport):
    install_transport(_raises(lambda req: httpx.ConnectTimeout("slow", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "main", TEST_CONFIG)

    assert excinfo.value.status_code is None
    assert "ConnectTimeout" in excinfo.value.message


async def test_timeout_is_also_caught(install_transport):
    install_transport(_raises(lambda req: httpx.ReadTimeout("timed out", request=req)))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.status_code is None


# --------------------------------------------------------------------------
# primary rate limits
# --------------------------------------------------------------------------


async def test_429_with_remaining_zero_is_rate_limit(install_transport):
    install_transport(_responds(429, headers={"X-RateLimit-Remaining": "0"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is True
    assert "rate limit exceeded" in excinfo.value.message.lower()
    assert excinfo.value.status_code == 429


async def test_403_with_remaining_zero_is_rate_limit(install_transport):
    install_transport(_responds(403, headers={"X-RateLimit-Remaining": "0"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is True
    assert "rate limit exceeded" in excinfo.value.message.lower()
    assert excinfo.value.status_code == 403


async def test_rate_limit_message_includes_reset_time(install_transport):
    # 1893456000 == 2030-01-01 00:00:00 UTC
    install_transport(
        _responds(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"})
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert "2030-01-01 00:00:00 UTC" in excinfo.value.message


async def test_unparseable_reset_header_does_not_break_message(install_transport):
    install_transport(
        _responds(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "not-a-number"})
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is True
    assert "resets at" not in excinfo.value.message


# --------------------------------------------------------------------------
# secondary rate limits (403 + Retry-After, no X-RateLimit-Remaining: 0)
# --------------------------------------------------------------------------


async def test_secondary_rate_limit_is_detected_via_retry_after(install_transport):
    install_transport(
        _responds(
            403,
            headers={"Retry-After": "60", "X-RateLimit-Remaining": "4999"},
            json={"message": "You have exceeded a secondary rate limit."},
        )
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    err = excinfo.value
    assert err.is_rate_limit is True
    assert "secondary rate limit" in err.message.lower()
    assert "Retry after 60 seconds" in err.message


async def test_secondary_rate_limit_without_remaining_header_at_all(install_transport):
    install_transport(_responds(403, headers={"Retry-After": "120"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "main", TEST_CONFIG)

    assert excinfo.value.is_rate_limit is True
    assert "Retry after 120 seconds" in excinfo.value.message


async def test_primary_limit_wording_wins_when_both_signals_present(install_transport):
    install_transport(
        _responds(429, headers={"X-RateLimit-Remaining": "0", "Retry-After": "30"})
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    message = excinfo.value.message
    assert "rate limit exceeded" in message.lower()
    assert "secondary" not in message.lower()
    assert "Retry after 30 seconds" in message


# --------------------------------------------------------------------------
# things that are NOT rate limits
# --------------------------------------------------------------------------


async def test_403_that_is_not_a_rate_limit_gets_generic_message(install_transport):
    install_transport(
        _responds(
            403,
            headers={"X-RateLimit-Remaining": "4999"},
            json={"message": "Forbidden: account suspended"},
        )
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is False
    assert "rate limit" not in excinfo.value.message.lower()
    assert "403" in excinfo.value.message
    assert excinfo.value.status_code == 403


async def test_403_with_rate_limit_wording_in_body_but_no_headers_is_not_rate_limit(
    install_transport,
):
    """The old implementation matched on body text; that was fragile."""
    install_transport(
        _responds(403, json={"message": "API rate limit exceeded for 1.2.3.4"})
    )

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is False
    assert "rate limit" not in excinfo.value.message.lower()


async def test_500_is_not_flagged_as_rate_limit_even_with_retry_after(install_transport):
    install_transport(_responds(500, headers={"Retry-After": "5"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.is_rate_limit is False
    assert excinfo.value.status_code == 500


# --------------------------------------------------------------------------
# response bodies must not leak
# --------------------------------------------------------------------------

SECRET = "ghp_SUPERSECRETTOKENVALUE1234567890"


async def test_500_body_is_not_echoed_in_message(install_transport):
    install_transport(_responds(500, text=f"internal failure, token={SECRET}"))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert SECRET not in excinfo.value.message
    assert SECRET not in str(excinfo.value)
    assert "500" in excinfo.value.message


async def test_tree_500_body_is_not_echoed_in_message(install_transport):
    install_transport(_responds(500, text=f"internal failure, token={SECRET}"))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "main", TEST_CONFIG)

    assert SECRET not in excinfo.value.message


# --------------------------------------------------------------------------
# not found / success paths still work
# --------------------------------------------------------------------------


async def test_metadata_404(install_transport):
    install_transport(_responds(404, json={"message": "Not Found"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_metadata(REPO, TEST_CONFIG)

    assert excinfo.value.status_code == 404
    assert excinfo.value.is_rate_limit is False
    assert "Repository not found" in excinfo.value.message


async def test_tree_404(install_transport):
    install_transport(_responds(404, json={"message": "Not Found"}))

    with pytest.raises(GitHubClientError) as excinfo:
        await fetch_repo_tree(REPO, "nope", TEST_CONFIG)

    assert excinfo.value.status_code == 404


async def test_tree_defaults_to_head_when_no_ref(install_transport):
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"truncated": False, "tree": []})

    install_transport(handle)
    await fetch_repo_tree(REPO, None, TEST_CONFIG)
    assert seen == ["/repos/octo/demo/git/trees/HEAD"]


async def test_tree_success_returns_payload(install_transport):
    payload = {"sha": "abc", "truncated": False, "tree": [{"path": "a.py", "type": "blob"}]}
    install_transport(lambda req: httpx.Response(200, json=payload))

    assert await fetch_repo_tree(REPO, "main", TEST_CONFIG) == payload
