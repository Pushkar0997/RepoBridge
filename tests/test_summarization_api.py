"""
Summarisation through the API and into storage.

The provider is injected via `routes_runs.SUMMARY_PROVIDER_OVERRIDE`, so no test reaches
the network. The `_no_real_summariser` fixture in conftest.py unsets the key as a second
guard.

These tests are about the *grounding contract*: what a summary payload must disclose.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.core.summarization import SummarizationError
from repobridge.main import app
from tests.test_api import (
    FILE_CONTENTS,
    REPO_URL,
    _blob,
    _contents_response,
    _dir,
    _install,
    _tree_body,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _api_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    """Install a recording provider and return what it saw."""
    seen: dict = {}

    def install(text="A grounded summary of the repository.", error=None):
        async def call(prompt: str) -> str:
            seen["prompt"] = prompt
            if error is not None:
                raise error
            return text

        monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(routes_runs, "SUMMARY_PROVIDER_OVERRIDE", call)
        return seen

    return install


def _entries():
    return [
        _dir("src"),
        _blob("README.md", 40),
        _blob("src/app.py", 40),
        _blob("nb.ipynb", 400),
        _blob("assets/logo.png", 4000),  # skipped, never read
        _blob("package-lock.json", 900),  # skipped, lockfile
    ]


def _analyze(install_transport, entries=None, content_responder=None):
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries or _entries())),
        content_responder=content_responder,
    )
    return client.post("/api/analyze", json={"repo_url": REPO_URL}).json()


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_summary_is_generated_and_returned(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    summary = body["summary"]

    assert summary["status"] == "ok"
    assert summary["text"] == "A grounded summary of the repository."
    assert summary["model"]
    assert summary["provenance"]


def test_summary_is_persisted_and_readable_via_the_endpoint(install_transport, provider):
    provider()
    body = _analyze(install_transport)

    stored = client.get(f"/api/runs/{body['run_id']}/summary")
    assert stored.status_code == 200
    payload = stored.json()
    assert payload["status"] == "ok"
    assert payload["text"] == body["summary"]["text"]
    # the provenance is stored with it, not recomputed
    assert payload["provenance"]["chunks_total"] == body["summary"]["provenance"]["chunks_total"]


def test_summary_endpoint_404s_for_an_unknown_run():
    assert client.get("/api/runs/nope/summary").status_code == 404


# --------------------------------------------------------------------------
# grounding: the payload discloses what was and was not read
# --------------------------------------------------------------------------


def test_summary_provenance_discloses_skipped_files(install_transport, provider):
    seen = provider()
    body = _analyze(install_transport)
    prov = body["summary"]["provenance"]

    assert prov["skipped_count"] == 2
    assert prov["skipped_by_reason"] == {"lockfile": 1, "non_text_asset": 1}
    assert any("lockfile" in item for item in prov["limitations"])
    # and the model was told
    assert "1 lockfile" in seen["prompt"]


def test_summary_provenance_reports_what_was_read(install_transport, provider):
    provider()
    body = _analyze(install_transport)
    prov = body["summary"]["provenance"]

    assert prov["files_selected"] == 3
    assert prov["files_read"] == 3
    assert prov["read_of_selected"] == "read 3 of 3 selected files"
    assert prov["chunks_total"] == 4
    assert prov["chunks_included"] == 4
    assert prov["chunks_of_total"] == "sent 4 of 4 extracted chunks"


def test_capped_run_discloses_the_cap_in_the_summary(install_transport, provider, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    seen = provider()

    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)
    prov = body["summary"]["provenance"]

    assert prov["files_not_fetched"] == 8
    assert prov["read_cap"] == 2
    assert prov["is_partial"] is True
    assert any("8 selected file(s) were not read" in i for i in prov["limitations"])
    assert "8 selected file(s) were not read" in seen["prompt"]


def test_truncated_tree_is_disclosed_in_the_summary(install_transport, provider):
    seen = provider()
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_entries(), truncated=True)),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    prov = body["summary"]["provenance"]

    assert prov["tree_truncated"] is True
    assert prov["is_partial"] is True
    assert any("truncated the file listing" in i for i in prov["limitations"])
    assert "truncated the file listing" in seen["prompt"]


def test_token_budget_shortfall_is_disclosed(install_transport, provider, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_SUMMARY_TOKEN_BUDGET", "5")
    seen = provider()

    body = _analyze(install_transport)
    prov = body["summary"]["provenance"]

    assert prov["chunks_included"] < prov["chunks_total"]
    assert prov["is_partial"] is True
    assert any("extracted chunks fit the token budget" in i for i in prov["limitations"])
    assert "fit the token budget" in seen["prompt"]


def test_read_failures_are_disclosed(install_transport, provider):
    def content_responder(path: str) -> httpx.Response:
        if path == "src/app.py":
            return httpx.Response(404, json={"message": "Not Found"})
        return _contents_response(path, FILE_CONTENTS.get(path, "x\n"))

    seen = provider()
    body = _analyze(install_transport, content_responder=content_responder)
    prov = body["summary"]["provenance"]

    assert prov["files_read_failed"] == 1
    assert any("could not be read or decoded" in i for i in prov["limitations"])
    assert "could not be read or decoded" in seen["prompt"]


# --------------------------------------------------------------------------
# a degraded run has nothing to summarise
# --------------------------------------------------------------------------


def test_degraded_run_produces_no_content_not_a_summary(install_transport, provider):
    seen = provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()

    assert body["summary"]["status"] == "no_content"
    assert body["summary"]["text"] is None
    assert "nothing to summarise" in body["summary"]["error"]
    # the provider was never called: nothing was sent
    assert "prompt" not in seen


def test_degraded_run_summary_is_persisted_as_no_content(install_transport, provider):
    provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    stored = client.get(f"/api/runs/{run_id}/summary").json()
    assert stored["status"] == "no_content"
    assert stored["text"] is None


def test_a_repo_with_nothing_selected_produces_no_content(install_transport, provider):
    seen = provider()
    entries = [_blob("logo.png", 100), _blob("archive.zip", 100)]
    body = _analyze(install_transport, entries)

    assert body["summary"]["status"] == "no_content"
    assert "prompt" not in seen
    # but the provenance still explains what happened
    assert body["summary"]["provenance"]["skipped_by_reason"] == {"non_text_asset": 2}


# --------------------------------------------------------------------------
# provider failure must not lose the run
# --------------------------------------------------------------------------


def test_provider_rate_limit_does_not_lose_the_run(install_transport, provider):
    provider(error=SummarizationError("The summarisation provider rate-limited this request."))
    body = _analyze(install_transport)

    assert body["summary"]["status"] == "provider_error"
    assert "rate-limited" in body["summary"]["error"]
    # everything else survived
    assert body["classification"]["selected_count"] == 3
    assert body["extraction"]["files_read"] == 3
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["status"] == "completed"
    assert run["extraction"]["chunk_count"] == 4


def test_provider_being_down_does_not_lose_the_run(install_transport, provider):
    provider(error=SummarizationError("Could not reach the summarisation provider."))
    body = _analyze(install_transport)

    assert body["summary"]["status"] == "provider_error"
    stored = client.get(f"/api/runs/{body['run_id']}/summary").json()
    assert stored["status"] == "provider_error"
    # provenance survives, so the run is still explainable
    assert stored["provenance"]["chunks_total"] == 4


def test_missing_key_yields_not_configured_without_failing_the_run(install_transport):
    # the conftest guard already unset the key
    body = _analyze(install_transport)

    assert body["summary"]["status"] == "not_configured"
    assert "REPOBRIDGE_GEMINI_API_KEY" in body["summary"]["error"]
    assert body["extraction"]["files_read"] == 3


# --------------------------------------------------------------------------
# key safety
# --------------------------------------------------------------------------

SECRET_KEY = "AIzaSyAPIKEYTHATMUSTNEVERBEPERSISTED0000"


def test_the_api_key_is_never_stored_or_returned(install_transport, monkeypatch):
    async def call(prompt: str) -> str:
        return "summary text"

    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", SECRET_KEY)
    monkeypatch.setattr(routes_runs, "SUMMARY_PROVIDER_OVERRIDE", call)

    body = _analyze(install_transport)
    run_id = body["run_id"]

    for response in (
        client.post("/api/analyze", json={"repo_url": REPO_URL}),
        client.get(f"/api/runs/{run_id}"),
        client.get(f"/api/runs/{run_id}/summary"),
        client.get(f"/api/runs/{run_id}/files"),
        client.get(f"/api/runs/{run_id}/chunks"),
        client.get(f"/runs/{run_id}"),
    ):
        assert SECRET_KEY not in response.text


async def test_no_stored_value_anywhere_contains_the_key(isolated_database, monkeypatch):
    """Scans every column of every row, as the GitHub token test does."""
    from sqlalchemy import select

    from repobridge.infra.schemas import AnalysisChunk, AnalysisFile, AnalysisRun

    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", SECRET_KEY)

    async with isolated_database.session() as session:
        for model in (AnalysisRun, AnalysisFile, AnalysisChunk):
            rows = (await session.execute(select(model))).scalars().all()
            for row in rows:
                for column in model.__table__.columns:
                    assert SECRET_KEY not in str(getattr(row, column.name))


# --------------------------------------------------------------------------
# the run detail page
# --------------------------------------------------------------------------


def test_run_detail_page_shows_the_summary_and_its_provenance(install_transport, provider):
    provider("This repository provides a demonstration package.")
    body = _analyze(install_transport)

    page = client.get(f"/runs/{body['run_id']}").text
    assert "This repository provides a demonstration package." in page
    assert "Summary" in page
    # the provenance is on the page, not just in the API
    assert "read 3 of 3 selected files" in page
    assert "sent 4 of 4 extracted chunks" in page


def test_run_detail_page_shows_summary_limitations(install_transport, provider, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()

    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body = _analyze(install_transport, entries)

    page = client.get(f"/runs/{body['run_id']}").text
    assert "not read" in page
    assert "partial" in page.lower()


def test_run_detail_page_explains_a_missing_summary(install_transport):
    body = _analyze(install_transport)  # no key configured
    page = client.get(f"/runs/{body['run_id']}").text
    assert "REPOBRIDGE_GEMINI_API_KEY" in page
