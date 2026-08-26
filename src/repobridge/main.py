from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import logging
from importlib.metadata import version
from pathlib import Path

import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from repobridge.api.errors import install_error_handlers, run_not_found
from repobridge.api.routes_chunks import router as chunks_router
from repobridge.api.routes_diagnostics import router as diagnostics_router
from repobridge.api.routes_diagnostics import stage_rollup, worst_level
from repobridge.api.routes_files import router as files_router
from repobridge.api.routes_runs import router as runs_router
from repobridge.core.diagnostics import Level, Stage
from repobridge.core.selection import SkipReason
from repobridge.infra import storage
from repobridge.config import (
    DEFAULT_GITHUB_CONFIG,
    DEFAULT_SUMMARIZATION_CONFIG,
    get_bind_address,
    get_deployment_config,
    get_extraction_config,
    get_gemini_api_key,
    get_github_token,
    get_summarization_config,
)
from repobridge.infra.db import SchemaVersionError, get_database, get_session, sqlite_path
from repobridge.infra.schemas import RunStatus, StoredEntryStatus
from sqlalchemy.ext.asyncio import AsyncSession

BASE_DIR = Path(__file__).resolve().parent

#: One version string. `/health`, the OpenAPI metadata and the startup log line all read
#: it, so they cannot disagree -- they were three separate literals before.
APP_VERSION = version("repobridge")

# Basic logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("repobridge")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Create the SQLite schema on startup so a fresh clone just works, and say once what
    this process is configured with.

    **The startup block is what the logs are for.** Diagnostics already explain every
    run, per run, in the UI -- so the log's job is the part diagnostics structurally
    cannot cover: facts about the *process*, which exist before any run does and belong
    to none of them. Which database, which caps, whether each key is present. It is the
    difference between "it isn't summarising" and a support answer.

    Booleans only for the keys, exactly as the UI does. A log file is the last place a
    secret should end up.
    """
    database = get_database()
    try:
        await database.create_all()
    except SchemaVersionError as exc:
        # Without this the message is the last line of a forty-line traceback, which is
        # the first thing a new user sees when their database is one release behind.
        logger.error(
            "RepoBridge cannot start.\n\n%s\n", exc, exc_info=False
        )
        raise

    extraction = get_extraction_config()
    deployment = get_deployment_config()
    logger.info(
        "RepoBridge %s ready | mode=%s | storage=%s | database=%s | github_token=%s | "
        "gemini_key=%s | model=%s | read_cap=%s files | concurrency=%s",
        APP_VERSION,
        deployment.mode,
        deployment.storage,
        sqlite_path(database.url) or database.url,
        "set" if get_github_token() else "NOT SET (60 requests/hour, unauthenticated)",
        "set" if get_gemini_api_key() else "NOT SET (runs complete; no summaries)",
        get_summarization_config().model,
        extraction.max_files_per_run,
        extraction.max_concurrent_reads,
    )
    if deployment.is_shared:
        # The limits an operator most needs confirmed at boot: getting them wrong is
        # otherwise only visible as an unexpectedly large bill.
        logger.info(
            "Shared deployment | analyses/hour: instance=%s client=%s | max repo "
            "entries=%s | limits are per-process, so run a single worker",
            deployment.max_analyses_per_hour or "unlimited",
            deployment.max_analyses_per_hour_per_client or "unlimited",
            deployment.max_repo_entries or "unlimited",
        )
    if deployment.is_ephemeral:
        logger.warning(
            "Storage is declared ephemeral: stored runs will not survive a restart."
        )
    yield


# FastAPI app
app = FastAPI(title="RepoBridge v0.1", version=APP_VERSION, lifespan=lifespan)

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
    return {"status": "ok", "service": "repobridge", "version": APP_VERSION}


# How many entries one page of the tree view shows. The tree view is paginated
# server-side rather than lazy-loaded: no build step, no framework, and every page is a
# real URL that the back button and a shared link both work on.
TREE_PAGE_SIZE = 100

# How many chunks the run detail page previews. Small on purpose: it is a sample to show
# what extraction produced, and the page states how many of the total it is showing.
CHUNK_PREVIEW_COUNT = 20


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


def _deployment_context() -> dict:
    """
    What kind of instance this is, for the templates.

    Kept beside `_key_status` because the two are read together: *whose* keys these are
    changes what there is to say about them. On a local install the keys are the reader's
    and the useful thing is how to set them; on a shared instance they are the operator's
    and that advice is simply wrong -- a tester cannot set an environment variable on
    someone else's server.
    """
    deployment = get_deployment_config()
    return {
        "shared": deployment.is_shared,
        "ephemeral": deployment.is_ephemeral,
        "max_analyses_per_hour": deployment.max_analyses_per_hour,
        "max_analyses_per_hour_per_client": deployment.max_analyses_per_hour_per_client,
        "max_repo_entries": deployment.max_repo_entries,
        "read_cap": get_extraction_config().max_files_per_run,
    }


def _key_status() -> dict:
    """
    Whether each key is configured. **Booleans and variable names only.**

    Never the value, and never a masked form of it either: a mask still discloses length
    and usually the first characters, which is a leak with a reassuring shape. The only
    facts this returns about a key are that it is set or that it is not.

    Read at call time, like every other config accessor here, so setting a key and
    reloading the page reflects it without restarting the process.
    """
    return {
        "github": bool(get_github_token()),
        "gemini": bool(get_gemini_api_key()),
        "github_env": DEFAULT_GITHUB_CONFIG.token_env_var,
        "gemini_env": DEFAULT_SUMMARIZATION_CONFIG.api_key_env_var,
        "model_env": DEFAULT_SUMMARIZATION_CONFIG.model_env_var,
        "model": get_summarization_config().model,
    }


#: How many runs the home page lists. Small on purpose: it is a recent-runs list, not a
#: browser, and the scope line always says how many of how many are shown.
RUNS_PAGE_SIZE = 20


def _ui_date(value: str | None):
    """
    Parse a filter date for a *page*, returning None rather than raising.

    The API answers a malformed date with a 400 (`routes_runs._parse_when`). A page must
    not: the tree page has ignored unknown filter values since Milestone 4 rather than
    500ing a screen, and a person who typed a bad date wants the list plus a note, not an
    error document. Same input, two right answers, because the consumers differ -- a
    script needs to be told it was wrong, a person needs to keep browsing.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    status: str | None = Query(None),
    owner: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Root UI route: the analyze form plus recent runs, filterable.

    The filters are the ones `GET /api/runs` gained in Milestone 8, which nothing in the
    UI used. `total` and `unfiltered_total` both reach the template, and the template
    always renders both, so a filtered list can never read as the whole -- the rule the
    file listing has followed since Milestone 4.
    """
    status = status if status in {s.value for s in RunStatus} else None
    owner = (owner or "").strip() or None

    # a date we could not read is reported and ignored, never fatal to the page
    bad_dates = [
        label for label, raw in (("from", since), ("to", until))
        if raw and _ui_date(raw) is None
    ]

    runs, total, unfiltered = await storage.list_runs(
        session,
        status=status,
        owner=owner,
        since=_ui_date(since),
        until=_ui_date(until),
        limit=RUNS_PAGE_SIZE,
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "RepoBridge v0.1",
            "runs": runs,
            "total": total,
            "unfiltered_total": unfiltered,
            "status": status,
            "owner": owner,
            "since": since if not (since and _ui_date(since) is None) else "",
            "until": until if not (until and _ui_date(until) is None) else "",
            "filtered": bool(status or owner or _ui_date(since) or _ui_date(until)),
            "bad_dates": bad_dates,
            "statuses": [s.value for s in RunStatus],
            "keys": _key_status(),
            "deployment": _deployment_context(),
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(
    run_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """Run detail: metadata, status, counts and skip reasons for one stored run."""
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    chunk_sample, chunk_total = await storage.list_run_chunks(
        session, run_id, limit=CHUNK_PREVIEW_COUNT
    )
    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={
            "title": f"{run.owner}/{run.name} – RepoBridge",
            "run": run,
            "reasons": await storage.counts_by_reason(session, run_id),
            "chunk_types": await storage.chunk_counts_by_type(session, run_id),
            "chunk_sample": chunk_sample,
            "chunk_total": chunk_total,
            "chunk_preview_count": CHUNK_PREVIEW_COUNT,
            "summary_provenance": (
                json.loads(run.summary_provenance) if run.summary_provenance else None
            ),
            "keys": _key_status(),
            "deployment": _deployment_context(),
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
        raise run_not_found(run_id)

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


def diagnostics_url(run_id: str, *, stage=None, level=None) -> str:
    """Build a diagnostics URL keeping whichever filters are active, as `tree_url` does."""
    params = {}
    if stage:
        params["stage"] = stage
    if level:
        params["level"] = level
    query = urlencode(params)
    return f"/runs/{run_id}/diagnostics" + (f"?{query}" if query else "")


@app.get("/runs/{run_id}/diagnostics", response_class=HTMLResponse)
async def run_diagnostics_page(
    run_id: str,
    request: Request,
    stage: str | None = Query(None),
    level: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Diagnostics view: the ordered account of what one run did.

    The counts and the stage strip are always computed over *all* the run's events, never
    over the filtered subset. Filtering the totals as well would let a reader narrow the
    view until a run with failures looked clean.
    """
    run = await storage.get_run(session, run_id)
    if run is None:
        raise run_not_found(run_id)

    stage = stage if stage in {s.value for s in Stage} else None
    level = level if level in {lv.value for lv in Level} else None

    # The page shows the whole timeline (no limit): it is one run's account, and the
    # counts and stage strip below are computed over all of it regardless of filters.
    all_events, _ = await storage.list_run_events(session, run_id)
    events, _ = await storage.list_run_events(session, run_id, stage=stage, level=level)

    # decode the JSON details once, here, rather than filtering in the template
    for event in events:
        event.parsed_details = json.loads(event.details) if event.details else None

    counts = await storage.event_counts_by_level(session, run_id)
    overall = worst_level([e.level for e in all_events])

    return templates.TemplateResponse(
        request=request,
        name="diagnostics.html",
        context={
            "title": f"Diagnostics - {run.owner}/{run.name}",
            "run": run,
            "events": events,
            # named `total` to match the API's pagination envelope; the sentence the
            # template renders with it is unchanged
            "total": len(all_events),
            "stages": stage_rollup(all_events),
            "levels": [lv.value for lv in Level],
            "counts_by_level": {lv.value: counts.get(lv.value, 0) for lv in Level},
            "outcome": {
                "worst_level": overall,
                "is_partial": any(e.level == Level.PARTIAL.value for e in all_events),
                "has_failures": any(
                    e.level in (Level.DEGRADED.value, Level.ERROR.value) for e in all_events
                ),
            },
            "stage_filter": stage,
            "level_filter": level,
            "diagnostics_url": diagnostics_url,
        },
    )


# Include API routers (Milestone 1 and later)
app.include_router(runs_router)
app.include_router(files_router)
app.include_router(chunks_router)
app.include_router(diagnostics_router)

# One error envelope for every failure, including the UI pages. See api/errors.py.
install_error_handlers(app)