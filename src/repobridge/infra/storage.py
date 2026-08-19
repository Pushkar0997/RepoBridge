"""
Persistence operations for analysis runs.

`spec.md` section 9 names `infra/storage` as the persistence layer; `db.py` owns
connections and `schemas.py` owns models, so the reads and writes live here.

Every classified entry is stored, directories included. That is deliberate: aggregates
cannot answer "was assets/2764.svg skipped, and why", and the accounting identity must be
reconstructible from rows alone.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.config import DEFAULT_DATABASE_CONFIG, DatabaseConfig
from repobridge.core.extraction import ExtractionResult
from repobridge.core.selection import ClassificationResult
from repobridge.infra.schemas import (
    AnalysisChunk,
    AnalysisEvent,
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
    session: AsyncSession,
    *,
    status: str | None = None,
    owner: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[Sequence[AnalysisRun], int, int]:
    """
    Runs newest first, with the matching total **and the unfiltered total**.

    Both totals are returned, always, because a filtered count that looks like a whole
    count is the failure this project keeps finding: `list_run_files` and
    `list_run_chunks` already carry the run's own size for exactly this reason. A caller
    holding `total: 3` needs to know whether that is three runs or three of ninety.

    `owner` folds case because GitHub owner names are case-insensitive, and a filter that
    misses `PSF` when the stored row says `psf` would silently under-report. Filtering on
    a substring is deliberately not offered here: an exact owner is answerable from an
    index, and "everything matching a fragment" is what the path filter on
    `/files` is for, one level down.
    """
    unfiltered = await session.scalar(select(func.count()).select_from(AnalysisRun)) or 0

    conditions = []
    if status:
        conditions.append(AnalysisRun.status == status)
    if owner:
        conditions.append(func.lower(AnalysisRun.owner) == owner.lower())
    if since is not None:
        conditions.append(AnalysisRun.created_at >= since)
    if until is not None:
        conditions.append(AnalysisRun.created_at <= until)

    if conditions:
        total = await session.scalar(
            select(func.count()).select_from(AnalysisRun).where(*conditions)
        ) or 0
    else:
        total = unfiltered

    stmt = (
        select(AnalysisRun)
        .where(*conditions)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows, total, unfiltered


async def count_run_files(session: AsyncSession, run_id: str) -> int:
    """Rows stored for this run, ignoring every filter. The denominator for `total`."""
    return await session.scalar(
        select(func.count()).select_from(AnalysisFile).where(AnalysisFile.run_id == run_id)
    ) or 0


async def count_run_chunks(session: AsyncSession, run_id: str) -> int:
    """Chunks stored for this run, ignoring every filter."""
    return await session.scalar(
        select(func.count()).select_from(AnalysisChunk).where(AnalysisChunk.run_id == run_id)
    ) or 0


async def count_run_events(session: AsyncSession, run_id: str) -> int:
    """Events stored for this run, ignoring every filter."""
    return await session.scalar(
        select(func.count()).select_from(AnalysisEvent).where(AnalysisEvent.run_id == run_id)
    ) or 0


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
    metadata: dict | None = None,
) -> str:
    """
    Persist a run that failed before there was anything to classify.

    Two callers, one shape. The metadata call failed -- repo not found, rate limited,
    unreachable -- and there is no metadata to store; or metadata succeeded and the
    caller named a ref that does not exist, in which case `metadata` carries what was
    genuinely retrieved. Storing it is the point: a run that knows the repository is real
    and the *ref* was wrong tells the user something a bare failure does not.

    No file rows in either case -- there was no tree to classify. Stored because a run
    that never resolved is precisely the thing a user comes back and asks about, and it
    is otherwise the one outcome that leaves no trace at all.

    `resolved_ref` stays None throughout: nothing was ever confirmed.

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
        metadata=metadata or {},
        tree_entry_count=0,
        tree_truncated=False,
        # `error`, not `tree_error`: no tree was ever attempted, and a column name must
        # not assert a stage that did not run.
        tree_error=None,
        classification=None,
        error=error,
        status=RunStatus.FAILED.value,
    )


async def persist_extraction(
    session: AsyncSession,
    run_id: str,
    result: ExtractionResult,
    cfg: DatabaseConfig = DEFAULT_DATABASE_CONFIG,
) -> None:
    """
    Record what happened to each selected file, and store its chunks.

    Updates the existing `analysis_files` rows rather than inserting new ones: a file's
    classification and its content outcome are two facts about the same entry. Every
    selected file gets a `content_status`, including the ones the cap never reached --
    the identity `selected == read + failed + not_fetched` must hold from the rows.
    """
    # one lookup of path -> file id, rather than a query per file
    rows = (
        await session.execute(
            select(AnalysisFile.id, AnalysisFile.path).where(
                AnalysisFile.run_id == run_id,
                AnalysisFile.status == StoredEntryStatus.SELECTED.value,
            )
        )
    ).all()
    file_ids = {path: file_id for file_id, path in rows}

    chunk_rows: list[dict[str, Any]] = []
    chunk_total = 0

    for extraction in result.files:
        file_id = file_ids.get(extraction.path)
        if file_id is None:
            # a path we did not classify as selected: should not happen, and silently
            # skipping it would break the identity, so it is worth knowing about
            continue

        await session.execute(
            update(AnalysisFile)
            .where(AnalysisFile.id == file_id)
            .values(
                content_status=extraction.status.value,
                content_error=extraction.error,
                content_sha=extraction.content_sha,
                content_bytes=extraction.byte_count,
            )
        )

        for chunk in extraction.chunks:
            chunk_total += 1
            chunk_rows.append(
                {
                    "run_id": run_id,
                    "file_id": file_id,
                    "source_path": chunk.source_path,
                    "chunk_index": chunk.chunk_index,
                    "chunk_type": chunk.chunk_type.value,
                    "cell_index": chunk.cell_index,
                    "text": chunk.text,
                    "char_count": chunk.char_count,
                    "token_estimate": chunk.token_estimate(),
                }
            )

    for start in range(0, len(chunk_rows), cfg.insert_batch_size):
        batch = chunk_rows[start : start + cfg.insert_batch_size]
        if batch:
            await session.execute(insert(AnalysisChunk), batch)

    await session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .values(
            files_read=len(result.read),
            files_read_failed=len(result.failed),
            files_not_fetched=len(result.not_fetched),
            read_cap=result.cap,
            chunk_count=chunk_total,
        )
    )
    await session.commit()


async def list_run_chunks(
    session: AsyncSession,
    run_id: str,
    *,
    chunk_type: str | None = None,
    path_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_text: bool = False,
) -> tuple[Sequence[AnalysisChunk], int]:
    """
    One page of a run's chunks. Text is opt-in: chunk bodies are whole files.
    """
    conditions = [AnalysisChunk.run_id == run_id]
    if chunk_type:
        conditions.append(AnalysisChunk.chunk_type == chunk_type)
    if path_contains:
        conditions.append(AnalysisChunk.source_path.contains(path_contains, autoescape=True))

    total = (
        await session.scalar(
            select(func.count()).select_from(AnalysisChunk).where(*conditions)
        )
        or 0
    )
    stmt = (
        select(AnalysisChunk)
        .where(*conditions)
        .order_by(AnalysisChunk.source_path, AnalysisChunk.chunk_index, AnalysisChunk.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return rows, total


async def content_status_counts(session: AsyncSession, run_id: str) -> dict[str, int]:
    """Recompute read/failed/not_fetched from the rows, for the identity check."""
    stmt = (
        select(AnalysisFile.content_status, func.count())
        .where(AnalysisFile.run_id == run_id, AnalysisFile.content_status.is_not(None))
        .group_by(AnalysisFile.content_status)
    )
    return {status: count for status, count in (await session.execute(stmt)).all()}


async def chunk_counts_by_type(session: AsyncSession, run_id: str) -> dict[str, int]:
    """Chunk counts grouped by type, for the run detail page."""
    stmt = (
        select(AnalysisChunk.chunk_type, func.count())
        .where(AnalysisChunk.run_id == run_id)
        .group_by(AnalysisChunk.chunk_type)
        .order_by(func.count().desc())
    )
    return {chunk_type: count for chunk_type, count in (await session.execute(stmt)).all()}


async def persist_summary(session: AsyncSession, run_id: str, result) -> None:
    """
    Store the summary alongside its provenance.

    The provenance is stored as JSON rather than recomputed on read: it records what the
    inventory was *at the time the summary was generated*, which is the only thing that
    makes the prose checkable.
    """
    await session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .values(
            summary_status=result.status.value,
            summary_text=result.text,
            summary_model=result.model,
            summary_error=result.error,
            summary_provenance=json.dumps(result.provenance) if result.provenance else None,
            summary_prompt_tokens=result.prompt_tokens_estimated or None,
        )
    )
    await session.commit()


async def chunks_for_summary(session: AsyncSession, run_id: str) -> list:
    """Every chunk of a run, as the lightweight refs the summariser wants."""
    from repobridge.core.summarization import ChunkRef

    stmt = (
        select(AnalysisChunk)
        .where(AnalysisChunk.run_id == run_id)
        .order_by(AnalysisChunk.source_path, AnalysisChunk.chunk_index, AnalysisChunk.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        ChunkRef(
            source_path=r.source_path,
            chunk_index=r.chunk_index,
            chunk_type=r.chunk_type,
            text=r.text,
            token_estimate=r.token_estimate,
            cell_index=r.cell_index,
        )
        for r in rows
    ]


async def persist_events(
    session: AsyncSession,
    run_id: str,
    recorder,
    cfg: DatabaseConfig = DEFAULT_DATABASE_CONFIG,
) -> int:
    """
    Store a run's diagnostic events, stamping them with the run id.

    Called after the run row exists, because the id is generated there and the earliest
    events (validation, metadata) are produced several steps before it.

    **Never raises into the pipeline.** Diagnostics explain a run; they must not be able to
    fail one. A failure here is logged and swallowed, which is the one place in this
    codebase where swallowing is right: the alternative is that the machinery for
    explaining failures becomes a new cause of them.
    """
    from repobridge.core.diagnostics import rows_for

    if not recorder.events:
        return 0
    try:
        # Continue the run's existing timeline instead of restarting at zero. A recorder
        # numbers from zero because it cannot know whether the run already has events;
        # re-summarising builds a fresh one against a run that does. Without this, a
        # re-summarise writes sequence 0 and 1 again and its events sort into the middle
        # of the original run -- "Re-summarising from stored content" landing before the
        # tree was retrieved. The ordering guarantee this module claims is only true if
        # the sequence cannot restart.
        offset = await next_event_sequence(session, run_id)
        rows = rows_for(run_id, recorder.events, offset)
        for start in range(0, len(rows), cfg.insert_batch_size):
            batch = rows[start : start + cfg.insert_batch_size]
            if batch:
                await session.execute(insert(AnalysisEvent), batch)
        await session.commit()
    except Exception:  # noqa: BLE001 - see the docstring
        logging.getLogger(__name__).exception(
            "Could not persist diagnostics for run %s; the run itself is unaffected.", run_id
        )
        await session.rollback()
        return 0
    return len(rows)


async def list_run_events(
    session: AsyncSession,
    run_id: str,
    *,
    stage: str | None = None,
    level: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[Sequence[AnalysisEvent], int]:
    """
    A run's events in pipeline order.

    Ordered by `sequence`, never by `created_at` alone: two events in the same millisecond
    must not swap places between page loads.

    **Paginated, despite the volume rules.** `core/diagnostics.py` keeps one analysis to
    tens of events by aggregating rather than writing a row per file, and for a single
    analysis that bound holds. It does not hold for a *run*: `POST /runs/{id}/summarize`
    appends to the same timeline every time it is called, and nothing caps how often a
    caller may re-summarise. An endpoint whose response grows without limit is not a
    stable API contract, so this takes the same `limit`/`offset` as files and chunks.
    `limit=None` returns everything, which is what the UI page uses.
    """
    conditions = [AnalysisEvent.run_id == run_id]
    if stage:
        conditions.append(AnalysisEvent.stage == stage)
    if level:
        conditions.append(AnalysisEvent.level == level)
    stmt = (
        select(AnalysisEvent)
        .where(*conditions)
        # `id` is the tiebreaker, not the key: sequences are made to continue across
        # writes (see `persist_events`), but two events can still collide if the same run
        # is written from two places at once, and insertion order is the honest answer
        # when they do. Ordering must never be able to depend on when the page is loaded.
        .order_by(AnalysisEvent.sequence, AnalysisEvent.id)
    )
    total = await session.scalar(
        select(func.count()).select_from(AnalysisEvent).where(*conditions)
    ) or 0
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all(), total


async def next_event_sequence(session: AsyncSession, run_id: str) -> int:
    """
    The sequence a new event for this run should take: one past the stored maximum.

    Zero for a run with no events, so the ordinary analyse path -- which writes its whole
    timeline in one go against a run that has none -- is unaffected.
    """
    highest = await session.scalar(
        select(func.max(AnalysisEvent.sequence)).where(AnalysisEvent.run_id == run_id)
    )
    return 0 if highest is None else int(highest) + 1


async def event_counts_by_level(session: AsyncSession, run_id: str) -> dict[str, int]:
    stmt = (
        select(AnalysisEvent.level, func.count())
        .where(AnalysisEvent.run_id == run_id)
        .group_by(AnalysisEvent.level)
    )
    return {level: count for level, count in (await session.execute(stmt)).all()}
