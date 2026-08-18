from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path

from contextlib import asynccontextmanager
from urllib.parse import urlencode

from repobridge.api.routes_files import router as files_router
from repobridge.api.routes_runs import router as runs_router
from repobridge.core.selection import SkipReason
from repobridge.infra import storage
from repobridge.infra.db import get_database, get_session
from repobridge.infra.schemas import StoredEntryStatus
from sqlalchemy.ext.asyncio import AsyncSession

BASE_DIR = Path(__file__).resolve().parent

# Basic logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("repobridge")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the SQLite schema on startup so a fresh clone just works."""
    await get_database().create_all()
    logger.info("Database schema ready")
    yield


# FastAPI app
app = FastAPI(title="RepoBridge v0.1", version="0.1.0", lifespan=lifespan)

# Templates and static
templates = Jinja2Templates(directory=str(BASE_DIR / "ui" / "templates"))
static_dir = BASE_DIR / "ui" / "static"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health", response_class=JSONResponse)
async def health() -> dict:
    """
    Simple health endpoint to verify the app is running.
    """
    return {"status": "ok", "service": "repobridge", "version": "0.1.0"}


# How many entries one page of the tree view shows. The tree view is paginated
# server-side rather than lazy-loaded: no build step, no framework, and every page is a
# real URL that the back button and a shared link both work on.
TREE_PAGE_SIZE = 100


def tree_url(run_id: str, *, status=None, reason=None, path=None, offset: int = 0) -> str:
    """
    Build a tree-page URL preserving whichever filters are active.

    Passed into the template so filter chips and the pager cannot drop one another's
    state -- switching status while a path filter is set must keep the path.
    """
    params = {}
    if status:
        params["status"] = status
    if reason:
        params["reason"] = reason
    if path:
        params["path"] = path
    if offset:
        params["offset"] = offset
    query = urlencode(params)
    return f"/runs/{run_id}/tree" + (f"?{query}" if query else "")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    """Root UI route: the analyze form plus recent runs."""
    runs, total = await storage.list_runs(session, limit=10)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "RepoBridge v0.1", "runs": runs, "total_runs": total},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(
    run_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """Run detail: metadata, status, counts and skip reasons for one stored run."""
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={
            "title": f"{run.owner}/{run.name} – RepoBridge",
            "run": run,
            "reasons": await storage.counts_by_reason(session, run_id),
        },
    )


@app.get("/runs/{run_id}/tree", response_class=HTMLResponse)
async def run_tree_page(
    run_id: str,
    request: Request,
    status: str | None = Query(None),
    reason: str | None = Query(None),
    path: str | None = Query(None),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """
    Tree view: one page of a run's classified entries.

    Never renders the whole tree -- kubernetes/kubernetes is 37,393 entries -- and the
    template states what fraction of the total is on screen, always.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"message": f"Run '{run_id}' was not found."})

    # unknown filter values are ignored rather than 500ing a page
    status = status if status in {s.value for s in StoredEntryStatus} else None
    reason = reason if reason in {r.value for r in SkipReason} else None
    path = (path or "").strip() or None

    rows, matching = await storage.list_run_files(
        session, run_id, status=status, skip_reason=reason, path_contains=path,
        limit=TREE_PAGE_SIZE, offset=offset,
    )
    return templates.TemplateResponse(
        request=request,
        name="tree.html",
        context={
            "title": f"Tree – {run.owner}/{run.name}",
            "run": run,
            "rows": rows,
            "matching": matching,
            "offset": offset,
            "page_size": TREE_PAGE_SIZE,
            "shown_from": offset + 1 if rows else 0,
            "shown_to": offset + len(rows),
            "status": status,
            "reason": reason,
            "path": path,
            "filtered": bool(status or reason or path),
            "tree_url": tree_url,
            "statuses": [s.value for s in StoredEntryStatus],
            "reasons": await storage.counts_by_reason(session, run_id),
        },
    )


# Include API routers (Milestone 1 and later)
app.include_router(runs_router)
app.include_router(files_router)