"""
`POST /api/runs/{run_id}/summarize` -- re-summarising a stored run.

**Why this endpoint has its own file.** Summarisation is the one stage that fails
independently of everything that fed it: a transient 503, or a daily quota that ran out
between extraction and generation, leaves a perfectly good run with no summary. Without a
way to retry it, the only recovery is re-analysing the repository -- spending GitHub calls
to re-read files already stored.

The contract these tests hold it to:

1. it re-summarises from **stored** chunks, making **no** GitHub call,
2. its provenance is **identical** to the one the original analysis produced, because it
   is computed from the same stored inventory,
3. a provider failure here still does not lose the run.

No test reaches the network: GitHub is a MockTransport and the provider is injected
through `dependency_overrides`.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.core.summarization import SummarizationError
from repobridge.main import app
from tests.test_api import REPO_URL, _blob, _dir, _install, _tree_body

client = TestClient(app)


@pytest.fixture(autouse=True)
def _api_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    """Install a provider through the app's dependency overrides; record what it saw."""
    seen: dict = {"prompts": []}

    def install(text="A grounded summary of the repository.", error=None):
        async def call(prompt: str) -> str:
            seen["prompts"].append(prompt)
            if error is not None:
                raise error
            return text

        monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
        app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call
        return seen

    try:
        yield install
    finally:
        app.dependency_overrides.pop(routes_runs.get_summary_provider, None)


def _entries():
    return [
        _dir("src"),
        _blob("README.md", 40),
        _blob("src/app.py", 40),
        _blob("nb.ipynb", 400),
        _blob("assets/logo.png", 4000),  # skipped, never read
        _blob("package-lock.json", 900),  # skipped, lockfile
    ]


def _analyze(install_transport, entries=None):
    """Analyse once and return (run_id, recorded GitHub calls)."""
    calls = _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries or _entries())),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    return body, calls


# --------------------------------------------------------------------------
# the case this exists for
# --------------------------------------------------------------------------


def test_a_run_whose_summary_failed_can_be_summarised_afterwards(install_transport, provider):
    """A 503 at analysis time must not leave the run permanently without a summary."""
    provider(error=SummarizationError("The summarisation provider returned status 503."))
    body, _ = _analyze(install_transport)
    assert body["summary"]["status"] == "provider_error"

    provider("A grounded summary of the repository.")
    retry = client.post(f"/api/runs/{body['run_id']}/summarize")

    assert retry.status_code == 200
    assert retry.json()["status"] == "ok"
    assert retry.json()["text"] == "A grounded summary of the repository."


def test_the_new_summary_replaces_the_stored_one(install_transport, provider):
    provider(error=SummarizationError("provider down"))
    body, _ = _analyze(install_transport)

    provider("The replacement summary.")
    client.post(f"/api/runs/{body['run_id']}/summarize")

    stored = client.get(f"/api/runs/{body['run_id']}/summary").json()
    assert stored["status"] == "ok"
    assert stored["text"] == "The replacement summary."
    assert stored["error"] is None


def test_a_daily_quota_failure_is_recoverable_the_next_day(install_transport, provider):
    """
    The scenario in full: the quota runs out mid-run, the run is stored intact, and the
    summary is generated later without re-reading anything.
    """
    provider(
        error=SummarizationError(
            "The summarisation provider's daily request quota is exhausted for model "
            "'gemini-3.5-flash-lite'. ... the summary can be generated later."
        )
    )
    body, _ = _analyze(install_transport)
    assert body["summary"]["status"] == "provider_error"
    assert body["extraction"]["chunk_count"] == 4  # the expensive work survived

    provider("Generated the next day.")
    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["status"] == "ok"
    assert retry["provenance"]["chunks_total"] == 4


# --------------------------------------------------------------------------
# it must not re-fetch
# --------------------------------------------------------------------------


def test_no_github_call_is_made(install_transport, provider):
    provider()
    body, calls = _analyze(install_transport)
    calls.clear()

    assert client.post(f"/api/runs/{body['run_id']}/summarize").status_code == 200
    assert calls == [], f"re-summarising must not touch GitHub, but made: {calls}"


def test_no_file_is_re_read(install_transport, provider):
    """Sharper than the call count: not one contents request, whatever else happened."""
    provider()
    body, calls = _analyze(install_transport)
    calls.clear()

    client.post(f"/api/runs/{body['run_id']}/summarize")
    assert [c for c in calls if c[0] == "contents"] == []


def test_the_stored_chunks_are_what_reaches_the_model(install_transport, provider):
    seen = provider()
    body, _ = _analyze(install_transport)
    analysis_prompt = seen["prompts"][-1]

    client.post(f"/api/runs/{body['run_id']}/summarize")
    stored_prompt = seen["prompts"][-1]

    # same content, from the database rather than from GitHub
    assert "# Demo" in stored_prompt
    assert stored_prompt == analysis_prompt


def test_extraction_counts_are_untouched_by_a_re_summary(install_transport, provider):
    provider()
    body, _ = _analyze(install_transport)

    client.post(f"/api/runs/{body['run_id']}/summarize")
    run = client.get(f"/api/runs/{body['run_id']}").json()

    assert run["extraction"]["files_read"] == 3
    assert run["extraction"]["chunk_count"] == 4
    assert run["status"] == "completed"


# --------------------------------------------------------------------------
# the grounding contract must hold identically
# --------------------------------------------------------------------------


def test_provenance_is_identical_to_the_original_analysis(install_transport, provider):
    """
    The load-bearing test. If the stored path computed provenance differently from the
    live path, a re-summarised run would carry prose checked against a different record --
    which is exactly the trust the provenance exists to provide.
    """
    provider()
    body, _ = _analyze(install_transport)

    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()
    assert retry["provenance"] == body["summary"]["provenance"]


def test_provenance_is_identical_for_a_capped_run(install_transport, provider, monkeypatch):
    """The cap is recorded on the run row, so a later summary must still disclose it."""
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")
    provider()
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body, _ = _analyze(install_transport, entries)

    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["provenance"] == body["summary"]["provenance"]
    assert retry["provenance"]["files_not_fetched"] == 8
    assert retry["provenance"]["read_cap"] == 2
    assert retry["provenance"]["is_partial"] is True


def test_skip_reasons_are_recomputed_from_the_stored_rows(install_transport, provider):
    seen = provider()
    body, _ = _analyze(install_transport)

    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["provenance"]["skipped_by_reason"] == {"lockfile": 1, "non_text_asset": 1}
    assert "1 lockfile" in seen["prompts"][-1]


def test_truncation_is_still_disclosed_later(install_transport, provider):
    seen = provider()
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(_entries(), truncated=True)),
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()

    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["provenance"]["tree_truncated"] is True
    assert any("truncated the file listing" in i for i in retry["provenance"]["limitations"])
    assert "truncated the file listing" in seen["prompts"][-1]


# --------------------------------------------------------------------------
# nothing to summarise, and nothing to lose
# --------------------------------------------------------------------------


def test_unknown_run_is_a_404():
    assert client.post("/api/runs/nope/summarize").status_code == 404


def test_a_degraded_run_still_produces_no_content_not_an_invented_summary(
    install_transport, provider
):
    seen = provider()

    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    retry = client.post(f"/api/runs/{run_id}/summarize").json()

    assert retry["status"] == "no_content"
    assert retry["text"] is None
    assert seen["prompts"] == [], "a run with no chunks must never reach the provider"


def test_a_failed_run_has_nothing_to_summarise(install_transport, provider):
    """A repo that 404'd at metadata is stored, has no chunks, and stays honest."""
    seen = provider()
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body([])),
        metadata_responder=lambda request: httpx.Response(404, json={"message": "Not Found"}),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["detail"]["run_id"]

    retry = client.post(f"/api/runs/{run_id}/summarize").json()

    assert retry["status"] == "no_content"
    assert seen["prompts"] == []


def test_a_provider_failure_on_retry_does_not_lose_the_run(install_transport, provider):
    provider()
    body, _ = _analyze(install_transport)

    provider(error=SummarizationError("The summarisation provider returned status 503."))
    retry = client.post(f"/api/runs/{body['run_id']}/summarize")

    assert retry.status_code == 200
    assert retry.json()["status"] == "provider_error"
    # the run, its chunks and its provenance all survive
    run = client.get(f"/api/runs/{body['run_id']}").json()
    assert run["status"] == "completed"
    assert run["extraction"]["chunk_count"] == 4
    assert run["summary"]["provenance"]["chunks_total"] == 4


def test_a_missing_key_is_reported_not_raised(install_transport, provider, monkeypatch):
    provider()
    body, _ = _analyze(install_transport)

    # Production shape with nothing configured. The key must go with the provider: an
    # injected provider is what keeps a set key from reaching the network, so dropping
    # one without the other is how a test would make a real call.
    app.dependency_overrides.pop(routes_runs.get_summary_provider, None)
    monkeypatch.delenv("REPOBRIDGE_GEMINI_API_KEY", raising=False)
    retry = client.post(f"/api/runs/{body['run_id']}/summarize")

    assert retry.status_code == 200
    assert retry.json()["status"] == "not_configured"
    assert "REPOBRIDGE_GEMINI_API_KEY" in retry.json()["error"]


# --------------------------------------------------------------------------
# response shape and key safety
# --------------------------------------------------------------------------


def test_the_response_identifies_the_run_and_the_repo(install_transport, provider):
    provider()
    body, _ = _analyze(install_transport)

    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["run_id"] == body["run_id"]
    assert retry["repo"] == f"{body['owner']}/{body['name']}"
    assert retry["run_status"] == "completed"
    assert set(retry) >= {"status", "text", "model", "error", "provenance"}


def test_the_model_used_is_reported(install_transport, provider, monkeypatch):
    provider()
    body, _ = _analyze(install_transport)

    monkeypatch.setenv("REPOBRIDGE_GEMINI_MODEL", "gemini-3.1-flash-lite")
    retry = client.post(f"/api/runs/{body['run_id']}/summarize").json()

    assert retry["model"] == "gemini-3.1-flash-lite"


SECRET_KEY = "AIzaSyRESUMMARISEKEYMUSTNEVERLEAK000000"


def test_the_api_key_never_appears_in_the_response(install_transport, provider, monkeypatch):
    provider()
    body, _ = _analyze(install_transport)
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", SECRET_KEY)

    response = client.post(f"/api/runs/{body['run_id']}/summarize")
    assert SECRET_KEY not in response.text
