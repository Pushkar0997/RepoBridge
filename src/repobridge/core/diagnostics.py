"""
The single readable account of what a run did.

Everything diagnostics reports already existed before this module: the run row knows the
tree failed, `analysis_files` knows which file could not be decoded, the summary payload
knows how many chunks fitted the budget. What did not exist was **one ordered place that
answers "what did this run do, and where did it fall short"** without a reader knowing
three tables and the order the pipeline runs in. That is what this is for, and it is why
diagnostics *derives* from the pipeline rather than replacing anything: no fact lives here
alone, and nothing here is the only copy of anything.

---

## The level set, and why it is four

`evals.md` names "empty or vague diagnostics" as a failure signal, and a level set is the
fastest way to become vague. Three levels (info/warning/error) collapse two genuinely
different outcomes into "warning": *a stage that finished but was bounded* and *a stage
that did not finish and was survived*. A reader scanning a timeline needs those apart --
the first needs no action, the second is the reason a run looks thinner than expected.

| Level | The stage… | Run outcome | Example |
|---|---|---|---|
| `INFO` | did what it was asked | unaffected | tree retrieved, 153 entries |
| `PARTIAL` | **completed**, with a bounded and quantified shortfall | usable, smaller | read 20 of 107 files; 82 chunks over budget |
| `DEGRADED` | **did not complete**; the run continues without it | reduced | tree retrieval failed; provider error; one file undecodable |
| `ERROR` | **did not complete**; the run ends here | failed | repository not found |

The two tests that keep this honest:

- **PARTIAL always carries numbers.** "Some files were skipped" is the vague diagnostic
  `evals.md` warns about; "read 20 of 107 selected files" is not. If an event cannot say
  how much was lost, it is not PARTIAL -- it is INFO or DEGRADED.
- **DEGRADED always carries a reason.** A stage that did not complete and cannot say why
  is the black box `AGENTS.md` forbids.

There is deliberately **no `WARNING`**, because every candidate for it is really one of
PARTIAL or DEGRADED, and having both a precise and a vague option guarantees the vague one
gets used.

**Level describes the event's own subject, not the whole run.** One undecodable file is
DEGRADED (that file did not work); the content stage that skipped past it is PARTIAL (it
read 106 of 107). Both are true, and a reader needs both.

---

## Volume: what gets a row, and what gets counted

`kubernetes/kubernetes` classifies 37,393 entries and skips 22,924 of them. A row per entry
would be a second copy of `analysis_files` with worse indexes, and would bury the four
events that matter under twenty thousand that do not.

The rule: **failures get rows, successes get counted.**

- **Per run, per stage: always.** One event for what the stage did, plus PARTIAL events
  quantifying any shortfall. That is ~10-15 rows for any repository of any size.
- **Per file: only when that file failed**, capped at `MAX_FILE_EVENTS` with one overflow
  event naming the remainder. A file that was read, skipped by rule, or left unread by the
  cap gets no row of its own -- those are uniform facts, and their aggregate is exact.
- **Never per skipped entry.** The skip reason for a specific path is already stored on
  `analysis_files`, indexed, filterable and linkable from the diagnostics page. Diagnostics
  points at it rather than copying it.

This meets the constraint that a *specific file that failed* must still be findable: a
failure is exactly the case that gets its own row, with its path in its own column.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from repobridge.config import (
    DEFAULT_GITHUB_CONFIG,
    DEFAULT_SUMMARIZATION_CONFIG,
    GitHubConfig,
    SummarizationConfig,
)

logger = logging.getLogger(__name__)

#: Per-file failure events recorded per stage before collapsing into a count. A run whose
#: every file fails is a broken run, not a run needing 200 rows to explain it.
MAX_FILE_EVENTS = 50

#: What a redacted secret is replaced with. Distinctive so a test can assert on it.
REDACTED = "[redacted]"


class Stage(str, Enum):
    """
    The stages the pipeline actually has, in the order it runs them.

    Deliberately not a general-purpose list: every member corresponds to a step in
    `analyze_repo`, so "the diagnostics view shows each major stage" (`evals.md`) is a
    checkable claim rather than an aspiration.
    """

    VALIDATION = "validation"
    METADATA = "metadata"
    TREE = "tree"
    CLASSIFICATION = "classification"
    CONTENT = "content"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"
    PERSISTENCE = "persistence"


#: Pipeline order, for grouping a timeline by stage without relying on insertion order.
STAGE_ORDER = {stage: index for index, stage in enumerate(Stage)}


class Level(str, Enum):
    """See the module docstring for why these four and not info/warning/error."""

    INFO = "info"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    ERROR = "error"


#: Worst-first, for "what is the worst thing that happened in this stage".
LEVEL_SEVERITY = {Level.INFO: 0, Level.PARTIAL: 1, Level.DEGRADED: 2, Level.ERROR: 3}


def _secret_values(
    github_cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG,
    summary_cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG,
) -> list[str]:
    """
    The secret values currently in the environment, read fresh each time.

    Read at call time rather than cached: a test that sets a key after import must still be
    protected, and the cost is two `os.getenv` calls per event.
    """
    names = (github_cfg.token_env_var, summary_cfg.api_key_env_var)
    return [value for value in (os.getenv(name) for name in names) if value]


def redact(value: Any) -> Any:
    """
    Replace any occurrence of a configured secret with `REDACTED`.

    A belt-and-braces guard, not the primary defence. The primary defence is that nothing
    puts a token or key into an event in the first place. This exists because event
    messages are sometimes built from exception text, and an exception can carry a URL or a
    header that the code raising it never intended to expose. Applied to every message and
    every string in every metadata blob.
    """
    secrets = _secret_values()
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            if secret and secret in value:
                value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


@dataclass
class DiagnosticEvent:
    """
    One thing that happened, with everything needed to judge it.

    The fields answer `evals.md`'s questions directly: `stage` and `path` say what was
    involved, `level` says whether it succeeded, `message` and `details` say why not, and
    `created_at` with `sequence` says when and in what order.
    """

    stage: Stage
    level: Level
    message: str
    path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Monotonic within a run. SQLite timestamps are not fine-grained enough to order
    #: events that happen in the same millisecond, and a timeline that reorders itself
    #: between page loads is worse than no timeline.
    sequence: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "stage": self.stage.value,
            "level": self.level.value,
            "message": self.message,
            "path": self.path,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
        }


class Recorder:
    """
    Collects a run's events in memory, to be persisted once at the end.

    **Why buffered rather than written as they happen.** A run has no id until it is
    persisted -- the id is generated in `storage.create_run`, at step 6 of 8 -- so events
    from validation, metadata and tree retrieval are produced before there is anything to
    attach them to. Buffering also means diagnostics cannot fail a run: a recorder that
    raised mid-pipeline would take down the analysis it exists to explain.

    The cost is that a process killed mid-run loses its events. Accepted: the run itself
    would be lost too, since persistence is the same step.
    """

    def __init__(self, max_file_events: int = MAX_FILE_EVENTS):
        self.events: list[DiagnosticEvent] = []
        self.max_file_events = max_file_events
        self._file_events: dict[Stage, int] = {}
        self._suppressed: dict[Stage, int] = {}

    # -- recording ---------------------------------------------------------

    def record(
        self,
        stage: Stage,
        level: Level,
        message: str,
        *,
        path: str | None = None,
        **details: Any,
    ) -> DiagnosticEvent:
        event = DiagnosticEvent(
            stage=stage,
            level=level,
            message=redact(message),
            path=path,
            details=redact({k: v for k, v in details.items() if v is not None}),
            sequence=len(self.events),
        )
        self.events.append(event)
        # keep the application log and the timeline saying the same thing (tasks.md)
        logger.log(
            logging.ERROR if level is Level.ERROR else
            logging.WARNING if level in (Level.DEGRADED, Level.PARTIAL) else logging.INFO,
            "[%s/%s] %s%s",
            stage.value, level.value, event.message, f" ({path})" if path else "",
        )
        return event

    def info(self, stage: Stage, message: str, **details: Any) -> DiagnosticEvent:
        return self.record(stage, Level.INFO, message, **details)

    def partial(self, stage: Stage, message: str, **details: Any) -> DiagnosticEvent:
        """A stage that completed with a quantified shortfall. Always pass the numbers."""
        return self.record(stage, Level.PARTIAL, message, **details)

    def degraded(self, stage: Stage, message: str, **details: Any) -> DiagnosticEvent:
        """A stage that did not complete and was survived. Always pass the reason."""
        return self.record(stage, Level.DEGRADED, message, **details)

    def error(self, stage: Stage, message: str, **details: Any) -> DiagnosticEvent:
        """A stage that did not complete and ended the run."""
        return self.record(stage, Level.ERROR, message, **details)

    def file_failure(
        self, stage: Stage, path: str, message: str, **details: Any
    ) -> DiagnosticEvent | None:
        """
        One file that failed, capped per stage.

        Returns None once the cap is reached; `flush_suppressed` then records a single
        event naming how many were not listed, so the count stays exact even when the
        list does not.
        """
        seen = self._file_events.get(stage, 0)
        if seen >= self.max_file_events:
            self._suppressed[stage] = self._suppressed.get(stage, 0) + 1
            return None
        self._file_events[stage] = seen + 1
        return self.record(stage, Level.DEGRADED, message, path=path, **details)

    def flush_suppressed(self) -> None:
        """Record the "and N more" events. Call once, after the pipeline finishes."""
        for stage, count in sorted(self._suppressed.items(), key=lambda kv: STAGE_ORDER[kv[0]]):
            self.record(
                stage,
                Level.PARTIAL,
                f"{count} further per-file failure(s) are not listed individually; "
                f"this run lists at most {self.max_file_events} per stage. Every affected "
                f"file is still recorded with its status in the file listing.",
                listed=self.max_file_events,
                suppressed=count,
            )
        self._suppressed.clear()

    # -- reading -----------------------------------------------------------

    @property
    def worst_level(self) -> Level:
        return max(
            (e.level for e in self.events), key=lambda lv: LEVEL_SEVERITY[lv], default=Level.INFO
        )

    def counts_by_level(self) -> dict[str, int]:
        counts = {level.value: 0 for level in Level}
        for event in self.events:
            counts[event.level.value] += 1
        return counts


# --------------------------------------------------------------------------
# turning provider errors into structured detail
# --------------------------------------------------------------------------


def rate_limit_details(error: Any) -> dict[str, Any]:
    """
    The structured half of a GitHub rate-limit failure, for the moved Milestone 2 criterion.

    A rate limit in diagnostics is only useful if it says **which quota and when it
    resets**, so the reader knows whether to wait four minutes or authenticate. The source
    is the failing response's own headers, carried on `GitHubClientError.rate_limit` --
    *not* `/rate_limit`, which `smoke.md` Run 1 measured as stale (it reported
    `remaining: 4995` while a real request's own header read `4978`).
    """
    detail = dict(getattr(error, "rate_limit", None) or {})
    detail.setdefault("status_code", getattr(error, "status_code", None))
    return {k: v for k, v in detail.items() if v is not None}


def rows_for(
    run_id: str, events: Iterable[DiagnosticEvent], offset: int = 0
) -> list[dict[str, Any]]:
    """
    Events as insert-ready rows. `run_id` is stamped here because it did not exist yet.

    `offset` is stamped here for the same reason. A `Recorder` numbers from zero because
    it has no idea whether the run it describes already has a timeline -- re-summarising
    builds a fresh recorder against a run that already holds a dozen events. Adding the
    run's current maximum here makes the stored sequence continue rather than restart,
    which is what keeps the timeline append-only. Doing it at write time rather than at
    record time means no caller can forget: the offset is a property of the destination,
    not of the recorder.
    """
    return [
        {
            "run_id": run_id,
            "sequence": event.sequence + offset,
            "stage": event.stage.value,
            "level": event.level.value,
            "message": event.message,
            "path": event.path,
            "details": json.dumps(event.details) if event.details else None,
            "created_at": event.created_at,
        }
        for event in events
    ]
