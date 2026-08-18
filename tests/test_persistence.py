"""
Persistence tests.

Every test runs against a fresh in-memory database supplied by the autouse
`isolated_database` fixture in conftest.py; none touches a real database file. The
restart test uses `file_database`, which is a real file inside pytest's tmp_path.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from repobridge.core.selection import classify_tree
from repobridge.infra import storage
from repobridge.infra.schemas import AnalysisFile, AnalysisRun, StoredEntryStatus

METADATA = {
    "full_name": "octo/demo",
    "default_branch": "main",
    "description": "A demo repository.",
    "language": "Python",
    "private": False,
    "archived": False,
    "fork": False,
    "stargazers_count": 3,
}


def blob(path: str, size: int = 100) -> dict:
    return {"path": path, "type": "blob", "mode": "100644", "sha": "b" * 40, "size": size}


def tree_dir(path: str) -> dict:
    return {"path": path, "type": "tree", "mode": "040000", "sha": "t" * 40}


MIXED = [
    tree_dir("src"),
    tree_dir("assets"),
    blob("README.md", 400),
    blob("src/app.py", 900),
    blob("assets/logo.png", 4000),
    blob("package-lock.json", 90_000),
    blob("main.go", 500),
    {"type": "blob", "mode": "100644"},  # malformed -> failed
]


async def _store(session, entries, **overrides):
    result = classify_tree(entries) if entries is not None else None
    kwargs = dict(
        repo_url="https://github.com/octo/demo",
        owner="octo",
        name="demo",
        branch_or_ref="main",
        resolved_ref="main" if entries is not None else None,
        metadata=METADATA,
        tree_entry_count=len(entries) if entries is not None else 0,
        tree_truncated=False,
        tree_error=None,
        classification=result,
    )
    kwargs.update(overrides)
    run_id = await storage.create_run(session, **kwargs)
    return run_id, result


# --------------------------------------------------------------------------
# every entry is stored
# --------------------------------------------------------------------------


async def test_successful_run_stores_every_entry(isolated_database):
    async with isolated_database.session() as session:
        run_id, result = await _store(session, MIXED)

        stored = await session.scalar(
            select(func.count()).select_from(AnalysisFile).where(AnalysisFile.run_id == run_id)
        )
        assert stored == len(MIXED) == result.total_entries


async def test_directories_are_stored_not_discarded(isolated_database):
    async with isolated_database.session() as session:
        run_id, _ = await _store(session, MIXED)

        rows, total = await storage.list_run_files(
            session, run_id, status=StoredEntryStatus.DIRECTORY.value, limit=100
        )
        assert total == 2
        assert {r.path for r in rows} == {"src", "assets"}


async def test_identity_is_reconstructible_from_stored_rows_alone(isolated_database):
    async with isolated_database.session() as session:
        run_id, result = await _store(session, MIXED)

        by_status = await storage.reconstruct_counts(session, run_id)
        total = sum(by_status.values())

        assert (
            by_status.get("directory", 0)
            + by_status.get("selected", 0)
            + by_status.get("skipped", 0)
            + by_status.get("failed", 0)
            == total
            == result.total_entries
        )


async def test_stored_counts_match_the_denormalised_run_columns(isolated_database):
    """Guards drift between the run's cached counts and the rows they summarise."""
    async with isolated_database.session() as session:
        run_id, _ = await _store(session, MIXED)
        run = await storage.get_run(session, run_id)
        by_status = await storage.reconstruct_counts(session, run_id)

        assert run.directories == by_status.get("directory", 0)
        assert run.selected_count == by_status.get("selected", 0)
        assert run.skipped_count == by_status.get("skipped", 0)
        assert run.failed_count == by_status.get("failed", 0)


async def test_skip_reasons_survive_storage(isolated_database):
    async with isolated_database.session() as session:
        run_id, result = await _store(session, MIXED)
        assert await storage.counts_by_reason(session, run_id) == result.counts_by_reason()


async def test_a_specific_path_can_be_asked_about(isolated_database):
    """Aggregates cannot answer whether one named path was skipped, and why."""
    async with isolated_database.session() as session:
        run_id, _ = await _store(session, MIXED)

        row = await session.scalar(
            select(AnalysisFile).where(
                AnalysisFile.run_id == run_id, AnalysisFile.path == "assets/logo.png"
            )
        )
        assert row is not None
        assert row.status == "skipped"
        assert row.skip_reason == "non_text_asset"
        assert row.message


# --------------------------------------------------------------------------
# degraded and truncated runs
# --------------------------------------------------------------------------


async def test_degraded_run_is_stored_with_its_error(isolated_database):
    async with isolated_database.session() as session:
        run_id, _ = await _store(
            session,
            None,
            resolved_ref=None,
            tree_error="Tree retrieval failed: GitHub API rate limit exceeded.",
        )
        run = await storage.get_run(session, run_id)

        assert run is not None
        assert run.status == "degraded"
        assert "rate limit" in run.tree_error
        # a degraded run reached the tree stage; `error` is for runs that never did
        assert run.error is None
        # whatever metadata succeeded is kept
        assert run.default_branch == "main"
        assert run.language == "Python"
        assert run.resolved_ref is None


async def test_truncated_tree_is_stored_and_does_not_read_back_as_complete(isolated_database):
    async with isolated_database.session() as session:
        run_id, _ = await _store(
            session,
            MIXED,
            tree_truncated=True,
            tree_error="GitHub truncated the tree response, so the listing is incomplete.",
        )
        run = await storage.get_run(session, run_id)

        assert run.tree_truncated is True
        assert run.tree_error is not None
        assert "incomplete" in run.tree_error


def test_run_survives_a_restart(file_database):
    """Write with one engine, dispose it, reopen the same file, read the run back."""
    open_database = file_database

    async def write() -> str:
        db = open_database()
        async with db.session() as session:
            run_id, _ = await _store(session, MIXED)
        await db.dispose()
        return run_id

    run_id = asyncio.run(write())

    async def read_back():
        db = open_database()
        async with db.session() as session:
            run = await storage.get_run(session, run_id)
            counts = await storage.reconstruct_counts(session, run_id)
        await db.dispose()
        return run, counts

    run, counts = asyncio.run(read_back())
    assert run is not None
    assert run.id == run_id
    assert sum(counts.values()) == len(MIXED)


# --------------------------------------------------------------------------
# no secrets
# --------------------------------------------------------------------------


def test_schema_has_no_token_column():
    for table in (AnalysisRun.__table__, AnalysisFile.__table__):
        for column in table.columns:
            assert "token" not in column.name.lower(), f"{table.name}.{column.name}"


async def test_no_token_value_is_written_anywhere(isolated_database, monkeypatch):
    secret = "ghp_TOKENVALUETHATMUSTNOTBEPERSISTED"
    monkeypatch.setenv("REPOBRIDGE_GITHUB_TOKEN", secret)

    async with isolated_database.session() as session:
        run_id, _ = await _store(session, MIXED)

        run = await storage.get_run(session, run_id)
        haystack = " ".join(str(getattr(run, c.name)) for c in AnalysisRun.__table__.columns)
        rows, _ = await storage.list_run_files(session, run_id, limit=500)
        haystack += " ".join(
            str(getattr(r, c.name)) for r in rows for c in AnalysisFile.__table__.columns
        )
        assert secret not in haystack


# --------------------------------------------------------------------------
# pagination and filtering
# --------------------------------------------------------------------------


async def test_pagination_does_not_return_everything(isolated_database):
    entries = [blob(f"src/file_{i:04d}.py") for i in range(250)]
    async with isolated_database.session() as session:
        run_id, _ = await _store(session, entries)

        page, total = await storage.list_run_files(session, run_id, limit=100, offset=0)
        assert total == 250
        assert len(page) == 100

        page2, _ = await storage.list_run_files(session, run_id, limit=100, offset=100)
        assert len(page2) == 100
        assert {r.path for r in page}.isdisjoint({r.path for r in page2})

        last, _ = await storage.list_run_files(session, run_id, limit=100, offset=200)
        assert len(last) == 50


async def test_filter_by_status(isolated_database):
    async with isolated_database.session() as session:
        run_id, result = await _store(session, MIXED)

        for status, expected in (
            ("directory", result.directories),
            ("selected", len(result.selected)),
            ("skipped", len(result.skipped)),
            ("failed", len(result.failed)),
        ):
            _, total = await storage.list_run_files(session, run_id, status=status, limit=500)
            assert total == expected, status


async def test_filter_by_skip_reason(isolated_database):
    async with isolated_database.session() as session:
        run_id, _ = await _store(session, MIXED)

        rows, total = await storage.list_run_files(
            session, run_id, skip_reason="lockfile", limit=500
        )
        assert total == 1
        assert rows[0].path == "package-lock.json"

        _, none_total = await storage.list_run_files(
            session, run_id, skip_reason="submodule", limit=500
        )
        assert none_total == 0


async def test_list_runs_is_newest_first(isolated_database):
    async with isolated_database.session() as session:
        first, _ = await _store(session, MIXED)
        second, _ = await _store(session, MIXED)

        runs, total = await storage.list_runs(session, limit=10)
        assert total == 2
        assert {r.id for r in runs} == {first, second}
        assert runs[0].created_at >= runs[1].created_at


async def test_unknown_run_returns_none_from_storage(isolated_database):
    async with isolated_database.session() as session:
        assert await storage.get_run(session, "no-such-run") is None


async def test_failed_run_uses_error_not_tree_error(isolated_database):
    """A metadata failure never attempted a tree, so tree_error must stay null."""
    async with isolated_database.session() as session:
        run_id = await storage.create_failed_run(
            session,
            repo_url="https://github.com/octo/demo",
            owner="octo",
            name="demo",
            branch_or_ref=None,
            error="Repository not found on GitHub.",
        )
        run = await storage.get_run(session, run_id)

        assert run.status == "failed"
        assert run.error == "Repository not found on GitHub."
        assert run.tree_error is None
        assert run.tree_entry_count == 0
