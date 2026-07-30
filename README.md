# RepoBridge

RepoBridge is a lightweight local-first tool that turns public GitHub repositories into grounded, structured context for LLM workflows.

Instead of throwing raw HTML or random files at a model and hoping it understands your codebase, RepoBridge uses official GitHub APIs to retrieve the repository tree and readable contents, extracts normalized text from supported files, generates a grounded summary, and exposes everything through a small web UI and a local REST API.

> Status: v0.1 – early development, private and proprietary, not yet ready for public use.

---

## Why RepoBridge?

Most LLM tools struggle to “read” a GitHub repo in a reliable way. They either ignore the URL, only skim the README, or try to ingest huge blobs of HTML and JSON without any structure.

RepoBridge focuses on one job:

- Take a public GitHub repository,
- Retrieve its structure and supported contents in a disciplined way,
- Normalize them into LLM-friendly text,
- Generate grounded summaries,
- And show diagnostics about what was accessed, skipped, or failed.

This makes it easier to build agents, tools, or workflows that actually understand a repo’s layout and content instead of guessing.

---

## Core idea (v0.1)

RepoBridge v0.1 aims to:

- Accept a public GitHub repository URL.
- Validate and normalize the URL into `owner` and `repo` details.
- Use GitHub APIs to fetch the repository tree and contents.
- Select readable files (markdown, code, notebooks, text, JSON) and skip obvious binaries and junk.
- Extract normalized text from supported files, including notebook cells.
- Generate a grounded repository summary from extracted content.
- Surface a diagnostics view that explains selections, skips, and failures.
- Expose results via:
  - a small local web UI, and
  - a local REST API for scripts or LLM tools.

No crawling, no browser automation, no cloud deployment – local-first and focused.

---

## Project structure

High-level layout (subject to change as the project evolves):

```text
RepoBridge/
├── LICENSE.md                # Legal terms (currently All Rights Reserved)
├── README.md                 # Project overview
├── specs/                    # Spec-driven documents for each version
│   └── 001-repobridge-v0.1/
│       ├── spec.md           # v0.1 product specification
│       ├── plan.md           # Milestones and implementation plan
│       ├── tasks.md          # Task breakdown
│       └── evals.md          # Evaluation and acceptance criteria
├── src/
│   ├── repobridge/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app entrypoint
│   │   ├── config.py         # Basic configuration
│   │   ├── core/             # Core logic modules
│   │   ├── infra/            # DB, schemas, logging
│   │   ├── api/              # REST API routes
│   │   └── ui/               # Small web UI (templates + static)
├── tests/                    # Unit and integration tests
└── pyproject.toml            # Python project metadata and dependencies
```

Specs drive development: code changes should follow what’s written in `specs/001-repobridge-v0.1/spec.md`, not the other way around.

---

## Setup (local development)

RepoBridge supports multiple setup styles so you can use whatever you’re comfortable with.

### 1. Classic venv + requirements.txt

This is the simplest if you’re used to `requirements.txt`.

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Linux/macOS
   source .venv/bin/activate
   # Windows (PowerShell)
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies from `requirements.txt`:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   uvicorn src.repobridge.main:app --reload
   ```

---

### 2. venv + direct pip install

If you prefer not to use `requirements.txt`, you can install directly using the dependency list:

1. Create and activate `.venv` (same as above).

2. Install packages:

   ```bash
   pip install fastapi uvicorn[standard] jinja2 httpx pydantic sqlalchemy aiosqlite pytest pytest-asyncio
   ```

3. Run the app:

   ```bash
   uvicorn src.repobridge.main:app --reload
   ```

---

### 3. Future: tooling that reads `pyproject.toml`

RepoBridge also includes a `pyproject.toml` describing project metadata and dependencies. Modern Python tools (like `uv`, `poetry`, or `pip-tools`) can read this file directly and manage environments for you.

Example (conceptual, not required for v0.1):

```bash
# Using uv (if installed)
uv sync
uv run uvicorn src.repobridge.main:app --reload
```

For now, the classic venv + `requirements.txt` flow is enough. The `pyproject.toml` file is there to support more advanced packaging and tooling later. 

---

## v0.1 scope (short version)

- Public GitHub repositories only.
- Local FastAPI server + SQLite.
- Small server-rendered UI.
- No accounts, billing, cloud, or browser automation.
- No private repos in v0.1.
- Focus on:
  - repo tree,
  - file selection,
  - extraction,
  - summary,
  - diagnostics.

Anything beyond this is explicitly out of scope until v0.x+ specs say otherwise.

---

## Running (planned for v0.1)

The exact commands will be added once the implementation is in place. The intended workflow is:

1. Install dependencies via `pip` or `uv` using `pyproject.toml`.
2. Run the FastAPI app locally (e.g., via `uvicorn repobridge.main:app`).
3. Open the local web UI in your browser.
4. Paste a public GitHub repo URL and start an analysis.
5. Inspect the summary, tree, files, and diagnostics.
6. Optionally consume results via the local REST API.

---

## License & usage

RepoBridge is currently proprietary software.

The source code is **not** licensed for reuse, redistribution, or commercial use without explicit written permission from the author. See `LICENSE.md` for details.

---

## Roadmap (high-level)

- v0.1 – Local-only, GitHub repo analysis, small UI + REST API, core diagnostics.
- v0.2+ – Better relevance ranking, exports, optional docs-site support.
- Future – MCP/tool integration, richer code intelligence, more sources, and possible commercial offerings.

This roadmap is exploratory and may change as the project evolves.
