"""
One repository, one analysis, every surface cross-checked against every other.

**This file was empty.** `tasks.md` names it under Milestone 6 ("simulate a small repo
analysis and check that a non-empty summary is produced") and again under Milestone 10
("cover a full small-repo analysis from API perspective"), and it shipped with zero tests
in it for five milestones -- a filename that looked like coverage and was not. Found during
release hardening.

**What it adds that the per-stage suites do not.** `test_api.py`, `test_extraction_api.py`,
`test_summarization_api.py`, `test_diagnostics.py` and `test_ui.py` each verify one stage
thoroughly, in isolation, against a fixture built for it. None of them asserts that the
stages *agree with each other*: that the file count on the run row equals the number of
file rows the files endpoint returns, that the chunk count in the summary's provenance
equals what the chunks endpoint serves, that the diagnostics timeline reports the same
numbers the run detail page prints. Each stage can be individually correct and collectively
inconsistent, and that is the failure mode a stage-shaped test cannot see.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.api import routes_runs
from repobridge.main import app
from tests.test_api import REPO_URL, _blob, _contents_response, _dir, _install, _tree_body

client = TestClient(app)

SUMMARY_TEXT = "A small library with a README, one module and a notebook."


@pytest.fixture(autouse=True)
def _e2e_database(isolated_database):
    return isolated_database


@pytest.fixture
def provider(monkeypatch):
    async def call(prompt: str) -> str:
        return SUMMARY_TEXT

    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
    app.dependency_overrides[routes_runs.get_summary_provider] = lambda: call
    try:
        yield
    finally:
        app.dependency_overrides.pop(routes_runs.get_summary_provider, None)


#: A small repository with one of everything the pipeline treats differently.
ENTRIES = [
    _dir("src"),
    _dir("assets"),
    _blob("README.md", 120),
    _blob("src/app.py", 200),
    _blob("notebook.ipynb", 900),
    _blob("assets/logo.png", 5000),      # skipped: non-text asset
    _blob("package-lock.json", 4000),    # skipped: lockfile
]

NOTEBOOK = (
    '{"cells": ['
    '{"cell_type": "markdown", "source": ["# Title\\n"]},'
    '{"cell_type": "code", "source": ["print(1)\\n"]}'
    '], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
)

CONTENTS = {
    "README.md": "# Demo\n\nA small library.\n",
    "src/app.py": "def main():\n    return 1\n",
    "notebook.ipynb": NOTEBOOK,
}


@pytest.fixture
def analysis(install_transport, provider):
    """One complete run, and everything the API says about it afterwards."""
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(ENTRIES)),
        content_responder=lambda path: _contents_response(path, CONTENTS[path]),
    )
    created = client.post("/api/analyze", json={"repo_url": REPO_URL})
    assert created.status_code == 200, created.text
    body = created.json()
    run_id = body["run_id"]

    def get(suffix=""):
        resp = client.get(f"/api/runs/{run_id}{suffix}")
        assert resp.status_code == 200, f"{suffix}: {resp.text}"
        return resp.json()

    return {
        "run_id": run_id,
        "analyze": body,
        "run": get(),
        "files": get("/files?limit=500"),
        "chunks": get("/chunks?limit=200&include_text=true"),
        "summary": get("/summary"),
        "diagnostics": get("/diagnostics"),
    }


# --------------------------------------------------------------------------
# the journey completes
# --------------------------------------------------------------------------


def test_a_small_repository_analyses_end_to_end(analysis):
    body = analysis["analyze"]

    assert body["resolved_ref"] == "main"
    assert body["tree_entry_count"] == len(ENTRIES)
    assert body["tree_truncated"] is False
    assert body["tree_error"] is None
    assert body["classification"]["selected_count"] == 3
    assert body["classification"]["skipped_count"] == 2
    assert body["extraction"]["files_read"] == 3
    assert body["summary"]["status"] == "ok"
    assert body["summary"]["text"] == SUMMARY_TEXT


def test_a_notebook_is_split_into_markdown_and_code_cells(analysis):
    """The one extraction behaviour that is not simply "read the file"."""
    kinds = {
        (c["source_path"], c["chunk_type"])
        for c in analysis["chunks"]["items"]
        if c["source_path"] == "notebook.ipynb"
    }
    assert ("notebook.ipynb", "notebook_markdown") in kinds
    assert ("notebook.ipynb", "notebook_code") in kinds
    cells = [
        c["cell_index"] for c in analysis["chunks"]["items"]
        if c["source_path"] == "notebook.ipynb"
    ]
    assert sorted(cells) == [0, 1], "cell positions are preserved, not invented"


# --------------------------------------------------------------------------
# the surfaces agree with each other
# --------------------------------------------------------------------------


def test_the_run_row_agrees_with_the_files_endpoint(analysis):
    run, files = analysis["run"], analysis["files"]

    assert files["unfiltered_total"] == run["tree_entry_count"]
    by_status = {}
    for item in files["items"]:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1

    assert by_status.get("selected", 0) == run["classification"]["selected_count"]
    assert by_status.get("skipped", 0) == run["classification"]["skipped_count"]
    assert by_status.get("directory", 0) == run["classification"]["directories"]
    # and the run's own recomputation of the same thing
    assert run["stored_rows"]["stored_identity_holds"] is True


def test_the_accounting_identity_holds_across_every_surface(analysis):
    """`directories + selected + skipped + failed == entries`, from three sources."""
    run = analysis["run"]
    c = run["classification"]
    assert (
        c["directories"] + c["selected_count"] + c["skipped_count"] + c["failed_count"]
        == c["total_entries"]
    )
    assert analysis["analyze"]["classification"]["accounts_for_every_entry"] is True
    assert sum(run["stored_rows"]["by_status"].values()) == run["tree_entry_count"]


def test_the_extraction_identity_holds_across_every_surface(analysis):
    """`selected == read + failed + not_fetched`, one stage later."""
    ex = analysis["analyze"]["extraction"]
    assert ex["files_read"] + ex["files_failed"] + ex["files_not_fetched"] == ex["selected_total"]
    assert ex["accounts_for_every_selected_file"] is True

    read_paths = {
        item["path"] for item in analysis["files"]["items"]
        if item["content_status"] == "read"
    }
    assert len(read_paths) == ex["files_read"]
    assert read_paths == set(CONTENTS)


def test_the_chunks_endpoint_agrees_with_the_summary_provenance(analysis):
    chunks, provenance = analysis["chunks"], analysis["summary"]["provenance"]

    assert chunks["unfiltered_total"] == provenance["chunks_total"]
    assert chunks["run_chunk_count"] == provenance["chunks_total"]
    assert provenance["chunks_included"] + provenance["chunks_excluded"] == provenance["chunks_total"]
    # nothing was over budget on a repository this small, so the summary saw every chunk
    assert provenance["chunks_included"] == chunks["unfiltered_total"]
    assert provenance["is_partial"] is False
    # ...but two entries were skipped without reading, and the summary says so. `is_partial`
    # is about coverage of what was *selected*; a skip is a limitation either way.
    assert provenance["limitations"] == [
        "Skipped without reading: 1 lockfile, 1 non_text_asset."
    ]


def test_every_chunk_traces_to_a_file_that_was_actually_read(analysis):
    """The grounding contract, checked as a join rather than asserted."""
    read_paths = {
        item["path"] for item in analysis["files"]["items"]
        if item["content_status"] == "read"
    }
    for chunk in analysis["chunks"]["items"]:
        assert chunk["source_path"] in read_paths, (
            f"chunk from {chunk['source_path']}, which was never read"
        )


def test_the_diagnostics_timeline_reports_the_same_numbers_as_the_run(analysis):
    run, diagnostics = analysis["run"], analysis["diagnostics"]
    events = {e["stage"]: e for e in diagnostics["items"] if e["level"] == "info"}

    assert events["tree"]["details"]["entries"] == run["tree_entry_count"]
    assert events["classification"]["details"]["selected"] == run["classification"]["selected_count"]
    assert events["content"]["details"]["files_read"] == analysis["analyze"]["extraction"]["files_read"]
    assert events["extraction"]["details"]["chunks"] == analysis["chunks"]["unfiltered_total"]
    assert events["persistence"]["details"]["run_id"] == analysis["run_id"]


def test_the_skip_reasons_agree_between_the_run_and_the_file_rows(analysis):
    by_reason = analysis["run"]["stored_rows"]["skipped_count_by_reason"]
    from_rows = {}
    for item in analysis["files"]["items"]:
        if item["status"] == "skipped":
            from_rows[item["reason"]] = from_rows.get(item["reason"], 0) + 1

    assert by_reason == from_rows
    assert sum(by_reason.values()) == analysis["run"]["classification"]["skipped_count"]
    assert set(by_reason) == {"non_text_asset", "lockfile"}


# --------------------------------------------------------------------------
# and it survives a restart
# --------------------------------------------------------------------------


def test_everything_is_readable_again_after_the_app_restarts(
    install_transport, provider, file_database
):
    """
    A second engine against the same file. `evals.md` Milestone 10: "the app can be
    restarted and still function normally".

    Uses `file_database` rather than the module's `isolated_database`: the latter is
    in-memory, and reopening an in-memory URL gives a *different*, empty database -- which
    would make this test pass for the wrong reason if it asserted the run was gone, and
    fail confusingly when it asserts the run is there.
    """
    _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(ENTRIES)),
        content_responder=lambda path: _contents_response(path, CONTENTS[path]),
    )
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]
    before = client.get(f"/api/runs/{run_id}/chunks").json()["unfiltered_total"]

    from repobridge.infra import db as db_module

    reopened = db_module.set_database(file_database())   # a new engine on the same file
    try:
        with TestClient(app) as second_process:
            run = second_process.get(f"/api/runs/{run_id}").json()
            assert run["status"] == "completed"
            assert run["classification"]["selected_count"] == 3
            assert run["stored_rows"]["stored_identity_holds"] is True

            chunks = second_process.get(f"/api/runs/{run_id}/chunks").json()
            assert chunks["unfiltered_total"] == before

            assert second_process.get(f"/api/runs/{run_id}/summary").json()["text"] == SUMMARY_TEXT
            assert second_process.get(f"/api/runs/{run_id}/diagnostics").json()["total"] > 0
            # and the pages render from the reopened database, not from anything cached
            assert second_process.get(f"/runs/{run_id}").status_code == 200
            assert second_process.get(f"/runs/{run_id}/tree").status_code == 200
    finally:
        db_module.set_database(reopened)
