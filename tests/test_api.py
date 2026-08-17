"""
Tests for the /api/analyze endpoint.

All GitHub traffic is faked with httpx.MockTransport; these tests never touch the
network. The transport is injected by monkeypatching httpx.AsyncClient for the
duration of a test, because github_client constructs its own client per call.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from repobridge.core import github_client
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


def _install(monkeypatch, tree_responder) -> list[tuple[str, str | None]]:
    """
    Route every github_client request through a MockTransport.

    `tree_responder` is called with the ref taken from the request path and returns
    the httpx.Response to serve. Returns a list that records the calls made, so tests
    can assert which ref was actually requested from GitHub.
    """
    calls: list[tuple[str, str | None]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == METADATA_PATH:
            calls.append(("metadata", None))
            return httpx.Response(200, json=METADATA)
        if path.startswith(TREE_PATH_PREFIX):
            ref = path[len(TREE_PATH_PREFIX) :]
            calls.append(("tree", ref))
            return tree_responder(ref)
        return httpx.Response(500, json={"message": f"unexpected path: {path}"})

    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(github_client.httpx, "AsyncClient", _MockedAsyncClient)
    return calls


def test_metadata_and_tree_both_succeed(monkeypatch):
    entries = [_dir("src"), _blob("src/app.py", 120), _blob("README.md", 42)]
    calls = _install(monkeypatch, lambda ref: httpx.Response(200, json=_tree_body(entries)))

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


def test_missing_branch_falls_back_to_default_branch(monkeypatch):
    calls = _install(
        monkeypatch, lambda ref: httpx.Response(200, json=_tree_body([_blob("README.md")]))
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})

    assert resp.status_code == 200
    body = resp.json()
    assert body["branch_or_ref"] is None
    assert body["resolved_ref"] == METADATA["default_branch"] == "main"
    assert body["tree_error"] is None
    # the ref actually sent to GitHub is the default branch, not "HEAD"
    assert ("tree", "main") in calls


def test_explicit_bad_ref_returns_404_naming_the_ref(monkeypatch):
    def responder(ref: str) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _install(monkeypatch, responder)

    resp = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "no-such-branch"}
    )

    assert resp.status_code == 404
    message = resp.json()["detail"]["message"]
    assert "no-such-branch" in message
    assert f"{OWNER}/{REPO}" in message


def test_truncated_tree_sets_flag_and_warns_in_tree_error(monkeypatch):
    entries = [_blob(f"file_{i}.py") for i in range(10)]
    _install(
        monkeypatch,
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


def test_rate_limited_tree_returns_200_with_metadata_and_tree_error(monkeypatch):
    def responder(ref: str) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "API rate limit exceeded for 1.2.3.4."}
        )

    _install(monkeypatch, responder)

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


def test_preview_is_capped_but_count_reflects_all_entries(monkeypatch):
    entries = [_blob(f"file_{i}.py", size=i) for i in range(60)]
    _install(monkeypatch, lambda ref: httpx.Response(200, json=_tree_body(entries)))

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
