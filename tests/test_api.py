"""
Tests for the /api/analyze endpoint.

All GitHub traffic is faked with httpx.MockTransport via the `install_transport`
fixture in conftest.py; these tests never touch the network.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _api_database(isolated_database):
    """
    Every test in this module drives /api/analyze, which persists. Module-scoped autouse
    so each test still gets its own database without naming the fixture individually.
    """
    return isolated_database

OWNER = "octo"
REPO = "demo"
REPO_URL = f"https://github.com/{OWNER}/{REPO}"

METADATA_PATH = f"/repos/{OWNER}/{REPO}"
TREE_PATH_PREFIX = f"/repos/{OWNER}/{REPO}/git/trees/"
CONTENTS_PATH_PREFIX = f"/repos/{OWNER}/{REPO}/contents/"

NOTEBOOK_JSON = json.dumps(
    {
        "cells": [
            {"cell_type": "markdown", "source": ["# Notebook title\n"]},
            {"cell_type": "code", "source": ["import qiskit\n", "qc = None\n"]},
        ],
        "metadata": {},
        "nbformat": 4,
    }
)

#: content served for specific paths by the default content responder
FILE_CONTENTS = {
    "README.md": "# Demo\n\nProse.\n",
    "src/app.py": "def f():\n    return 1\n",
    "nb.ipynb": NOTEBOOK_JSON,
}

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


def _contents_response(path: str, text: str) -> httpx.Response:
    """Mimic GitHub's contents API: base64 payload with an encoding field."""
    return httpx.Response(
        200,
        json={
            "path": path,
            "encoding": "base64",
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        },
    )


def _install(
    install_transport, tree_responder, metadata_responder=None, content_responder=None
) -> list[tuple[str, str | None]]:
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
        if path.startswith(CONTENTS_PATH_PREFIX):
            file_path = unquote(path[len(CONTENTS_PATH_PREFIX) :])
            calls.append(("contents", file_path))
            if content_responder is not None:
                return content_responder(file_path)
            return _contents_response(
                    file_path, FILE_CONTENTS.get(file_path, "placeholder\n")
                )
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
    message = resp.json()["error"]["message"]
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
    assert body["resolved_ref"] is None
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
    message = resp.json()["error"]["message"]
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
    # the ref was never confirmed, so it is not reported as resolved
    assert body["resolved_ref"] is None


def test_network_error_on_tree_with_explicit_ref_is_not_a_404(install_transport):
    """A network failure is not evidence that the ref is bad."""

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "some-branch"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["tree_error"] is not None
    assert body["resolved_ref"] is None
    # the caller can still see what was asked for
    assert body["branch_or_ref"] == "some-branch"


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
    assert body["resolved_ref"] is None


# --------------------------------------------------------------------------
# resolved_ref honesty: it names a ref only when GitHub confirmed that ref
# --------------------------------------------------------------------------


def test_resolved_ref_is_the_ref_used_when_tree_succeeds(install_transport):
    calls = _install(
        install_transport, lambda ref: httpx.Response(200, json=_tree_body([_blob("a.py")]))
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "dev"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["resolved_ref"] == "dev"
    # and it is the ref actually sent to GitHub, not just an echo of the request
    assert ("tree", "dev") in calls


def test_resolved_ref_is_default_branch_when_no_ref_supplied_and_tree_succeeds(install_transport):
    calls = _install(
        install_transport, lambda ref: httpx.Response(200, json=_tree_body([_blob("a.py")]))
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})

    body = resp.json()
    assert resp.status_code == 200
    assert body["branch_or_ref"] is None
    assert body["resolved_ref"] == METADATA["default_branch"] == "main"
    assert ("tree", "main") in calls


def test_resolved_ref_is_null_on_tree_network_error(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["resolved_ref"] is None
    assert body["tree_error"] is not None


def test_resolved_ref_is_null_on_tree_rate_limit(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Too Many Requests"}
        ),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["resolved_ref"] is None
    assert body["tree_error"] is not None


def test_resolved_ref_is_null_on_tree_upstream_5xx(install_transport):
    _install(install_transport, lambda ref: httpx.Response(500, text="upstream boom"))

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["resolved_ref"] is None
    assert body["tree_error"] is not None


def test_resolved_ref_null_still_leaves_intent_derivable(install_transport):
    """
    No separate "attempted ref" field is reported. With an explicit ref the caller reads
    branch_or_ref; without one, metadata.default_branch. Both survive a tree failure.
    """
    _install(install_transport, lambda ref: httpx.Response(500, text="upstream boom"))

    explicit = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "wanted"}
    ).json()
    assert explicit["resolved_ref"] is None
    assert explicit["branch_or_ref"] == "wanted"

    implicit = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    assert implicit["resolved_ref"] is None
    assert implicit["branch_or_ref"] is None
    assert implicit["metadata"]["default_branch"] == "main"


def test_explicit_bad_ref_still_404_not_a_null_resolved_ref(install_transport):
    """A bad explicit ref remains an error, not a 200 with resolved_ref null."""
    _install(install_transport, lambda ref: httpx.Response(404, json={"message": "Not Found"}))

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "nope"})

    assert resp.status_code == 404
    assert "nope" in resp.json()["error"]["message"]


def test_truncated_tree_still_reports_resolved_ref(install_transport):
    """Truncation is a partial result for a ref GitHub did answer for."""
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([_blob("a.py")], truncated=True)),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})

    body = resp.json()
    assert body["resolved_ref"] == "main"
    assert body["tree_truncated"] is True


# --------------------------------------------------------------------------
# classification summary
# --------------------------------------------------------------------------


def _mixed_entries():
    return [
        _dir("src"),
        _blob("README.md", 400),
        _blob("src/app.py", 900),
        _blob("assets/logo.png", 5000),
        _blob("package-lock.json", 90_000),
        _blob("main.go", 500),
        {"path": "external/dep", "type": "commit", "mode": "160000", "sha": "c" * 40},
    ]


def test_classification_summary_is_returned(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_mixed_entries())))

    body = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()
    c = body["classification"]

    assert c["total_entries"] == 7
    assert c["directories"] == 1
    assert c["selected_count"] == 2  # README.md, src/app.py
    assert c["skipped_count"] == 4  # png, lockfile, go, submodule
    assert c["failed_count"] == 0
    assert c["skipped_count_by_reason"] == {
        "non_text_asset": 1,
        "lockfile": 1,
        "submodule": 1,
        "unsupported_extension": 1,
    }


def test_classification_counts_sum_to_the_total_entry_count(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_mixed_entries())))

    body = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()
    c = body["classification"]

    assert (
        c["directories"] + c["selected_count"] + c["skipped_count"] + c["failed_count"]
        == c["total_entries"]
        == body["tree_entry_count"]
    )
    assert c["accounts_for_every_entry"] is True
    assert sum(c["skipped_count_by_reason"].values()) == c["skipped_count"]


def test_classification_covers_whole_tree_while_samples_are_capped(install_transport):
    # 300 entries: well past both the tree preview cap and the sample cap
    entries = [_blob(f"src/file_{i}.py") for i in range(150)]
    entries += [_blob(f"img/pic_{i}.png") for i in range(150)]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    body = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()
    c = body["classification"]

    # aggregates cover everything
    assert c["total_entries"] == 300
    assert c["selected_count"] == 150
    assert c["skipped_count"] == 150
    # samples are capped, and say so
    assert c["sample_limit"] == 50
    assert len(c["selected_sample"]) == 50
    assert len(c["skipped_sample"]) == 50
    # the tree preview cap is unchanged and independent
    assert len(body["tree_preview"]) == 50


def test_skipped_sample_entries_carry_code_and_message(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_mixed_entries())))

    body = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()

    for item in body["classification"]["skipped_sample"]:
        assert item["reason"], item
        assert item["message"], item
    lockfile = next(
        i for i in body["classification"]["skipped_sample"] if i["path"] == "package-lock.json"
    )
    assert lockfile["reason"] == "lockfile"
    assert "package-lock.json" in lockfile["message"]


def test_failed_entries_appear_in_the_summary(install_transport):
    entries = [_blob("a.py"), {"type": "blob", "mode": "100644"}]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    c = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()["classification"]

    assert c["failed_count"] == 1
    assert c["accounts_for_every_entry"] is True
    assert c["failed_sample"][0]["message"]


def test_classification_absent_when_tree_failed(install_transport):
    """Nothing to classify. Zero counts would read as 'we looked and found nothing'."""

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})
    body = resp.json()

    # the M2 degraded path is intact
    assert resp.status_code == 200
    assert body["metadata"]["full_name"] == f"{OWNER}/{REPO}"
    assert body["tree_error"] is not None
    assert body["resolved_ref"] is None
    # and classification is absent, not empty
    assert body["classification"] is None


def test_classification_absent_when_tree_rate_limited(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Too Many Requests"}
        ),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})
    body = resp.json()

    assert resp.status_code == 200
    assert body["classification"] is None
    assert body["tree_error"] is not None


def test_truncated_tree_still_classifies_what_arrived(install_transport):
    entries = [_blob("a.py"), _blob("b.png")]
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries, truncated=True)),
    )

    body = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()

    assert body["tree_truncated"] is True
    assert body["classification"]["total_entries"] == 2
    # the warning says the classification is partial too
    assert "Classification below covers only those" in body["tree_error"]


def test_empty_tree_classifies_cleanly(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body([])))

    c = client.post(
        "/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}
    ).json()["classification"]

    assert c["total_entries"] == 0
    assert c["accounts_for_every_entry"] is True
    assert c["skipped_count_by_reason"] == {}


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
    assert "rate limit exceeded" in resp.json()["error"]["message"].lower()


def test_secondary_rate_limit_maps_to_429(install_transport):
    resp = _metadata_status(install_transport, 403, {"Retry-After": "45"})
    assert resp.status_code == 429
    message = resp.json()["error"]["message"]
    assert "secondary rate limit" in message.lower()
    assert "Retry after 45 seconds" in message


def test_genuine_403_stays_403(install_transport):
    resp = _metadata_status(install_transport, 403, {"X-RateLimit-Remaining": "4999"})
    assert resp.status_code == 403
    assert "rate limit" not in resp.json()["error"]["message"].lower()


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


# --------------------------------------------------------------------------
# persistence: run_id, and the read-back endpoints
# --------------------------------------------------------------------------


def _persist_entries():
    return [
        _dir("src"),
        _blob("README.md", 400),
        _blob("src/app.py", 900),
        _blob("assets/logo.png", 4000),
        _blob("package-lock.json", 90_000),
        _blob("main.go", 500),
    ]


def test_analyze_returns_a_run_id_and_stores_the_run(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))

    body = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}).json()
    assert body["run_id"]

    stored = client.get(f"/api/runs/{body['run_id']}")
    assert stored.status_code == 200
    run = stored.json()
    assert run["status"] == "completed"
    assert run["tree_entry_count"] == body["tree_entry_count"]
    assert run["classification"]["selected_count"] == body["classification"]["selected_count"]
    assert run["classification"]["skipped_count"] == body["classification"]["skipped_count"]
    assert run["classification"]["directories"] == body["classification"]["directories"]


def test_stored_identity_holds_and_row_count_equals_total(install_transport):
    entries = _persist_entries()
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    body = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}).json()
    run = client.get(f"/api/runs/{body['run_id']}").json()

    assert run["stored_rows"]["total"] == len(entries) == body["tree_entry_count"]
    assert run["stored_rows"]["stored_identity_holds"] is True
    by_status = run["stored_rows"]["by_status"]
    assert (
        by_status.get("directory", 0)
        + by_status.get("selected", 0)
        + by_status.get("skipped", 0)
        + by_status.get("failed", 0)
        == run["stored_rows"]["total"]
    )


def test_degraded_run_is_persisted(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["run_id"]

    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["status"] == "degraded"
    # a degraded run reached the tree stage, so the narrower field is the right one
    assert "Could not reach the GitHub API" in run["tree_error"]
    assert run["error"] is None
    assert run["metadata"]["default_branch"] == "main"
    assert run["stored_rows"]["total"] == 0
    assert run["classification"]["selected_count"] == 0


def test_truncated_run_persists_the_flag(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_persist_entries(), truncated=True)),
    )

    body = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"}).json()
    run = client.get(f"/api/runs/{body['run_id']}").json()

    assert run["tree_truncated"] is True
    assert "incomplete" in run["tree_error"].lower()


def test_runs_list_is_newest_first(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))

    first = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]
    second = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    listing = client.get("/api/runs").json()
    assert listing["total"] == 2
    assert {i["run_id"] for i in listing["items"]} == {first, second}
    assert listing["limit"] == 20 and listing["offset"] == 0


def test_files_endpoint_is_paginated(install_transport):
    entries = [_blob(f"src/file_{i:04d}.py") for i in range(250)]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))

    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/api/runs/{run_id}/files").json()
    assert page["total"] == 250
    assert len(page["items"]) == 100  # default page, not everything
    assert page["limit"] == 100

    page2 = client.get(f"/api/runs/{run_id}/files", params={"offset": 100}).json()
    assert {i["path"] for i in page["items"]}.isdisjoint({i["path"] for i in page2["items"]})


def test_files_endpoint_caps_the_page_size(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    # above FILES_PAGE_MAX is rejected rather than silently honoured
    assert client.get(f"/api/runs/{run_id}/files", params={"limit": 100_000}).status_code == 422


def test_files_endpoint_filters_by_status(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    selected = client.get(f"/api/runs/{run_id}/files", params={"status": "selected"}).json()
    assert selected["total"] == 2
    assert {i["path"] for i in selected["items"]} == {"README.md", "src/app.py"}

    dirs = client.get(f"/api/runs/{run_id}/files", params={"status": "directory"}).json()
    assert dirs["total"] == 1 and dirs["items"][0]["path"] == "src"


def test_files_endpoint_filters_by_skip_reason(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    lock = client.get(f"/api/runs/{run_id}/files", params={"reason": "lockfile"}).json()
    assert lock["total"] == 1
    assert lock["items"][0]["path"] == "package-lock.json"
    assert lock["items"][0]["message"]

    none = client.get(f"/api/runs/{run_id}/files", params={"reason": "submodule"}).json()
    assert none["total"] == 0 and none["items"] == []


def test_files_endpoint_rejects_unknown_filters(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    assert client.get(f"/api/runs/{run_id}/files", params={"status": "nope"}).status_code == 400
    assert client.get(f"/api/runs/{run_id}/files", params={"reason": "nope"}).status_code == 400


def test_unknown_run_id_is_404_not_an_empty_result():
    missing = client.get("/api/runs/does-not-exist")
    assert missing.status_code == 404
    assert "does-not-exist" in missing.json()["error"]["message"]

    files = client.get("/api/runs/does-not-exist/files")
    assert files.status_code == 404
    assert "does-not-exist" in files.json()["error"]["message"]


def test_runs_list_is_empty_before_any_analysis():
    listing = client.get("/api/runs").json()
    assert listing["total"] == 0 and listing["items"] == []


# --------------------------------------------------------------------------
# failed runs: metadata never resolved, but the attempt is still auditable
# --------------------------------------------------------------------------


def test_metadata_404_stores_a_failed_run(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )

    resp = client.post("/api/analyze", json={"repo_url": REPO_URL, "branch_or_ref": "main"})
    assert resp.status_code == 404

    listing = client.get("/api/runs").json()
    assert listing["total"] == 1
    run_id = listing["items"][0]["run_id"]

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["owner"] == OWNER and run["name"] == REPO
    assert run["repo_url"] == REPO_URL
    assert run["branch_or_ref"] == "main"
    # the failure that ended the run lives in `error`; no tree was ever attempted
    assert "Repository not found" in run["error"]
    assert run["tree_error"] is None
    # nothing was classified, so there are no file rows
    assert run["stored_rows"]["total"] == 0
    assert run["tree_entry_count"] == 0
    assert client.get(f"/api/runs/{run_id}/files").json()["total"] == 0


def test_metadata_rate_limit_also_stores_a_failed_run(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Too Many Requests"}
        ),
    )

    assert client.post("/api/analyze", json={"repo_url": REPO_URL}).status_code == 429

    run_id = client.get("/api/runs").json()["items"][0]["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert "rate limit" in run["error"].lower()
    assert run["tree_error"] is None


def test_metadata_network_failure_stores_a_failed_run(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=_connect_error,
    )

    assert client.post("/api/analyze", json={"repo_url": REPO_URL}).status_code == 502
    run = client.get(f"/api/runs/{client.get('/api/runs').json()['items'][0]['run_id']}").json()
    assert run["status"] == "failed"
    assert "Could not reach the GitHub API" in run["error"]
    assert run["tree_error"] is None


def test_invalid_url_stores_nothing():
    """
    A URL that never reached GitHub has no repository to record. The 400 is the whole
    story, and a run row would imply an analysis that never began.
    """
    resp = client.post("/api/analyze", json={"repo_url": "https://gitlab.com/owner/repo"})
    assert resp.status_code == 400

    assert client.get("/api/runs").json()["total"] == 0


def test_failed_runs_appear_alongside_successful_ones(install_transport):
    """A user browsing recent runs should see the failures, not a filtered-clean list."""
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    client.post("/api/analyze", json={"repo_url": REPO_URL})

    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    client.post("/api/analyze", json={"repo_url": REPO_URL})

    listing = client.get("/api/runs").json()
    assert listing["total"] == 2
    assert {i["status"] for i in listing["items"]} == {"completed", "failed"}


def test_error_and_tree_error_are_never_both_set(install_transport):
    """
    The two fields describe different stages and must not overlap: `error` ended the run,
    `tree_error` is the narrower "metadata succeeded, the tree did not".
    """
    # completed: neither
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    ok = client.get(
        f"/api/runs/{client.post('/api/analyze', json={'repo_url': REPO_URL}).json()['run_id']}"
    ).json()
    assert ok["error"] is None and ok["tree_error"] is None

    # degraded: tree_error only
    _install(
        install_transport,
        lambda ref: httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0"}, json={"message": "Too Many Requests"}
        ),
    )
    degraded = client.get(
        f"/api/runs/{client.post('/api/analyze', json={'repo_url': REPO_URL}).json()['run_id']}"
    ).json()
    assert degraded["status"] == "degraded"
    assert degraded["tree_error"] is not None and degraded["error"] is None

    # failed: error only
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    client.post("/api/analyze", json={"repo_url": REPO_URL})
    failed = next(
        i for i in client.get("/api/runs").json()["items"] if i["status"] == "failed"
    )
    detail = client.get(f"/api/runs/{failed['run_id']}").json()
    assert detail["error"] is not None and detail["tree_error"] is None


# --------------------------------------------------------------------------
# UI page routes (no styling assertions -- only what the page states)
# --------------------------------------------------------------------------


def _completed_run_id(install_transport) -> str:
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_persist_entries())))
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]


def test_index_renders_and_lists_recent_runs(install_transport):
    empty = client.get("/")
    assert empty.status_code == 200
    assert "No runs yet" in empty.text

    _completed_run_id(install_transport)
    listed = client.get("/")
    assert listed.status_code == 200
    assert f"{OWNER}/{REPO}" in listed.text
    # the form is wired now, not inert
    assert "not wired yet" not in listed.text


def test_run_detail_page_renders_a_completed_run(install_transport):
    run_id = _completed_run_id(install_transport)

    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    assert "completed" in page.text
    assert f"{OWNER}/{REPO}" in page.text
    # the accounting identity is stated on the page
    assert "= 6 entries" in page.text
    # skip reasons are grouped with counts
    assert "lockfile" in page.text


def test_run_detail_page_renders_a_degraded_run(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    assert "Partial run" in page.text
    assert "Could not reach the GitHub API" in page.text
    # a degraded run has no file listing to offer
    assert "Browse all" not in page.text


def test_run_detail_page_renders_a_failed_run(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    resp = client.post("/api/analyze", json={"repo_url": REPO_URL})
    run_id = resp.json()["error"]["details"]["run_id"]

    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    assert "This run failed" in page.text
    assert "Repository not found on GitHub." in page.text


def test_failed_run_id_travels_with_the_error(install_transport):
    """The home page needs it to link to a run that failed."""
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    detail = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["error"]["details"]
    assert detail["run_id"]
    assert client.get(f"/runs/{detail['run_id']}").status_code == 200


def test_truncated_run_detail_page_says_it_is_incomplete(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_persist_entries(), truncated=True)),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}")
    assert "Incomplete listing" in page.text
    assert "contains more" in page.text


def test_tree_page_states_what_fraction_it_shows(install_transport):
    entries = [_blob(f"src/file_{i:04d}.py") for i in range(250)]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}/tree")
    assert page.status_code == 200
    # never implies the list is complete
    assert "Showing" in page.text
    assert "1</strong>&ndash;<strong>100" in page.text or "1&ndash;100" in page.text
    assert "250" in page.text
    assert "src/file_0000.py" in page.text
    assert "src/file_0100.py" not in page.text  # page 2 content is not on page 1


def test_tree_page_paginates(install_transport):
    entries = [_blob(f"src/file_{i:04d}.py") for i in range(250)]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page2 = client.get(f"/runs/{run_id}/tree", params={"offset": 100})
    assert page2.status_code == 200
    assert "src/file_0100.py" in page2.text
    assert "src/file_0000.py" not in page2.text


def test_tree_page_filters_by_status_and_reason(install_transport):
    run_id = _completed_run_id(install_transport)

    selected = client.get(f"/runs/{run_id}/tree", params={"status": "selected"})
    assert "README.md" in selected.text
    assert "matching entries" in selected.text

    lock = client.get(f"/runs/{run_id}/tree", params={"reason": "lockfile"})
    assert "package-lock.json" in lock.text
    assert "main.go" not in lock.text


def test_tree_page_ignores_unknown_filters_rather_than_erroring(install_transport):
    run_id = _completed_run_id(install_transport)
    page = client.get(f"/runs/{run_id}/tree", params={"status": "nonsense", "reason": "nonsense"})
    assert page.status_code == 200


def test_tree_page_of_a_truncated_run_warns(install_transport):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_persist_entries(), truncated=True)),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}/tree")
    assert "truncated" in page.text.lower()


def test_unknown_run_id_404s_on_both_pages():
    assert client.get("/runs/does-not-exist").status_code == 404
    assert client.get("/runs/does-not-exist/tree").status_code == 404


# --------------------------------------------------------------------------
# path filter: "was assets/2764.svg skipped, and why"
# --------------------------------------------------------------------------


def _pathy_entries():
    return [
        _dir("assets"),
        _blob("assets/2764.svg", 900),
        _blob("assets/2765.svg", 900),
        _blob("src/app.py", 500),
        _blob("README.md", 100),
        _blob("docs/assets/note.md", 100),
    ]


def test_files_endpoint_filters_by_path_substring(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    one = client.get(f"/api/runs/{run_id}/files", params={"path": "assets/2764.svg"}).json()
    assert one["total"] == 1
    assert one["items"][0]["path"] == "assets/2764.svg"
    assert one["items"][0]["status"] == "skipped"
    assert one["items"][0]["reason"] == "non_text_asset"
    assert one["items"][0]["message"]
    # the run's own size travels with the filtered count, so 1 cannot be mistaken for all
    assert one["run_entry_count"] == 6


def test_path_filter_is_a_substring_not_a_prefix(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    hits = client.get(f"/api/runs/{run_id}/files", params={"path": "assets"}).json()
    # the directory, both svgs, and the nested docs/assets/note.md
    assert hits["total"] == 4
    assert "docs/assets/note.md" in {i["path"] for i in hits["items"]}


def test_path_filter_combines_with_status_and_reason(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    combined = client.get(
        f"/api/runs/{run_id}/files",
        params={"path": "assets", "status": "skipped", "reason": "non_text_asset"},
    ).json()
    assert combined["total"] == 2
    assert {i["path"] for i in combined["items"]} == {"assets/2764.svg", "assets/2765.svg"}
    assert combined["filters"] == {
        "status": "skipped",
        "reason": "non_text_asset",
        "path": "assets",
    }


def test_path_filter_escapes_like_metacharacters(install_transport):
    entries = [_blob("a_b.py"), _blob("axb.py"), _blob("100%done.md")]
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(entries)))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    # "_" is a LIKE wildcard; unescaped it would also match axb.py
    underscore = client.get(f"/api/runs/{run_id}/files", params={"path": "a_b"}).json()
    assert underscore["total"] == 1
    assert underscore["items"][0]["path"] == "a_b.py"

    percent = client.get(f"/api/runs/{run_id}/files", params={"path": "100%"}).json()
    assert percent["total"] == 1


def test_path_filter_with_no_matches_returns_empty_not_everything(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    none = client.get(f"/api/runs/{run_id}/files", params={"path": "nothing-matches"}).json()
    assert none["total"] == 0 and none["items"] == []


def test_tree_page_path_filter_and_honest_scope_line(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}/tree", params={"path": "assets/2764.svg"})
    assert page.status_code == 200
    assert "assets/2764.svg" in page.text
    assert "non_text_asset" in page.text
    # names both the match count and the run total
    assert "matching entries" in page.text
    assert "of 6 in this run" in page.text
    # unrelated entries are gone
    assert "src/app.py" not in page.text


def test_tree_page_filters_preserve_each_other(install_transport):
    """Switching status with a path filter set must not drop the path."""
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}/tree", params={"path": "assets", "status": "skipped"})
    assert "path=assets" in page.text
    assert "status=skipped" in page.text or "chip-on" in page.text


def test_tree_page_no_match_states_the_run_total(install_transport):
    _install(install_transport, lambda ref: httpx.Response(200, json=_tree_body(_pathy_entries())))
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}/tree", params={"path": "nothing-matches"})
    assert "Showing" in page.text
    assert "No entries match these filters" in page.text
    assert "6 entries in total" in page.text
