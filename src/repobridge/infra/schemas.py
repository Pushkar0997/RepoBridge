"""
SQLite schema for analysis runs and their classified entries.

Three tables in v0.1: `analysis_runs`, `analysis_files` and `analysis_chunks`. The
diagnostics-event table is still absent — nothing produces events until Milestone 7.

SCHEMA_VERSION below is checked at startup (`infra/db.py`). There are no migrations: a
database predating a schema change is reported with a readable message and must be
deleted, rather than failing with OperationalError on the first query.

Storage principle: **every tree entry GitHub returned is stored**, including directories
and skipped files. Aggregates cannot answer "was assets/2764.svg skipped, and why", and
that question is the product's core promise. The accounting identity

    total_entries == directories + selected + skipped + failed

must be reconstructible from `analysis_files` alone, not only from a live API response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


#: Bumped whenever the schema changes. Stored in SQLite's PRAGMA user_version and
#: checked at startup. v1: runs + files. v2: adds chunks and the content columns.
SCHEMA_VERSION = 2


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    """
    Outcome of a run as a whole.

    DEGRADED is not failure: metadata succeeded and the run is worth keeping. A run that
    vanished because its tree call failed would be the worst outcome for a tool whose
    pitch is that it tells you what went wrong.
    """

    COMPLETED = "completed"
    DEGRADED = "degraded"
    #: metadata never resolved, so there is nothing to classify. Stored anyway: a repo
    #: that failed to resolve is exactly what a user will come back to ask about.
    FAILED = "failed"


class ContentStatusValue(str, Enum):
    """
    Whether a *selected* file's content was read. Orthogonal to classification status:
    a file stays `selected` and is separately read, failed, or never reached.

        selected == read + failed + not_fetched
    """

    READ = "read"
    FAILED = "failed"
    NOT_FETCHED = "not_fetched"


class StoredEntryStatus(str, Enum):
    """
    Status as stored. DIRECTORY is a storage representation, not a classification
    status: directories are counted rather than classified in the live model, and giving
    them their own row-level value keeps the identity reconstructible by GROUP BY without
    inflating the skip counts.
    """

    DIRECTORY = "directory"
    SELECTED = "selected"
    SKIPPED = "skipped"
    FAILED = "failed"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    # spec.md section 6: repo_url, owner, repo_name, branch/ref, timestamps, status
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch_or_ref: Mapped[str | None] = mapped_column(String(255))
    resolved_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # repository metadata, as returned by GitHub at the time of the run
    default_branch: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(128))
    private: Mapped[bool | None] = mapped_column(Boolean)
    archived: Mapped[bool | None] = mapped_column(Boolean)
    fork: Mapped[bool | None] = mapped_column(Boolean)
    stargazers_count: Mapped[int | None] = mapped_column(Integer)

    # The failure that ended the run, when one did: metadata never resolved, so no tree
    # was ever attempted. Separate from `tree_error` because a column name must not
    # assert a stage that did not run.
    error: Mapped[str | None] = mapped_column(Text)

    # tree retrieval outcome. `tree_error` is specifically "metadata succeeded, the tree
    # call did not" -- a degraded run. `tree_truncated` is persisted so a stored partial
    # listing can never later render as complete (plan.md Milestone 4).
    tree_entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tree_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tree_error: Mapped[str | None] = mapped_column(Text)

    # denormalised classification counts. Derivable from analysis_files, stored so a
    # listing page does not COUNT over tens of thousands of rows per run. Drift is
    # guarded by a test that reconstructs them from the rows.
    directories: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # extraction outcome. `files_read + files_read_failed + files_not_fetched` must equal
    # `selected_count`; `read_cap` is stored so a capped run can say what it was capped at
    # long after the config default has changed.
    files_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_read_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_not_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    read_cap: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    files: Mapped[list["AnalysisFile"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    # NOTE: there is deliberately no token column. v0.1 reads the token from the
    # environment and never persists it (spec.md section 7.8, plan.md Milestone 4).


class AnalysisFile(Base):
    __tablename__ = "analysis_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )

    path: Mapped[str] = mapped_column(Text, nullable=False)
    # GitHub's tree entry type: blob, tree or commit. Kept so a submodule stays
    # distinguishable from a file at rest, which `status` alone cannot express.
    entry_type: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(Integer)

    # the code/message pair from core/selection.py: the code groups, the message explains
    skip_reason: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)

    # content retrieval, null for entries that were never candidates (directories,
    # skipped files). `content_error` explains a failure or why the cap was hit.
    content_status: Mapped[str | None] = mapped_column(String(16))
    content_error: Mapped[str | None] = mapped_column(Text)
    content_sha: Mapped[str | None] = mapped_column(String(64))
    content_bytes: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[AnalysisRun] = relationship(back_populates="files")
    chunks: Mapped[list["AnalysisChunk"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # the diagnostics view's two access patterns
        Index("ix_files_run_status", "run_id", "status"),
        Index("ix_files_run_reason", "run_id", "skip_reason"),
        # "was this specific path skipped, and why"
        Index("ix_files_run_path", "run_id", "path"),
        Index("ix_files_run_content", "run_id", "content_status"),
    )


class AnalysisChunk(Base):
    """
    One normalised block of text from one file.

    Every chunk carries `source_path` and `chunk_index`, and notebook chunks additionally
    carry `cell_index`. A chunk that cannot be traced back to where it came from is the
    same defect as a file that vanishes, so the traceability columns are NOT NULL.
    """

    __tablename__ = "analysis_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_files.id", ondelete="CASCADE"), nullable=False
    )

    #: denormalised from the file so a chunk is readable without a join
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    #: position within the file, 0-based
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: notebooks only: position of the cell within the notebook
    cell_index: Mapped[int | None] = mapped_column(Integer)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: chars/4 heuristic, not a tokenizer -- see ExtractionConfig.chars_per_token
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped[AnalysisRun] = relationship()
    file: Mapped[AnalysisFile] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_run", "run_id"),
        Index("ix_chunks_file", "file_id", "chunk_index"),
        Index("ix_chunks_run_path", "run_id", "source_path"),
    )
