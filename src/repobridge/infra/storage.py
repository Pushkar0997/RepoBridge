"""
Persistence operations for analysis runs.

`spec.md` section 9 names `infra/storage` as the persistence layer; `db.py` owns
connections and `schemas.py` owns models, so the reads and writes live here.

Every classified entry is stored, directories included. That is deliberate: aggregates
cannot answer "was assets/2764.svg skipped, and why", and the accounting identity must be
reconstructible from rows alone.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Sequence

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.config import DEFAULT_DATABASE_CONFIG, DatabaseConfig
from repobridge.core.selection import ClassificationResult
from repobridge.infra.schemas import (
    AnalysisFile,
    AnalysisRun,
    RunStatus,
    StoredEntryStatus,
)


def new_run_id() -> str:
    return str(uuid.uuid4())


def _entry_rows(run_id: str, result: ClassificationResult) -> list[dict[str, Any]]:
    """Every entry as a row dict: directories, selected, skipped and failed."""
    rows: list[dict[str, Any]] = [
        {
            "run_id": run_id,
            "path": path,
            "entry_type": "tree",
            "status": StoredEntryStatus.DIRECTORY.value,
            "extension": None,
            "size": None,
            "skip_reason": None,
            "message": None,
        }
        for path in result.directory_paths
    ]

    for bucket, status in (
        (result.selected, StoredEntryStatus.SELECTED),
        (result.skipped, StoredEntryStatus.SKIPPED),
        (result.failed, StoredEntryStatus.FAILED),
    ):
        for f in bucket:
            rows.append(
                {
                    "run_id": run_id,
                    "path": f.path,
                    # a submodule is stored as type "commit" so it stays distinguishable
                    "entry_type": "commit" if f.reason and f.reason.value == "submodule" else "blob",
                    "status": status.value,
                    "extension": f.extension or None,
                    "size": f.size,
                    "skip_reason": f.reason.value if f.reason else None,
                    "message": f.message,
                }
            )
    return rows


async def create_run(
    session: AsyncSession,
    *,
    repo_url: str,
    owner: str,
    name: str,
    branch_or_ref: str | None,
    resolved_ref: str | None,
    metadata: dict[str, Any],
    tree_entry_count: int,
    tree_truncated: bool,
    tree_error: str | None,
    classification: ClassificationResult | None,
    error: str | None = None,
    status: str | None = None,
    cfg: DatabaseConfig = DEFAULT_DATABASE_CONFIG,
) -> str:
    """
    Persist a run and, when a tree arrived, every one of its classified entries.

    A degraded run (tree failed, classification None) is stored too, with its error and
    whatever metadata succeeded. A run that vanished because it failed would be the worst
    possible outcome for a tool whose pitch is that it tells you what went wrong.

    Two distinct error fields, deliberately: `error` is the failure that ended the run
    (metadata never resolved), `tree_error` is the narrower "metadata succeeded, the tree
    call did not". A degraded run sets tree_error; a failed run sets error. Never both.

    `status` overrides the derived value, for runs that failed before classification could
    even be attempted (see `create_failed_run`).
    """
    run_id = new_run_id()

    run = AnalysisRun(
        id=run_id,
        repo_url=repo_url,
        owner=owner,
        name=name,
        branch_or_ref=branch_or_ref,
        resolved_ref=resolved_ref,
        status=status
        or (RunStatus.COMPLETED if classification is not None else RunStatus.DEGRADED).value,
        default_branch=metadata.get("default_branch"),
        description=metadata.get("description"),
        language=metadata.get("language"),
        private=metadata.get("private"),
        archived=metadata.get("archived"),
        fork=metadata.get("fork"),
        stargazers_count=metadata.get("stargazers_count"),
        error=error,
        tree_entry_count=tree_entry_count,
        tree_truncated=tree_truncated,
        tree_error=tree_error,
        directories=classification.directories if classification else 0,
        selected_count=len(classification.selected) if classification else 0,
        skipped_count=len(classification.skipped) if classification else 0,
        failed_count=len(classification.failed) if classification else 0,
    )
    session.add(run)
    await session.flush()

    if classification is not None:
        rows = _entry_rows(run_id, classification)
        # Batched executemany: 37k single-row INSERTs is needlessly slow, and one
        # statement carrying 37k rows is needlessly large.
        for start in range(0, len(rows), cfg.insert_batch_size):
            batch = rows[start : start + cfg.insert_batch_size]
            if batch:
                await session.execute(insert(AnalysisFile), batch)

    await session.commit()
    return run_id


async def get_run(session: AsyncSession, run_id: str) -> AnalysisRun | None:
    return await session.get(AnalysisRun, run_id)


async def list_runs(
    session: AsyncSession, *, limit: int = 20, offset: int = 0
) -> tuple[Sequence[AnalysisRun], int]:
    """Runs newest first, plus the total count for pagination."""
    total = await session.scalar(select(func.count()).select_from(AnalysisRun)) or 0
    stmt = (
        select(AnalysisRun)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows, total


async def list_run_files(
    session: AsyncSession,
    run_id: str,
    *,
    status: str | None = None,
    skip_reason: str | None = None,
    path_contains: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[Sequence[AnalysisFile], int]:
    """
    One page of a run's entries, plus the total matching the filters.

    Paginated because a single run can be 37,393 rows. Filtering by status and skip reason
    is what a diagnostics view asks for; `path_contains` is what a *person* asks -- "was
    assets/2764.svg skipped, and why" is unanswerable by paging through 374 pages.

    `path_contains` is a substring match, case-insensitive on SQLite, with LIKE
    metacharacters escaped so a path containing % or _ matches literally.
    """
    conditions = [AnalysisFile.run_id == run_id]
    if status is not None:
        conditions.append(AnalysisFile.status == status)
    if skip_reason is not None:
        conditions.append(AnalysisFile.skip_reason == skip_reason)
    if path_contains:
        conditions.append(AnalysisFile.path.contains(path_contains, autoescape=True))

    total = (
        await session.scalar(
            select(func.count()).select_from(AnalysisFile).where(*conditions)
        )
        or 0
    )
    stmt = (
        select(AnalysisFile)
        .where(*conditions)
        .order_by(AnalysisFile.path, AnalysisFile.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows, total


async def reconstruct_counts(session: AsyncSession, run_id: str) -> dict[str, int]:
    """
    Recompute the per-status counts from stored rows.

    The identity must hold from the database alone, not only from a live response. Used
    by the API's `stored_identity_holds` and by the tests that guard count drift.
    """
    stmt = (
        select(AnalysisFile.status, func.count())
        .where(AnalysisFile.run_id == run_id)
        .group_by(AnalysisFile.status)
    )
    rows = (await session.execute(stmt)).all()
    return {status: count for status, count in rows}


async def counts_by_reason(session: AsyncSession, run_id: str) -> dict[str, int]:
    stmt = (
        select(AnalysisFile.skip_reason, func.count())
        .where(AnalysisFile.run_id == run_id, AnalysisFile.skip_reason.is_not(None))
        .group_by(AnalysisFile.skip_reason)
        .order_by(AnalysisFile.skip_reason)
    )
    rows = (await session.execute(stmt)).all()
    return {reason: count for reason, count in rows}


async def create_failed_run(
    session: AsyncSession,
    *,
    repo_url: str,
    owner: str,
    name: str,
    branch_or_ref: str | None,
    error: str,
) -> str:
    """
    Persist a run whose metadata call failed: repo not found, rate limited, unreachable.

    No file rows -- there was no tree to classify. Stored because a repository that never
    resolved is precisely the thing a user will come back and ask about, and it is the one
    outcome that would otherwise leave no trace at all.

    URL validation failures are deliberately not persisted: those never reached GitHub, and
    there is no repository to record.
    """
    return await create_run(
        session,
        repo_url=repo_url,
        owner=owner,
        name=name,
        branch_or_ref=branch_or_ref,
        resolved_ref=None,
        metadata={},
        tree_entry_count=0,
        tree_truncated=False,
        # `error`, not `tree_error`: no tree was ever attempted, and a column name must
        # not assert a stage that did not run.
        tree_error=None,
        classification=None,
        error=error,
        status=RunStatus.FAILED.value,
    )
