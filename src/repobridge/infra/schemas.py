"""
SQLite schema for analysis runs and their classified entries.

Two tables in v0.1: `analysis_runs` and `analysis_files`. Chunk and diagnostics-event
tables are deliberately absent — nothing produces chunks or events yet, and their shape
will be clearer once extraction (Milestone 5) and diagnostics (Milestone 7) exist.
spec.md section 7.8 lists chunk records as a v0.1 requirement; this is a milestone
ordering, not a decision to drop them.

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

    run: Mapped[AnalysisRun] = relationship(back_populates="files")

    __table_args__ = (
        # the diagnostics view's two access patterns
        Index("ix_files_run_status", "run_id", "status"),
        Index("ix_files_run_reason", "run_id", "skip_reason"),
        # "was this specific path skipped, and why"
        Index("ix_files_run_path", "run_id", "path"),
    )
