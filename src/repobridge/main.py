from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Basic logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("repobridge")

app = FastAPI(title="RepoBridge v0.1", version="0.1.0")

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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Root UI route – renders the basic index page.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "RepoBridge v0.1"},
    )