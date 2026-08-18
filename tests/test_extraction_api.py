"""
Extraction through the API and into storage.

Reuses the mock-transport helpers from test_api.py, which serve GitHub's metadata, tree
and contents endpoints. Nothing here touches the network.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from repobridge.main import app
from tests.test_api import (
    FILE_CONTENTS,
    NOTEBOOK_JSON,
    OWNER,
    REPO,
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


def _entries():
    return [
        _dir("src"),
        _blob("README.md", 40),
        _blob("src/app.py", 40),
        _blob("nb.ipynb", 400),
        _blob("assets/logo.png", 4000),  # skipped: never read
    ]


def _analyze(install_transport, entries=None, content_responder=None):
    calls = _install(
        install_transport,
        lambda ref: httpx.Response(200, json=_tree_body(entries or _entries())),
        content_responder=content_responder,
    )
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()
    return body, calls


# --------------------------------------------------------------------------
# the pipeline reads selected files, and only selected files
# --------------------------------------------------------------------------


def test_only_selected_files_are_read(install_transport):
    body, calls = _analyze(install_transport)

    fetched = {path for kind, path in calls if kind == "contents"}
    assert fetched == {"README.md", "src/app.py", "nb.ipynb"}
    # the skipped png and the directory were never requested
    assert "assets/logo.png" not in fetched
    assert "src" not in fetched


def test_extraction_summary_is_returned(install_transport):
    body, _ = _analyze(install_transport)
    extraction = body["extraction"]

    assert extraction["selected_total"] == 3
    assert extraction["files_read"] == 3
    assert extraction["files_failed"] == 0
    assert extraction["files_not_fetched"] == 0
    assert extraction["accounts_for_every_selected_file"] is True
    assert extraction["read_of_selected"] == "read 3 of 3 selected files"
    assert extraction["cap_applied"] is False
    # README (1) + app.py (1) + notebook (2 cells)
    assert extraction["chunk_count"] == 4


def test_degraded_run_has_no_extraction(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    body = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()

    assert body["extraction"] is None
    assert body["tree_error"] is not None


# --------------------------------------------------------------------------
# the cap
# --------------------------------------------------------------------------


def test_run_that_hits_the_cap_says_so_plainly(install_transport, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "5")

    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(20)]
    body, calls = _analyze(install_transport, entries)
    extraction = body["extraction"]

    assert extraction["files_read"] == 5
    assert extraction["files_not_fetched"] == 15
    assert extraction["cap_applied"] is True
    assert extraction["read_cap"] == 5
    assert extraction["read_of_selected"] == "read 5 of 20 selected files"
    assert extraction["accounts_for_every_selected_file"] is True
    # and it only cost 5 content calls, not 20
    assert len([c for c in calls if c[0] == "contents"]) == 5


def test_not_fetched_files_are_stored_with_a_reason(install_transport, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "2")

    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(6)]
    body, _ = _analyze(install_transport, entries)
    run_id = body["run_id"]

    files = client.get(f"/api/runs/{run_id}/files", params={"status": "selected"}).json()
    by_path = {i["path"]: i for i in files["items"]}
    assert len(by_path) == 6

    not_fetched = [i for i in by_path.values() if i.get("content_status") == "not_fetched"]
    assert len(not_fetched) == 4
    for item in not_fetched:
        assert item["content_error"]
        assert "at most 2 files" in item["content_error"]


# --------------------------------------------------------------------------
# failures do not end the run
# --------------------------------------------------------------------------


def test_a_file_that_fails_to_fetch_is_recorded_and_the_run_completes(install_transport):
    def content_responder(path: str) -> httpx.Response:
        if path == "src/app.py":
            return httpx.Response(404, json={"message": "Not Found"})
        return _contents_response(path, FILE_CONTENTS.get(path, "x\n"))

    body, _ = _analyze(install_transport, content_responder=content_responder)
    extraction = body["extraction"]

    assert extraction["files_read"] == 2
    assert extraction["files_failed"] == 1
    assert extraction["failed_sample"][0]["path"] == "src/app.py"
    assert extraction["accounts_for_every_selected_file"] is True
    # the run itself is still completed
    assert client.get(f"/api/runs/{body['run_id']}").json()["status"] == "completed"


def test_a_malformed_notebook_does_not_end_the_run(install_transport):
    def content_responder(path: str) -> httpx.Response:
        text = "{not valid json" if path == "nb.ipynb" else FILE_CONTENTS.get(path, "x\n")
        return _contents_response(path, text)

    body, _ = _analyze(install_transport, content_responder=content_responder)
    extraction = body["extraction"]

    assert extraction["files_read"] == 2
    assert extraction["files_failed"] == 1
    assert "not valid JSON" in extraction["failed_sample"][0]["error"]
    assert extraction["accounts_for_every_selected_file"] is True


def test_non_utf8_content_is_a_per_file_failure(install_transport):
    import base64

    def content_responder(path: str) -> httpx.Response:
        if path == "src/app.py":
            return httpx.Response(
                200,
                json={
                    "path": path,
                    "encoding": "base64",
                    "content": base64.b64encode(b"\xff\xfe\x00binary").decode("ascii"),
                },
            )
        return _contents_response(path, FILE_CONTENTS.get(path, "x\n"))

    body, _ = _analyze(install_transport, content_responder=content_responder)

    assert body["extraction"]["files_failed"] == 1
    assert "not UTF-8" in body["extraction"]["failed_sample"][0]["error"]


# --------------------------------------------------------------------------
# persistence and traceability
# --------------------------------------------------------------------------


def test_stored_content_status_reconstructs_the_identity(install_transport):
    body, _ = _analyze(install_transport)
    run = client.get(f"/api/runs/{body['run_id']}").json()

    files = client.get(
        f"/api/runs/{body['run_id']}/files", params={"status": "selected", "limit": 500}
    ).json()
    statuses = [i["content_status"] for i in files["items"]]
    assert statuses.count("read") == 3
    assert len(statuses) == run["classification"]["selected_count"] == 3


def test_chunks_endpoint_returns_traceable_chunks(install_transport):
    body, _ = _analyze(install_transport)
    run_id = body["run_id"]

    chunks = client.get(f"/api/runs/{run_id}/chunks").json()
    assert chunks["total"] == 4
    assert chunks["run_chunk_count"] == 4
    for item in chunks["items"]:
        # traceability: every chunk knows its file and its position
        assert item["source_path"]
        assert item["chunk_index"] is not None
        assert item["chunk_type"]
        assert "text_preview" in item


def test_notebook_chunks_keep_cell_index_and_type_through_storage(install_transport):
    body, _ = _analyze(install_transport)
    run_id = body["run_id"]

    chunks = client.get(f"/api/runs/{run_id}/chunks", params={"path": "nb.ipynb"}).json()
    assert chunks["total"] == 2

    by_index = sorted(chunks["items"], key=lambda i: i["chunk_index"])
    assert by_index[0]["chunk_type"] == "notebook_markdown"
    assert by_index[0]["cell_index"] == 0
    assert by_index[1]["chunk_type"] == "notebook_code"
    assert by_index[1]["cell_index"] == 1


def test_chunk_text_is_opt_in(install_transport):
    body, _ = _analyze(install_transport)
    run_id = body["run_id"]

    preview = client.get(f"/api/runs/{run_id}/chunks").json()
    assert "text" not in preview["items"][0]
    assert preview["text_included"] is False

    full = client.get(f"/api/runs/{run_id}/chunks", params={"include_text": "true"}).json()
    assert full["text_included"] is True
    assert "text" in full["items"][0]


def test_chunks_filter_by_type(install_transport):
    body, _ = _analyze(install_transport)
    run_id = body["run_id"]

    code = client.get(f"/api/runs/{run_id}/chunks", params={"chunk_type": "notebook_code"}).json()
    assert code["total"] == 1
    assert code["items"][0]["source_path"] == "nb.ipynb"
    # the run total travels alongside the filtered count
    assert code["run_chunk_count"] == 4


def test_chunks_reject_unknown_type_and_unknown_run():
    assert client.get("/api/runs/nope/chunks").status_code == 404


def test_chunks_reject_unknown_chunk_type(install_transport):
    body, _ = _analyze(install_transport)
    resp = client.get(f"/api/runs/{body['run_id']}/chunks", params={"chunk_type": "nonsense"})
    assert resp.status_code == 400


def test_run_records_extraction_counts(install_transport):
    body, _ = _analyze(install_transport)
    run = client.get(f"/api/runs/{body['run_id']}").json()

    assert run["extraction"]["files_read"] == 3
    assert run["extraction"]["chunk_count"] == 4
    assert run["extraction"]["read_of_selected"] == "read 3 of 3 selected files"


# --------------------------------------------------------------------------
# run detail page: the chunk preview
# --------------------------------------------------------------------------


def test_run_detail_page_shows_chunk_counts_by_type(install_transport):
    body, _ = _analyze(install_transport)
    page = client.get(f"/runs/{body['run_id']}")

    assert page.status_code == 200
    assert "Extracted content" in page.text
    assert "notebook_markdown" in page.text
    assert "notebook_code" in page.text
    assert "markdown" in page.text


def test_run_detail_page_states_how_many_files_were_read(install_transport):
    body, _ = _analyze(install_transport)
    page = client.get(f"/runs/{body['run_id']}").text

    # "3 of 3 selected files were read, producing 4 chunks"
    assert "selected files were read" in page
    assert "chunk" in page


def test_run_detail_page_says_how_many_chunks_it_is_showing(install_transport):
    """20 of 127 must never read as 127 of 127."""
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(40)]
    body, _ = _analyze(install_transport, entries)
    page = client.get(f"/runs/{body['run_id']}").text

    assert "Showing" in page
    assert "<strong>20</strong>" in page  # the preview count
    assert "<strong>40</strong>" in page  # the run total


def test_run_detail_page_shows_notebook_cell_index_and_type(install_transport):
    body, _ = _analyze(install_transport)
    page = client.get(f"/runs/{body['run_id']}").text

    assert "nb.ipynb" in page
    assert "notebook_markdown" in page
    assert "notebook_code" in page
    # the Cell column, and the explanation of what it is
    assert "Cell" in page
    assert "notebook cell this chunk came from" in page


def test_run_detail_page_warns_when_the_cap_was_hit(install_transport, monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_MAX_FILES_PER_RUN", "3")
    entries = [_blob(f"src/file_{i:03d}.py", 40) for i in range(10)]
    body, _ = _analyze(install_transport, entries)

    page = client.get(f"/runs/{body['run_id']}").text
    assert "were not read" in page
    assert "at most 3" in page


def test_run_detail_page_reports_read_failures(install_transport):
    def content_responder(path: str) -> httpx.Response:
        if path == "src/app.py":
            return httpx.Response(404, json={"message": "Not Found"})
        return _contents_response(path, FILE_CONTENTS.get(path, "x\n"))

    body, _ = _analyze(install_transport, content_responder=content_responder)
    page = client.get(f"/runs/{body['run_id']}").text
    assert "could not be read or decoded" in page


def test_degraded_run_detail_page_has_no_chunk_section(install_transport):
    def responder(ref: str) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(install_transport, responder)
    run_id = client.post("/api/analyze", json={"repo_url": REPO_URL}).json()["run_id"]

    page = client.get(f"/runs/{run_id}").text
    assert "Extracted content" not in page
