"""
Summarisation tests.

The provider is always injected, so no test makes a network call. The bulk of these test
the *grounding contract*: what the summary payload must disclose, and what must never
reach the model.
"""

from __future__ import annotations

import pytest

from repobridge.config import SummarizationConfig
from repobridge.core.summarization import (
    ChunkRef,
    SummarizationError,
    SummaryStatus,
    build_prompt,
    build_provenance,
    rank_chunks,
    select_within_budget,
    summarise,
)

CFG = SummarizationConfig()


def chunk(path: str, text: str = "content", chunk_type: str = "markdown", index: int = 0,
          tokens: int | None = None, cell: int | None = None) -> ChunkRef:
    return ChunkRef(
        source_path=path,
        chunk_index=index,
        chunk_type=chunk_type,
        text=text,
        token_estimate=tokens if tokens is not None else max(1, len(text) // 4),
        cell_index=cell,
    )


RUN = {
    "tree_entry_count": 40,
    "tree_truncated": False,
    "selected_count": 3,
    "skipped_count": 0,
    "files_read": 3,
    "files_read_failed": 0,
    "files_not_fetched": 0,
    "read_cap": 200,
}


async def _no_sleep(seconds: float) -> None:
    """Stand-in for asyncio.sleep. Retry tests assert the schedule, never wait on it."""


def _provider(text: str = "A grounded summary."):
    async def call(prompt: str) -> str:
        return text

    return call


def _recording_provider(text: str = "ok"):
    seen: dict = {}

    async def call(prompt: str) -> str:
        seen["prompt"] = prompt
        return text

    return call, seen


# --------------------------------------------------------------------------
# ranking: the Milestone 5 open item
# --------------------------------------------------------------------------


def test_root_readme_ranks_first():
    chunks = [
        chunk(".github/workflows/ci.yml", chunk_type="data"),
        chunk("src/deep/nested/module.py", chunk_type="code"),
        chunk("README.md"),
    ]
    assert rank_chunks(chunks)[0].source_path == "README.md"


def test_root_readme_outranks_a_nested_readme():
    ranked = rank_chunks([chunk("docs/guide/README.md"), chunk("README.md")])
    assert [c.source_path for c in ranked] == ["README.md", "docs/guide/README.md"]


def test_orienting_documents_rank_above_ordinary_files():
    ranked = rank_chunks(
        [chunk("src/util.py", chunk_type="code"), chunk("ARCHITECTURE.md"), chunk("CHANGELOG.md")]
    )
    # architecture before changelog (order of _ORIENTING_NAMES), both before source
    assert [c.source_path for c in ranked][:2] == ["ARCHITECTURE.md", "CHANGELOG.md"]


def test_explanatory_directories_outrank_peripheral_ones():
    ranked = rank_chunks(
        [
            chunk(".github/ISSUE_TEMPLATE/bug.md"),
            chunk("tests/test_thing.py", chunk_type="code"),
            chunk("docs/usage.md"),
        ]
    )
    assert ranked[0].source_path == "docs/usage.md"
    # .github and tests are both peripheral, and rank below docs
    assert {c.source_path for c in ranked[1:]} == {
        ".github/ISSUE_TEMPLATE/bug.md",
        "tests/test_thing.py",
    }


def test_shallower_paths_rank_above_deeper_ones():
    ranked = rank_chunks(
        [chunk("a/b/c/d/deep.md"), chunk("top.md"), chunk("a/b/mid.md")]
    )
    assert [c.source_path for c in ranked] == ["top.md", "a/b/mid.md", "a/b/c/d/deep.md"]


def test_prose_ranks_above_code_at_the_same_depth():
    ranked = rank_chunks(
        [chunk("src/z.py", chunk_type="code"), chunk("src/a.md", chunk_type="markdown")]
    )
    assert ranked[0].source_path == "src/a.md"


def test_ranking_is_deterministic_and_keeps_a_files_chunks_in_order():
    chunks = [
        chunk("nb.ipynb", chunk_type="notebook_code", index=2),
        chunk("nb.ipynb", chunk_type="notebook_code", index=0),
        chunk("nb.ipynb", chunk_type="notebook_code", index=1),
    ]
    ranked = rank_chunks(chunks)
    assert [c.chunk_index for c in ranked] == [0, 1, 2]
    assert rank_chunks(chunks) == ranked  # stable across calls


def test_ranking_does_not_promote_large_files():
    """Size is deliberately not a signal: a big generated file is not more explanatory."""
    ranked = rank_chunks(
        [
            chunk("data/generated.json", text="x" * 50_000, chunk_type="data"),
            chunk("README.md", text="short"),
        ]
    )
    assert ranked[0].source_path == "README.md"


# --------------------------------------------------------------------------
# token budget
# --------------------------------------------------------------------------


def test_budget_selects_within_the_limit():
    chunks = [chunk(f"f{i}.md", tokens=100) for i in range(10)]
    selected, used = select_within_budget(chunks, 350)
    assert len(selected) == 3
    assert used == 300


def test_budget_keeps_ranked_order():
    chunks = rank_chunks([chunk("z.md", tokens=10), chunk("README.md", tokens=10)])
    selected, _ = select_within_budget(chunks, 100)
    assert selected[0].source_path == "README.md"


def test_budget_skips_an_oversized_chunk_but_keeps_later_smaller_ones():
    chunks = [chunk("big.md", tokens=1000), chunk("small.md", tokens=10)]
    selected, used = select_within_budget(chunks, 100)
    assert [c.source_path for c in selected] == ["small.md"]
    assert used == 10


def test_everything_fits_when_the_budget_is_large():
    chunks = [chunk(f"f{i}.md", tokens=10) for i in range(5)]
    selected, used = select_within_budget(chunks, 10_000)
    assert len(selected) == 5 and used == 50


# --------------------------------------------------------------------------
# provenance: the enforcement mechanism
# --------------------------------------------------------------------------


def test_provenance_reports_a_complete_read_as_complete():
    prov = build_provenance(
        run_summary=RUN, skipped_by_reason={}, chunks_total=5, chunks_included=5,
        tokens_estimated=100, budget=1000,
    )
    assert prov["is_partial"] is False
    assert prov["limitations"] == []
    assert prov["read_of_selected"] == "read 3 of 3 selected files"
    assert prov["chunks_of_total"] == "sent 5 of 5 extracted chunks"


def test_provenance_discloses_skipped_files_by_reason():
    prov = build_provenance(
        run_summary={**RUN, "skipped_count": 23},
        skipped_by_reason={"non_text_asset": 7, "unsupported_extension": 16},
        chunks_total=5, chunks_included=5, tokens_estimated=10, budget=1000,
    )
    assert prov["skipped_by_reason"] == {"non_text_asset": 7, "unsupported_extension": 16}
    assert any("7 non_text_asset" in item for item in prov["limitations"])


def test_provenance_discloses_the_read_cap():
    prov = build_provenance(
        run_summary={**RUN, "files_read": 200, "files_not_fetched": 11_015, "read_cap": 200},
        skipped_by_reason={}, chunks_total=200, chunks_included=200,
        tokens_estimated=10, budget=1000,
    )
    assert prov["is_partial"] is True
    assert any("11015 selected file(s) were not read" in i for i in prov["limitations"])
    assert any("at most 200 files" in i for i in prov["limitations"])


def test_provenance_discloses_tree_truncation():
    prov = build_provenance(
        run_summary={**RUN, "tree_truncated": True},
        skipped_by_reason={}, chunks_total=5, chunks_included=5,
        tokens_estimated=10, budget=1000,
    )
    assert prov["tree_truncated"] is True
    assert prov["is_partial"] is True
    assert any("truncated the file listing" in i for i in prov["limitations"])


def test_provenance_discloses_chunks_dropped_by_the_budget():
    prov = build_provenance(
        run_summary=RUN, skipped_by_reason={}, chunks_total=100, chunks_included=40,
        tokens_estimated=1000, budget=1000,
    )
    assert prov["chunks_excluded"] == 60
    assert prov["is_partial"] is True
    assert any("40 of 100 extracted chunks" in i for i in prov["limitations"])


def test_provenance_discloses_read_failures():
    prov = build_provenance(
        run_summary={**RUN, "files_read": 2, "files_read_failed": 1},
        skipped_by_reason={}, chunks_total=2, chunks_included=2,
        tokens_estimated=10, budget=1000,
    )
    assert any("could not be read or decoded" in i for i in prov["limitations"])


def test_provenance_names_the_token_estimate_as_a_heuristic():
    prov = build_provenance(
        run_summary=RUN, skipped_by_reason={}, chunks_total=1, chunks_included=1,
        tokens_estimated=10, budget=1000,
    )
    assert "heuristic" in prov["token_estimate_method"]


# --------------------------------------------------------------------------
# the prompt states the inventory
# --------------------------------------------------------------------------


def test_prompt_states_what_was_read_and_what_was_not():
    prov = build_provenance(
        run_summary={**RUN, "files_read": 5, "files_not_fetched": 195, "read_cap": 5},
        skipped_by_reason={"non_text_asset": 7},
        chunks_total=50, chunks_included=10, tokens_estimated=100, budget=100,
    )
    prompt = build_prompt(
        repo="octo/demo", metadata={"resolved_ref": "main"}, provenance=prov,
        chunks=[chunk("README.md", text="# Demo")],
    )
    assert "WHAT WAS READ" in prompt
    assert "WHAT WAS NOT READ" in prompt
    assert "read 5 of 3 selected files" in prompt or "read 5 of" in prompt
    assert "195 selected file(s) were not read" in prompt
    assert "7 non_text_asset" in prompt
    assert "must not describe anything listed above as not read" in prompt


def test_prompt_includes_chunk_provenance_headers():
    prompt = build_prompt(
        repo="octo/demo", metadata={},
        provenance=build_provenance(
            run_summary=RUN, skipped_by_reason={}, chunks_total=2, chunks_included=2,
            tokens_estimated=10, budget=100,
        ),
        chunks=[
            chunk("README.md", text="# Demo"),
            chunk("nb.ipynb", text="import x", chunk_type="notebook_code", index=1, cell=3),
        ],
    )
    assert "--- README.md [markdown] ---" in prompt
    assert "notebook cell 3" in prompt


def test_prompt_says_nothing_was_missed_when_nothing_was():
    prompt = build_prompt(
        repo="octo/demo", metadata={},
        provenance=build_provenance(
            run_summary=RUN, skipped_by_reason={}, chunks_total=1, chunks_included=1,
            tokens_estimated=10, budget=100,
        ),
        chunks=[chunk("README.md")],
    )
    assert "Nothing. Every selected file was read" in prompt


# --------------------------------------------------------------------------
# the grounding contract, end to end
# --------------------------------------------------------------------------


async def test_a_run_with_no_chunks_never_calls_the_provider(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
    called = False

    async def provider(prompt: str) -> str:
        nonlocal called
        called = True
        return "should not happen"

    result = await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[], cfg=CFG, call_provider=provider,
    )

    assert called is False
    assert result.status is SummaryStatus.NO_CONTENT
    assert result.text is None
    assert "nothing to summarise" in result.error
    assert "would not be grounded" in result.error


async def test_no_content_result_still_carries_provenance(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
    result = await summarise(
        repo="octo/demo", metadata={},
        run_summary={**RUN, "selected_count": 0, "files_read": 0},
        skipped_by_reason={"non_text_asset": 3}, chunks=[], cfg=CFG,
        call_provider=_provider(),
    )
    assert result.provenance["skipped_by_reason"] == {"non_text_asset": 3}


async def test_missing_api_key_is_not_a_run_failure(monkeypatch):
    monkeypatch.delenv("REPOBRIDGE_GEMINI_API_KEY", raising=False)
    result = await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[chunk("README.md")], cfg=CFG,
    )
    assert result.status is SummaryStatus.NOT_CONFIGURED
    assert "REPOBRIDGE_GEMINI_API_KEY" in result.error
    assert result.provenance["chunks_total"] == 1


async def test_successful_summary_carries_text_provenance_and_model(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
    result = await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[chunk("README.md", text="# Demo project")], cfg=CFG,
        call_provider=_provider("This repository demonstrates a thing."),
    )
    assert result.status is SummaryStatus.OK
    assert result.is_grounded_output
    assert result.text == "This repository demonstrates a thing."
    assert result.model == CFG.model
    assert result.provenance["chunks_included"] == 1


async def test_partial_coverage_reaches_both_the_prompt_and_the_provenance(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")
    provider, seen = _recording_provider()

    result = await summarise(
        repo="octo/demo", metadata={},
        run_summary={**RUN, "selected_count": 500, "files_read": 200,
                     "files_not_fetched": 300, "read_cap": 200, "tree_truncated": True},
        skipped_by_reason={"non_text_asset": 12},
        chunks=[chunk(f"f{i}.md", tokens=10) for i in range(5)],
        cfg=SummarizationConfig(max_prompt_tokens=25),
        call_provider=provider,
    )

    # the prompt was told
    assert "300 selected file(s) were not read" in seen["prompt"]
    assert "truncated the file listing" in seen["prompt"]
    assert "12 non_text_asset" in seen["prompt"]
    # and the caller can verify it without trusting the prompt
    assert result.provenance["is_partial"] is True
    assert result.provenance["files_not_fetched"] == 300
    assert result.provenance["tree_truncated"] is True
    assert result.provenance["chunks_included"] == 2
    assert result.provenance["chunks_excluded"] == 3


# --------------------------------------------------------------------------
# provider failure must not lose the run
# --------------------------------------------------------------------------


async def test_provider_error_is_recorded_not_raised(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")

    async def failing(prompt: str) -> str:
        raise SummarizationError("The summarisation provider rate-limited this request.")

    result = await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[chunk("README.md")], cfg=CFG, call_provider=failing,
    )
    assert result.status is SummaryStatus.PROVIDER_ERROR
    assert result.text is None
    assert "rate-limited" in result.error
    # provenance survives the failure, so the run is still explainable
    assert result.provenance["chunks_total"] == 1


async def test_unexpected_provider_exception_is_contained(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", "test-key")

    async def exploding(prompt: str) -> str:
        raise ValueError("something entirely unexpected")

    result = await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[chunk("README.md")], cfg=CFG, call_provider=exploding,
    )
    assert result.status is SummaryStatus.PROVIDER_ERROR
    assert "ValueError" in result.error
    # the original message is not echoed -- it could contain anything
    assert "something entirely unexpected" not in result.error


# --------------------------------------------------------------------------
# key safety
# --------------------------------------------------------------------------

SECRET_KEY = "AIzaSyTESTKEYVALUEMUSTNOTLEAK1234567890"


async def test_the_api_key_never_appears_in_the_prompt(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", SECRET_KEY)
    provider, seen = _recording_provider()

    await summarise(
        repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
        chunks=[chunk("README.md")], cfg=CFG, call_provider=provider,
    )
    assert SECRET_KEY not in seen["prompt"]


async def test_the_api_key_never_appears_in_a_result(monkeypatch):
    monkeypatch.setenv("REPOBRIDGE_GEMINI_API_KEY", SECRET_KEY)

    async def failing(prompt: str) -> str:
        raise SummarizationError("provider said no")

    for provider in (_provider("fine"), failing):
        result = await summarise(
            repo="octo/demo", metadata={}, run_summary=RUN, skipped_by_reason={},
            chunks=[chunk("README.md")], cfg=CFG, call_provider=provider,
        )
        haystack = " ".join(
            str(v) for v in [result.text, result.error, result.model, result.provenance]
        )
        assert SECRET_KEY not in haystack


async def test_provider_error_does_not_echo_the_response_body(monkeypatch):
    """A provider error body can contain the prompt, and the prompt is repository content."""
    import httpx

    from repobridge.core.summarization import _call_gemini

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"upstream error, key={SECRET_KEY}, prompt=SECRET DATA")

    class _Mocked(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("repobridge.core.summarization.httpx.AsyncClient", _Mocked)

    with pytest.raises(SummarizationError) as excinfo:
        # 500 is retryable, so the sleep is stubbed: this test is about the message
        await _call_gemini("a prompt", CFG, SECRET_KEY, sleep=_no_sleep)

    message = str(excinfo.value)
    assert SECRET_KEY not in message
    assert "SECRET DATA" not in message
    assert "500" in message


async def test_rate_limit_is_reported_without_losing_the_run(monkeypatch):
    import httpx

    from repobridge.core.summarization import _call_gemini

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    class _Mocked(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("repobridge.core.summarization.httpx.AsyncClient", _Mocked)

    with pytest.raises(SummarizationError) as excinfo:
        await _call_gemini("a prompt", CFG, "key", sleep=_no_sleep)
    assert "rate-limited" in str(excinfo.value)
    assert "the summary can be generated later" in str(excinfo.value).lower()


async def test_the_api_key_is_sent_as_a_header_not_a_url_parameter(monkeypatch):
    import httpx

    from repobridge.core.summarization import _call_gemini

    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    class _Mocked(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("repobridge.core.summarization.httpx.AsyncClient", _Mocked)

    await _call_gemini("a prompt", CFG, SECRET_KEY)
    assert seen["header"] == SECRET_KEY
    assert SECRET_KEY not in seen["url"]
