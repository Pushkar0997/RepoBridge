"""
Extraction tests: format handling, notebook cell fidelity, traceability, and the cap.

Pure unit tests — `fetch_and_extract` takes a `fetch` callable, so none of this needs
HTTP or a mock transport.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from repobridge.config import ExtractionConfig
from repobridge.core.extraction import (
    ChunkType,
    ContentStatus,
    ExtractionError,
    content_sha,
    extract_file,
    extract_notebook,
    fetch_and_extract,
)

# --------------------------------------------------------------------------
# per-format extraction
# --------------------------------------------------------------------------


def test_markdown_becomes_a_markdown_chunk():
    chunks = extract_file("README.md", "# Title\n\nSome prose.\n")
    assert len(chunks) == 1
    assert chunks[0].chunk_type is ChunkType.MARKDOWN
    assert "# Title" in chunks[0].text


def test_plain_text_and_rst_become_text_chunks():
    assert extract_file("notes.txt", "hello")[0].chunk_type is ChunkType.TEXT
    assert extract_file("docs/index.rst", "Title\n=====")[0].chunk_type is ChunkType.TEXT


def test_python_preserves_code_structure():
    source = "def f(x):\n    if x:\n        return 1\n    return 0\n"
    chunks = extract_file("src/app.py", source)
    assert chunks[0].chunk_type is ChunkType.CODE
    # indentation and line structure survive verbatim
    assert chunks[0].text == source
    assert "    if x:" in chunks[0].text


@pytest.mark.parametrize("path", ["web/index.js", "web/types.ts", "build.sh", "make.bat"])
def test_code_formats_are_code_chunks(path):
    assert extract_file(path, "x = 1\n")[0].chunk_type is ChunkType.CODE


@pytest.mark.parametrize(
    "path", ["data/config.json", "ci.yml", "ci.yaml", "pyproject.toml", "setup.cfg", "tox.ini"]
)
def test_config_formats_are_data_chunks(path):
    assert extract_file(path, "a: 1\n")[0].chunk_type is ChunkType.DATA


def test_json_content_is_preserved_verbatim():
    body = '{\n  "name": "demo",\n  "version": 1\n}\n'
    chunks = extract_file("package.json", body)
    assert chunks[0].text == body
    assert json.loads(chunks[0].text)["name"] == "demo"


def test_crlf_is_normalised():
    chunks = extract_file("a.py", "line1\r\nline2\r\n")
    assert "\r" not in chunks[0].text
    assert chunks[0].text == "line1\nline2\n"


def test_empty_file_produces_no_chunks_rather_than_an_empty_one():
    """py.typed and .nojekyll are selected but have nothing to extract."""
    assert extract_file("src/pkg/py.typed", "") == []
    assert extract_file("docs/.nojekyll", "\n  \n") == []


# --------------------------------------------------------------------------
# notebooks: the case that matters
# --------------------------------------------------------------------------


def _notebook(cells) -> str:
    return json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


NOTEBOOK = _notebook(
    [
        {"cell_type": "markdown", "source": ["# Bell state\n", "\n", "Intro prose.\n"]},
        {"cell_type": "code", "source": ["import qiskit\n", "qc = qiskit.QuantumCircuit(2)\n"]},
        {"cell_type": "markdown", "source": "## Results"},
        {"cell_type": "code", "source": ["qc.draw()\n"], "outputs": [{"text": "ignored"}]},
    ]
)


def test_notebook_flattens_to_one_chunk_per_cell():
    chunks = extract_notebook("nb.ipynb", NOTEBOOK)
    assert len(chunks) == 4


def test_notebook_markdown_and_code_cells_stay_distinct():
    chunks = extract_notebook("nb.ipynb", NOTEBOOK)
    assert [c.chunk_type for c in chunks] == [
        ChunkType.NOTEBOOK_MARKDOWN,
        ChunkType.NOTEBOOK_CODE,
        ChunkType.NOTEBOOK_MARKDOWN,
        ChunkType.NOTEBOOK_CODE,
    ]


def test_notebook_cell_indices_are_preserved():
    chunks = extract_notebook("nb.ipynb", NOTEBOOK)
    assert [c.cell_index for c in chunks] == [0, 1, 2, 3]
    assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]


def test_notebook_cell_indices_survive_skipped_empty_cells():
    """chunk_index is position among chunks; cell_index is position in the notebook."""
    notebook = _notebook(
        [
            {"cell_type": "markdown", "source": "# One"},
            {"cell_type": "code", "source": "   \n"},  # empty, skipped
            {"cell_type": "code", "source": "print(1)"},
        ]
    )
    chunks = extract_notebook("nb.ipynb", notebook)
    assert len(chunks) == 2
    assert [c.cell_index for c in chunks] == [0, 2]
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_notebook_source_may_be_a_string_or_a_list():
    chunks = extract_notebook("nb.ipynb", NOTEBOOK)
    assert chunks[0].text.startswith("# Bell state")
    assert chunks[2].text == "## Results"


def test_notebook_cell_outputs_are_not_extracted():
    """Only source is content; outputs are execution artefacts."""
    chunks = extract_notebook("nb.ipynb", NOTEBOOK)
    assert all("ignored" not in c.text for c in chunks)


def test_notebook_routed_by_extension_through_extract_file():
    chunks = extract_file("analysis.ipynb", NOTEBOOK)
    assert len(chunks) == 4
    assert chunks[0].chunk_type is ChunkType.NOTEBOOK_MARKDOWN


@pytest.mark.parametrize(
    "content, fragment",
    [
        ("{not json at all", "not valid JSON"),
        ("[1, 2, 3]", "not an object"),
        ('{"metadata": {}}', "no 'cells' key"),
        ('{"cells": "nope"}', "not a list"),
    ],
)
def test_malformed_notebooks_raise_a_specific_error(content, fragment):
    with pytest.raises(ExtractionError) as excinfo:
        extract_notebook("bad.ipynb", content)
    assert fragment in str(excinfo.value)


def test_one_malformed_cell_does_not_discard_the_notebook():
    notebook = _notebook([{"cell_type": "markdown", "source": "# Fine"}, "not-a-cell"])
    chunks = extract_notebook("nb.ipynb", notebook)
    assert len(chunks) == 1
    assert chunks[0].text == "# Fine"


# --------------------------------------------------------------------------
# traceability
# --------------------------------------------------------------------------


def test_every_chunk_carries_its_source_path_and_position():
    for path, content in [
        ("README.md", "# hi"),
        ("src/app.py", "x = 1"),
        ("nb.ipynb", NOTEBOOK),
    ]:
        for chunk in extract_file(path, content):
            assert chunk.source_path == path
            assert chunk.chunk_index is not None
            assert chunk.chunk_index >= 0


def test_notebook_chunks_are_traceable_to_a_cell_not_just_a_file():
    for chunk in extract_file("nb.ipynb", NOTEBOOK):
        assert chunk.cell_index is not None


def test_non_notebook_chunks_have_no_cell_index():
    assert extract_file("a.py", "x = 1")[0].cell_index is None


def test_token_estimate_and_char_count():
    chunk = extract_file("a.md", "a" * 400)[0]
    assert chunk.char_count == 400
    assert chunk.token_estimate() == 100  # chars_per_token default 4
    assert chunk.token_estimate(ExtractionConfig(chars_per_token=8)) == 50


def test_content_sha_is_stable_and_content_dependent():
    assert content_sha("abc") == content_sha("abc")
    assert content_sha("abc") != content_sha("abd")


# --------------------------------------------------------------------------
# orchestration: the cap, failures, and the identity
# --------------------------------------------------------------------------


def _fetcher(contents: dict[str, str], failures: dict[str, Exception] | None = None):
    failures = failures or {}

    async def fetch(path: str) -> str:
        if path in failures:
            raise failures[path]
        return contents[path]

    return fetch


async def test_all_files_read_when_under_the_cap():
    contents = {f"f{i}.md": f"# {i}" for i in range(5)}
    result = await fetch_and_extract(list(contents), _fetcher(contents))

    assert len(result.read) == 5
    assert result.failed == [] and result.not_fetched == []
    assert result.cap_applied is False
    assert result.accounts_for_every_selected_file()


async def test_run_that_hits_the_cap_records_the_rest_as_not_fetched():
    contents = {f"f{i:03d}.md": f"# {i}" for i in range(25)}
    cfg = ExtractionConfig(max_files_per_run=10)

    result = await fetch_and_extract(list(contents), _fetcher(contents), cfg)

    assert len(result.read) == 10
    assert len(result.not_fetched) == 15
    assert result.cap_applied is True
    # nothing was dropped
    assert result.accounts_for_every_selected_file()
    assert result.selected_total == 25


async def test_not_fetched_files_say_why():
    contents = {f"f{i}.md": "x" for i in range(5)}
    result = await fetch_and_extract(list(contents), _fetcher(contents), ExtractionConfig(max_files_per_run=2))

    for skipped in result.not_fetched:
        assert skipped.error
        assert "at most 2 files" in skipped.error
        assert "5 were selected" in skipped.error


async def test_a_file_that_fails_to_fetch_does_not_end_the_run():
    contents = {"a.md": "# a", "b.md": "# b", "c.md": "# c"}
    failures = {"b.md": RuntimeError("GitHub said no")}

    result = await fetch_and_extract(list(contents), _fetcher(contents, failures))

    assert len(result.read) == 2
    assert len(result.failed) == 1
    assert result.failed[0].path == "b.md"
    assert "GitHub said no" in result.failed[0].error
    assert result.accounts_for_every_selected_file()


async def test_a_file_that_fails_to_decode_is_recorded_and_the_run_continues():
    contents = {"good.md": "# fine", "bad.ipynb": "{not json", "after.py": "x = 1"}

    result = await fetch_and_extract(list(contents), _fetcher(contents))

    assert {f.path for f in result.read} == {"good.md", "after.py"}
    assert len(result.failed) == 1
    assert result.failed[0].path == "bad.ipynb"
    assert "not valid JSON" in result.failed[0].error
    # a file that was retrieved but not extractable still has its hash and size
    assert result.failed[0].content_sha
    assert result.failed[0].byte_count == len("{not json")
    assert result.accounts_for_every_selected_file()


async def test_identity_holds_across_read_failed_and_not_fetched():
    contents = {f"f{i}.md": "x" for i in range(10)}
    failures = {"f1.md": RuntimeError("boom"), "f2.md": RuntimeError("boom")}
    cfg = ExtractionConfig(max_files_per_run=6)

    result = await fetch_and_extract(list(contents), _fetcher(contents, failures), cfg)

    assert len(result.read) == 4
    assert len(result.failed) == 2
    assert len(result.not_fetched) == 4
    assert 4 + 2 + 4 == result.selected_total == 10
    assert result.accounts_for_every_selected_file()


async def test_read_files_carry_hash_and_byte_count():
    contents = {"a.md": "# hello"}
    result = await fetch_and_extract(["a.md"], _fetcher(contents))

    read = result.read[0]
    assert read.content_sha == content_sha("# hello")
    assert read.byte_count == len("# hello".encode("utf-8"))


async def test_chunks_from_all_files_are_collected_and_traceable():
    contents = {"a.md": "# a", "nb.ipynb": NOTEBOOK}
    result = await fetch_and_extract(list(contents), _fetcher(contents))

    assert len(result.chunks) == 1 + 4
    assert {c.source_path for c in result.chunks} == {"a.md", "nb.ipynb"}
    for chunk in result.chunks:
        assert chunk.source_path
        assert chunk.chunk_index >= 0


async def test_empty_selection_is_valid():
    result = await fetch_and_extract([], _fetcher({}))
    assert result.selected_total == 0
    assert result.chunks == []
    assert result.accounts_for_every_selected_file()


# --------------------------------------------------------------------------
# bounded concurrency
# --------------------------------------------------------------------------


async def test_reads_run_concurrently_bounded_by_config():
    """At most `max_concurrent_reads` requests are in flight at once."""
    in_flight = 0
    peak = 0

    async def fetch(path: str) -> str:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return "# " + path

    paths = [f"f{i:03d}.md" for i in range(40)]
    result = await fetch_and_extract(paths, fetch, ExtractionConfig(max_concurrent_reads=5))

    assert peak == 5, f"expected the semaphore to cap at 5, saw {peak}"
    assert len(result.read) == 40


async def test_concurrency_is_faster_than_sequential_for_slow_fetches():
    async def fetch(path: str) -> str:
        await asyncio.sleep(0.02)
        return "# x"

    paths = [f"f{i}.md" for i in range(20)]

    start = time.perf_counter()
    await fetch_and_extract(paths, fetch, ExtractionConfig(max_concurrent_reads=10))
    concurrent = time.perf_counter() - start

    start = time.perf_counter()
    await fetch_and_extract(paths, fetch, ExtractionConfig(max_concurrent_reads=1))
    sequential = time.perf_counter() - start

    assert concurrent < sequential / 2


async def test_order_is_preserved_despite_out_of_order_completion():
    """Later files finishing first must not reorder the result."""

    async def fetch(path: str) -> str:
        # earlier paths sleep longer, so completion order is reversed
        await asyncio.sleep(0.05 - int(path[1:3]) * 0.01)
        return "# " + path

    paths = [f"f{i:02d}.md" for i in range(5)]
    result = await fetch_and_extract(paths, fetch, ExtractionConfig(max_concurrent_reads=5))

    assert [f.path for f in result.files] == paths


async def test_one_failure_does_not_cancel_concurrent_siblings():
    async def fetch(path: str) -> str:
        await asyncio.sleep(0.01)
        if path == "f002.md":
            raise RuntimeError("boom")
        return "# ok"

    paths = [f"f{i:03d}.md" for i in range(10)]
    result = await fetch_and_extract(paths, fetch, ExtractionConfig(max_concurrent_reads=5))

    assert len(result.read) == 9
    assert len(result.failed) == 1
    assert result.failed[0].path == "f002.md"
    assert result.accounts_for_every_selected_file()


async def test_concurrency_still_respects_the_cap():
    fetched: list[str] = []

    async def fetch(path: str) -> str:
        fetched.append(path)
        return "# x"

    paths = [f"f{i:03d}.md" for i in range(30)]
    result = await fetch_and_extract(
        paths, fetch, ExtractionConfig(max_files_per_run=7, max_concurrent_reads=5)
    )

    assert len(fetched) == 7, "files beyond the cap must never be requested"
    assert len(result.read) == 7
    assert len(result.not_fetched) == 23
    assert result.accounts_for_every_selected_file()
