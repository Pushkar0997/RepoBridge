"""
Tests for the /api/analyze endpoint.

All GitHub traffic is faked with httpx.MockTransport via the `install_transport`
fixture in conftest.py; these tests never touch the network.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from repobridge.main import app

client = TestClient(app)

OWNER = "octo"
REPO = "demo"
REPO_URL = f"https://github.com/{OWNER}/{REPO}"

METADATA_PATH = f"/repos/{OWNER}/{REPO}"
TREE_PATH_PREFIX = f"/repos/{OWNER}/{REPO}/git/trees/"

METADATA = {
    "full_name": f"{OWNER}/{REPO}",
    "private": False,
    "default_branch": "main",
    "description": "A demo repository.",
    "archived": False,
    "fork": False,
    "stargazers_count": 3,
    "language": "Python",
}


def _blob(path: str, size: int = 100) -> dict:
    return {"path": path, "mode": "100644", "type": "blob", "sha": "b" * 40, "size": size}


def _dir(path: str) -> dict:
    return {"path": path, "mode": "040000", "type": "tree", "sha": "t" * 40}


def _tree_body(entries: list[dict], truncated: bool = False) -> dict:
    return {"sha": "a" * 40, "url": "https://api.github.com/...", "truncated": truncated, "tree": entries}


def _install(install_transport, tree_responder, metadata_responder=None) -> list[tuple[str, str | None]]:
    """
    Serve the two GitHub endpoints /api/analyze uses, on top of the shared
    `install_transport` fixture from conftest.py.

    `tree_responder` is called with the ref taken from the request path and returns
    the httpx.Response to serve. `metadata_responder` defaults to a successful 200.
    Either may raise an httpx error to simulate a transport-level failure.

    Returns a list that records the calls made, so tests can assert which ref was
    actually requested from GitHub.
    """
    calls: list[tuple[str, str | None]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == METADATA_PATH:
            calls.append(("metadata", None))
            if metadata_responder is not None:
                return metadata_responder(request)
            return httpx.Response(200, json=METADATA)
        if path.startswith(TREE_PATH_PREFIX):
            ref = path[len(TREE_PATH_PREFIX) :]
            calls.append(("tree", ref))
            return tree_responder(ref)
        return httpx.Response(500, json={"message": f"unexpected path: {path}"})

    install_transport(handle)
    return calls


def test_metadata_and_tree_both_succeed(install_transport):
    entries = [_dir("src"), _blob("src/app.py", 120), _blob("README.md", 42)]
    calls = _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_ref"] == "main"
    assert body["tree_entry_count"] == 3
    assert body["tree_truncated"] is False
    assert body["tree_error"] is None
    assert len(body["tree_preview"]) == 3
    assert body["tree_preview"][1] == {
        "path": "src/app.py",
        "type": "blob",
        "size": 120,
        "mode": "100644",
    }
    # directories have no size in GitHub's tree payload
    assert body["tree_preview"][0]["size"] is None
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"
    assert ("tree", "main") in calls


def test_missing_branch_falls_back_to_default_branch(install_transport):
    calls = _install(
        install_transport, lambda ref: httpx.Response(200, json=_tree_body([_blob("README.md")]))
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})

    assert resp.status_code == 200
    body = resp.json()
    assert body["branch_or_ref"] is None
    assert body["resolved_ref"] == METADATA["default_branch"] == "main"
    assert body["tree_error"] is None
    # the ref actually sent to GitHub is the default branch, not "HEAD"
    assert ("tree", "main") in calls


def test_explicit_bad_ref_returns_404_naming_the_ref(install_transport):
    def responder(ref: str) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _install(install_transport, responder)

    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )

    assert resp.status_code == 404
    message = resp.json()["detail"]["message"]
    assert "no-such-branch" in message
    assert f"{OWNER}/{REPO}" in message


def test_truncated_tree_sets_flag_and_warns_in_tree_error(install_transport):
    entries = [_blob(f"file_{i}.py") for i in range(10)]
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries, truncated=True)),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["tree_truncated"] is True
    # truncation must not be discoverable only via the boolean
    assert body["tree_error"] is not None
    assert "incomplete" in body["tree_error"].lower()
    assert body["tree_entry_count"] == 10


def test_rate_limited_tree_returns_200_with_metadata_and_tree_error(install_transport):
    def responder(ref: str) -> httpx.Response:
        # rate limiting is detected from headers, not from the body text
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "Forbidden"},
        )

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    # metadata survived
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"
    assert body["metadata"]["default_branch"] == "main"
    # tree did not
    assert body["tree_error"] is not None
    assert "rate limit" in body["tree_error"].lower()
    assert body["tree_preview"] == []
    assert body["tree_entry_count"] == 0
    assert body["tree_truncated"] is False


def test_preview_is_capped_but_count_reflects_all_entries(install_transport):
    entries = [_blob(f"file_{i}.py", size=i) for i in range(60)]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tree_preview"]) == 50
    assert body["tree_entry_count"] == 60
    assert body["tree_preview"][0]["path"] == "file_0.py"
    assert body["tree_preview"][-1]["path"] == "file_49.py"
    # a capped preview is not truncation by GitHub
    assert body["tree_truncated"] is False
    assert body["tree_error"] is None


# --------------------------------------------------------------------------
# network failures: metadata is fatal, tree degrades
# --------------------------------------------------------------------------


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def test_network_error_on_metadata_fails_the_request(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=_connect_error,
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    # no status_code on the error -> 502, not a 500 with a traceback
    assert resp.status_code == 502
    message = resp.json()["detail"]["message"]
    assert "Could not reach the GitHub API" in message
    assert "Traceback" not in message


def test_network_error_on_tree_degrades_to_200(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    # metadata survived
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"
    # tree did not, and says so
    assert body["tree_error"] is not None
    assert "Could not reach the GitHub API" in body["tree_error"]
    assert body["tree_preview"] == []
    assert body["tree_entry_count"] == 0


def test_network_error_on_tree_with_explicit_ref_is_not_a_404(install_transport):
    """A network failure is not evidence that the ref is bad."""

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "some-branch"})

    assert resp.status_code == 200
    assert resp.json()["tree_error"] is not None


def test_429_rate_limit_on_tree_degrades_to_200(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(
            429,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1893456000"},
            json={"message": "Too Many Requests"},
        ),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    assert "rate limit exceeded" in body["tree_error"].lower()
    assert "2030-01-01 00:00:00 UTC" in body["tree_error"]
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"


# --------------------------------------------------------------------------
# status mapping: GitHub's code is not automatically ours
# --------------------------------------------------------------------------


def _metadata_status(install_transport, status: int, headers: dict | None = None):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(
            status, headers=headers or {}, json={"message": "x"}
        ),
    )
    return client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})


def test_upstream_500_maps_to_502(install_transport):
    assert _metadata_status(install_transport, 500).status_code == 502


def test_upstream_503_maps_to_502(install_transport):
    assert _metadata_status(install_transport, 503).status_code == 502


def test_primary_rate_limit_maps_to_429_not_403(install_transport):
    resp = _metadata_status(install_transport, 403, {"X-RateLimit-Remaining": "0"})
    assert resp.status_code == 429
    assert "rate limit exceeded" in resp.json()["detail"]["message"].lower()


def test_secondary_rate_limit_maps_to_429(install_transport):
    resp = _metadata_status(install_transport, 403, {"Retry-After": "45"})
    assert resp.status_code == 429
    message = resp.json()["detail"]["message"]
    assert "secondary rate limit" in message.lower()
    assert "Retry after 45 seconds" in message


def test_genuine_403_stays_403(install_transport):
    resp = _metadata_status(install_transport, 403, {"X-RateLimit-Remaining": "4999"})
    assert resp.status_code == 403
    assert "rate limit" not in resp.json()["detail"]["message"].lower()


def test_401_stays_401(install_transport):
    assert _metadata_status(install_transport, 401).status_code == 401


def test_404_stays_404(install_transport):
    assert _metadata_status(install_transport, 404).status_code == 404


def test_secondary_rate_limit_on_tree_still_degrades_to_200(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(403, headers={"Retry-After": "45"}, json={"message": "x"}),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    body = resp.json()
    assert "secondary rate limit" in body["tree_error"].lower()
    assert "Retry after 45 seconds" in body["tree_error"]
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"


# --------------------------------------------------------------------------
# GitHub response bodies must never reach the caller
# --------------------------------------------------------------------------

SECRET = "ghp_SUPERSECRETTOKENVALUE1234567890"


def test_github_error_body_does_not_reach_the_caller_via_metadata(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(
            500, text=f"internal error, token={SECRET}"
        ),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    # upstream 5xx is reported as 502: RepoBridge did not fail, GitHub did
    assert resp.status_code == 502
    assert SECRET not in resp.text


def test_github_error_body_does_not_reach_the_caller_via_tree(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(500, text=f"internal error, token={SECRET}"),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    assert resp.status_code == 200
    assert SECRET not in resp.text
    assert resp.json()["tree_error"] is not None


# --------------------------------------------------------------------------
# token surface
# --------------------------------------------------------------------------


def test_github_token_is_not_a_request_field(install_transport):
    """v0.1 reads the token from the environment only; see spec.md section 5."""
    from repobridge.core.models import AnalyzeRequest

    assert "github_token" not in AnalyzeRequest.model_fields

    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body([_blob("a.py")])))
    resp = client.post(
        "/api/analyze",
        json={"repo_url": REPO_URL, "branch_or_ref": "main", "github_token": SECRET},
    )

    # the field is ignored, not honoured, and never echoed back
    assert resp.status_code == 200
    assert SECRET not in resp.text
