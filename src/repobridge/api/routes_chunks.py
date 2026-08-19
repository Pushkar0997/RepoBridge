"""
`GET /api/runs/{run_id}/chunks` — the normalised text chunks of a stored run.

Paginated, and chunk text is opt-in (`include_text=true`): a chunk body is a whole file
for everything except notebooks, so a default page of 50 with text would be megabytes.
Filterable by chunk type and by source path, so "show me the notebook cells" and "show me
what came out of README.md" are both one query.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from repobridge.api.errors import invalid_value, run_not_found
from repobridge.core.extraction import ChunkType
from repobridge.infra import storage
from repobridge.infra.db import get_session

router = APIRouter(prefix="/api", tags=["chunks"])

CHUNKS_PAGE_DEFAULT = 50
CHUNKS_PAGE_MAX = 200

#: How much of a chunk's text to show when the caller has not asked for the whole thing.
CHUNK_PREVIEW_CHARS = 300


@router.get("/runs/{run_id}/chunks", response_class=JSONResponse)
async def list_run_chunks(
    run_id: str,
    chunk_type: str | None = Query(None, description="markdown | code | notebook_code | ..."),
    path: str | None = Query(None, description="substring match on the source path"),
    include_text: bool = Query(False, description="return full chunk text, not a preview"),
    limit: int = Query(CHUNKS_PAGE_DEFAULT, ge=1, le=CHUNKS_PAGE_MAX),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    valid_types = sorted(t.value for t in ChunkType)
    if chunk_type is not None and chunk_type not in valid_types:
        raise invalid_value("chunk_type", chunk_type, valid_types)

    rows, total = await storage.list_run_chunks(
        session, run_id, chunk_type=chunk_type, path_contains=path, limit=limit, offset=offset
    )

    return {
        "run_id": run_id,
        "total": total,
        # chunks stored for this run, ignoring every filter -- the standard denominator
        "unfiltered_total": await storage.count_run_chunks(session, run_id),
        "limit": limit,
        "offset": offset,
        "filters": {"chunk_type": chunk_type, "path": path},
        # the run's own totals, from the run row: unchanged, and still the numbers a
        # reader checks a summary against
        "run_chunk_count": run.chunk_count,
        "run_files_read": run.files_read,
        "run_selected_count": run.selected_count,
        "text_included": include_text,
        "items": [
            {
                # traceability: where this text came from, and where in it
                "source_path": row.source_path,
                "chunk_index": row.chunk_index,
                "cell_index": row.cell_index,
                "chunk_type": row.chunk_type,
                "char_count": row.char_count,
                "token_estimate": row.token_estimate,
                **(
                    {"text": row.text}
                    if include_text
                    else {
                        "text_preview": row.text[:CHUNK_PREVIEW_CHARS],
                        "text_truncated": len(row.text) > CHUNK_PREVIEW_CHARS,
                    }
                ),
            }
            for row in rows
        ],
    }
