"""
`GET /api/runs/{run_id}/files` — the classified entries of a stored run.

Paginated unconditionally: one run can be 37,393 rows, and none of them may come back in
a single response. Filterable by status and by skip reason, because that is what a
diagnostics view asks for ("show me the 9 non-text assets"), and by path substring,
because that is what a person asks ("was assets/2764.svg skipped, and why").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.api.errors import invalid_value, run_not_found
from repobridge.core.selection import SkipReason
from repobridge.infra import storage
from repobridge.infra.db import get_session
from repobridge.infra.schemas import StoredEntryStatus

router = APIRouter(prefix="/api", tags=["files"])

FILES_PAGE_DEFAULT = 100
FILES_PAGE_MAX = 500


@router.get("/runs/{run_id}/files", response_class=JSONResponse)
async def list_run_files(
    run_id: str,
    status: str | None = Query(None, description="directory | selected | skipped | failed"),
    reason: str | None = Query(None, description="skip reason code, e.g. non_text_asset"),
    path: str | None = Query(None, description="substring match on the entry path"),
    limit: int = Query(FILES_PAGE_DEFAULT, ge=1, le=FILES_PAGE_MAX),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    valid_statuses = sorted(s.value for s in StoredEntryStatus)
    if status is not None and status not in valid_statuses:
        raise invalid_value("status", status, valid_statuses)
    valid_reasons = sorted(r.value for r in SkipReason)
    if reason is not None and reason not in valid_reasons:
        raise invalid_value("reason", reason, valid_reasons)

    rows, total = await storage.list_run_files(
        session,
        run_id,
        status=status,
        skip_reason=reason,
        path_contains=path,
        limit=limit,
        offset=offset,
    )
    return {
        "run_id": run_id,
        "total": total,
        # rows stored for this run, ignoring every filter. The standard denominator, on
        # every paginated endpoint, so a filtered count is never read as a whole one.
        "unfiltered_total": await storage.count_run_files(session, run_id),
        "limit": limit,
        "offset": offset,
        "filters": {"status": status, "reason": reason, "path": path},
        # What the *tree* said this run contained. Deliberately kept alongside
        # `unfiltered_total` rather than replaced by it: the two can differ -- a degraded
        # run stored no rows but still knows its tree count -- and that difference is what
        # `stored_identity_holds` on the run endpoint exists to report.
        "run_entry_count": run.tree_entry_count,
        "items": [
            {
                "path": r.path,
                "entry_type": r.entry_type,
                "status": r.status,
                "extension": r.extension,
                "size": r.size,
                "reason": r.skip_reason,
                "message": r.message,
                # content retrieval outcome; null for entries never eligible to be read
                "content_status": r.content_status,
                "content_error": r.content_error,
                "content_bytes": r.content_bytes,
            }
            for r in rows
        ],
    }
