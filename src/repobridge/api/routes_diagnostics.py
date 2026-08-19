"""
`GET /api/runs/{run_id}/diagnostics` -- the ordered account of one run.

The payload is deliberately more than a list of events. A reader's first question is
"did this run do what it should have", and answering that from a raw timeline means
scanning every row; so the response leads with a verdict and a per-stage roll-up, and the
events follow as the evidence for it.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.core.diagnostics import LEVEL_SEVERITY, STAGE_ORDER, Level, Stage
from repobridge.infra import storage
from repobridge.infra.db import get_session

router = APIRouter(prefix="/api", tags=["diagnostics"])


def _event_payload(event) -> dict:
    return {
        "sequence": event.sequence,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "stage": event.stage,
        "level": event.level,
        "message": event.message,
        "path": event.path,
        "details": json.loads(event.details) if event.details else None,
    }


def worst_level(levels) -> str:
    """The most severe level in a group, for a per-stage roll-up."""
    known = [lv for lv in levels if lv in {level.value for level in Level}]
    if not known:
        return Level.INFO.value
    return max(known, key=lambda lv: LEVEL_SEVERITY[Level(lv)])


def stage_rollup(events) -> list[dict]:
    """
    One row per stage that produced events, in pipeline order.

    `evals.md` asks that "the diagnostics view shows each major stage". A stage that never
    ran is absent rather than shown as healthy: for a run that failed at metadata, the
    absence of a tree stage *is* the information.
    """
    grouped: dict[str, list] = {}
    for event in events:
        grouped.setdefault(event.stage, []).append(event)

    rows = []
    for stage, group in grouped.items():
        rows.append(
            {
                "stage": stage,
                "events": len(group),
                "worst_level": worst_level([e.level for e in group]),
                "first_sequence": min(e.sequence for e in group),
            }
        )
    rows.sort(
        key=lambda r: STAGE_ORDER.get(Stage(r["stage"]), 99)
        if r["stage"] in {s.value for s in Stage}
        else 99
    )
    return rows


@router.get("/runs/{run_id}/diagnostics", response_class=JSONResponse)
async def get_run_diagnostics(
    run_id: str,
    stage: str | None = Query(None),
    level: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Every recorded event for a run, in the order the pipeline produced them.

    Filters are provided because "show me only what went wrong" is the common question;
    they narrow `events` but never the `counts_by_level` roll-up, which always describes
    the whole run. A filtered view that also filtered the totals would let a reader
    conclude a run was clean by looking at it through a narrow enough lens.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    # unknown filter values are ignored rather than 500ing, as the tree page does
    stage = stage if stage in {s.value for s in Stage} else None
    level = level if level in {lv.value for lv in Level} else None

    all_events = await storage.list_run_events(session, run_id)
    shown = (
        all_events
        if not (stage or level)
        else await storage.list_run_events(session, run_id, stage=stage, level=level)
    )

    counts = await storage.event_counts_by_level(session, run_id)
    overall = worst_level([e.level for e in all_events])

    return {
        "run_id": run.id,
        "repo": f"{run.owner}/{run.name}",
        "run_status": run.status,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        # The verdict, so a caller does not have to derive it by scanning events.
        "outcome": {
            "worst_level": overall,
            "clean": overall == Level.INFO.value,
            "is_partial": any(e.level == Level.PARTIAL.value for e in all_events),
            "has_failures": any(
                e.level in (Level.DEGRADED.value, Level.ERROR.value) for e in all_events
            ),
        },
        "counts_by_level": {lv.value: counts.get(lv.value, 0) for lv in Level},
        "stages": stage_rollup(all_events),
        "total_events": len(all_events),
        "filters": {"stage": stage, "level": level},
        "events": [_event_payload(e) for e in shown],
    }
