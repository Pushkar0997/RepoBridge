"""
File ranking, and the accounting identity surviving it.

`rank_files` decides which files a capped run reads. That makes it the one place where a
reordering bug becomes a *correctness* bug: a file dropped here is a file that silently
never enters the summary's evidence, and the identity
`selected == read + failed + not_fetched` would stop holding.

So the tests split in two:

1. **Ranking quality** -- does a prefix of the ranking look like the repository?
2. **Ranking safety** -- is it a permutation, and does the identity survive it?

The regression case is `smoke.md` Run 8: `psf/requests` capped at 20 read 18 `.github/`
files, no README and no module of `src/requests/`, and the summary called the project
"heavily structured around GitHub infrastructure".
"""

from __future__ import annotations

import pytest

from repobridge.config import ExtractionConfig
from repobridge.core.extraction import ContentStatus, fetch_and_extract
from repobridge.core.ranking import rank_files
from repobridge.core.summarization import ChunkRef, rank_chunks

#: The real selected-file shape of `psf/requests`, abbreviated but faithful in proportion:
#: a small root, a docs tree, the library, tests, and a `.github/` directory that dominates
#: the alphabetically-first slice.
REQUESTS_LIKE = (
    [".coveragerc", ".git-blame-ignore-revs", "AUTHORS.rst", "HISTORY.md", "README.md",
     "requirements-dev.txt", "setup.cfg", "pyproject.toml"]
    + [f".github/{name}" for name in
       ("AI_POLICY.md", "CODEOWNERS", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "FUNDING.yml",
        "ISSUE_TEMPLATE.md", "SECURITY.md", "dependabot.yml")]
    + [f".github/ISSUE_TEMPLATE/{n}.md" for n in ("Bug_report", "Custom", "Feature_request")]
    + [f".github/workflows/{n}.yml" for n in
       ("close-issues", "codeql-analysis", "lint", "lock-issues", "publish", "run-tests",
        "typecheck")]
    + [f"docs/{n}" for n in ("index.rst", "api.rst", "conf.py", "requirements.txt")]
    + [f"docs/community/{n}.rst" for n in ("faq", "support", "updates", "vulnerabilities")]
    + [f"src/requests/{n}.py" for n in
       ("__init__", "__version__", "_internal_utils", "adapters", "api", "auth", "cookies",
        "models", "sessions", "status_codes", "structures", "utils")]
    + [f"tests/{n}.py" for n in ("__init__", "test_requests", "test_utils", "conftest")]
    + ["tests/certs/README.md", "ext/LICENSE"]
)


# --------------------------------------------------------------------------
# ranking quality
# --------------------------------------------------------------------------


def test_the_root_readme_is_read_first():
    assert rank_files(REQUESTS_LIKE)[0] == "README.md"


def test_the_run_8_regression_a_capped_run_reads_the_library_not_just_ci():
    """
    The defect this ranking exists for. At a cap of 20, path order read 18 `.github/`
    files, no README and nothing from `src/requests/`.
    """
    first_20 = rank_files(REQUESTS_LIKE)[:20]

    assert "README.md" in first_20
    library = [p for p in first_20 if p.startswith("src/requests/")]
    assert library, f"a capped run must reach the library itself, got {first_20}"
    github = [p for p in first_20 if p.startswith(".github/")]
    assert len(github) < 10, f"`.github/` must not dominate the cap, got {len(github)} of 20"


def test_path_order_would_have_failed_that_same_check():
    """The before/after, asserted rather than asserted-about: sorted order still fails."""
    first_20 = sorted(REQUESTS_LIKE)[:20]
    assert "README.md" not in first_20
    assert not [p for p in first_20 if p.startswith("src/requests/")]


def test_no_single_area_consumes_the_whole_cap():
    """A thousand files under one directory must not crowd out every other area."""
    paths = ["README.md"] + [f"huge/file_{i:04d}.py" for i in range(1000)] + [
        "docs/index.md", "src/app.py", "tests/test_app.py"
    ]
    first_10 = rank_files(paths)[:10]
    areas = {p.split("/")[0] if "/" in p else "" for p in first_10}
    assert len(areas) >= 4, f"expected several areas in the first 10, got {areas}"


def test_an_exhausted_area_yields_its_share_to_the_others():
    """Round-robin must not stall or pad when one area runs out."""
    paths = ["README.md"] + [f"src/mod_{i:03d}.py" for i in range(50)]
    ranked = rank_files(paths)
    assert ranked[0] == "README.md"
    assert len(ranked) == 51
    assert ranked[1:] == sorted(ranked[1:])  # only src/ left, so pure rank order


def test_explanatory_directories_outrank_peripheral_ones():
    paths = ["tests/helper.py", ".github/workflows/ci.yml", "docs/guide.md", "scripts/run.sh"]
    assert rank_files(paths)[0] == "docs/guide.md"


def test_shallower_paths_rank_above_deeper_ones_in_the_same_area():
    paths = ["src/a/b/c/deep.py", "src/top.py", "src/a/mid.py"]
    assert rank_files(paths) == ["src/top.py", "src/a/mid.py", "src/a/b/c/deep.py"]


def test_prose_ranks_above_code_at_the_same_depth():
    paths = ["src/zzz.md", "src/aaa.py"]
    assert rank_files(paths)[0] == "src/zzz.md"


def test_notebooks_rank_as_prose():
    """A notebook's markdown cells are usually its explanation."""
    paths = ["src/zzz.ipynb", "src/aaa.py"]
    assert rank_files(paths)[0] == "src/zzz.ipynb"


def test_ranking_is_deterministic():
    once = rank_files(REQUESTS_LIKE)
    twice = rank_files(list(reversed(REQUESTS_LIKE)))
    assert once == twice


def test_file_and_chunk_ranking_agree_about_what_explains_a_repository():
    """
    The two stages share `path_rank_key`. If they drifted, a capped run could read one set
    of files while the prompt privileged a different kind entirely.
    """
    paths = ["README.md", "docs/guide.md", ".github/workflows/ci.yml", "src/app.py"]
    by_file = rank_files(paths)
    by_chunk = [
        c.source_path
        for c in rank_chunks(
            [
                ChunkRef(p, 0, "markdown" if p.endswith(".md") else "code", "x", 1)
                for p in paths
            ]
        )
    ]
    assert by_file[0] == by_chunk[0] == "README.md"
    assert by_chunk.index("docs/guide.md") < by_chunk.index(".github/workflows/ci.yml")


# --------------------------------------------------------------------------
# ranking safety: it is a permutation, and nothing else
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["only.md"],
        ["a.py", "b.py"],
        REQUESTS_LIKE,
        ["dup.md", "dup.md", "dup.md"],
        ["", "a/", "a//b.py", "UPPER.MD", "weird name.txt", ".hidden"],
        [f"{i}.py" for i in range(200)],
    ],
)
def test_ranking_is_a_permutation(paths):
    """
    Nothing added, nothing lost, duplicates preserved. The identity depends on this: if
    ranking could drop a path, a selected file would vanish with no status at all.
    """
    ranked = rank_files(paths)
    assert len(ranked) == len(paths)
    assert sorted(ranked) == sorted(paths)


def test_ranking_preserves_duplicate_count():
    paths = ["a.md", "a.md", "b.py"]
    assert sorted(rank_files(paths)) == ["a.md", "a.md", "b.py"]


# --------------------------------------------------------------------------
# the identity, through a real capped extraction
# --------------------------------------------------------------------------


async def _extract(paths, cap, failing=()):
    async def fetch(path: str) -> str:
        if path in failing:
            raise RuntimeError("boom")
        return f"# {path}\n\ncontent\n"

    return await fetch_and_extract(paths, fetch, ExtractionConfig(max_files_per_run=cap))


async def test_the_identity_holds_under_ranking():
    result = await _extract(REQUESTS_LIKE, cap=20)

    assert result.accounts_for_every_selected_file()
    assert len(result.read) == 20
    assert len(result.not_fetched) == len(REQUESTS_LIKE) - 20
    assert result.selected_total == len(REQUESTS_LIKE)


async def test_ranking_changes_which_files_are_unread_never_how_many():
    """The point stated as a test: a different partition of the same set."""
    ranked = await _extract(REQUESTS_LIKE, cap=20)
    unranked_count = len(REQUESTS_LIKE) - 20

    assert len(ranked.not_fetched) == unranked_count
    # every selected path ends in exactly one bucket, and no path is invented
    landed = [f.path for f in ranked.files]
    assert sorted(landed) == sorted(REQUESTS_LIKE)
    assert len(landed) == len(set(landed))


async def test_every_unread_file_still_carries_not_fetched_and_a_reason():
    result = await _extract(REQUESTS_LIKE, cap=5)
    for f in result.not_fetched:
        assert f.status is ContentStatus.NOT_FETCHED
        assert "at most 5 files" in f.error


async def test_a_run_under_the_cap_reads_everything_regardless_of_order():
    """Ranking must never cost a file when there is budget for all of them."""
    result = await _extract(REQUESTS_LIKE, cap=1000)

    assert len(result.read) == len(REQUESTS_LIKE)
    assert result.not_fetched == []
    assert result.cap_applied is False
    assert result.accounts_for_every_selected_file()
    assert sorted(f.path for f in result.read) == sorted(REQUESTS_LIKE)


async def test_failures_still_account_correctly_under_ranking():
    ranked_first_20 = rank_files(REQUESTS_LIKE)[:20]
    failing = set(ranked_first_20[:3])

    result = await _extract(REQUESTS_LIKE, cap=20, failing=failing)

    assert len(result.failed) == 3
    assert len(result.read) == 17
    assert result.accounts_for_every_selected_file()


async def test_an_empty_selection_is_still_consistent():
    result = await _extract([], cap=20)
    assert result.accounts_for_every_selected_file()
    assert result.files == []
