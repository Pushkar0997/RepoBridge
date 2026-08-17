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

3. Install RepoBridge itself in editable mode, so the `repobridge` package is importable:

   ```bash
   pip install -e .
   ```

4. Run the app:

   ```bash
   uvicorn repobridge.main:app --reload
   ```

---

### 2. venv + direct pip install

If you prefer not to use `requirements.txt`, you can install directly using the dependency list:

1. Create and activate `.venv` (same as above).

2. Install packages:

   ```bash
   pip install fastapi uvicorn[standard] jinja2 httpx pydantic sqlalchemy aiosqlite pytest pytest-asyncio
   ```

3. Install RepoBridge itself in editable mode, so the `repobridge` package is importable:

   ```bash
   pip install -e .
   ```

4. Run the app:

   ```bash
   uvicorn repobridge.main:app --reload
   ```

---

### 3. Future: tooling that reads `pyproject.toml`

RepoBridge also includes a `pyproject.toml` describing project metadata and dependencies. Modern Python tools (like `uv`, `poetry`, or `pip-tools`) can read this file directly and manage environments for you.

Example (conceptual, not required for v0.1):

```bash
# Using uv (if installed)
uv sync
uv run uvicorn repobridge.main:app --reload
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

## What actually works today

RepoBridge is mid-build. This section describes only what runs right now; everything in
"Core idea" above is the target, not the current state. Milestones are tracked in
`specs/001-repobridge-v0.1/plan.md`.

**Working:**

- `GET /health` — returns `{"status": "ok", ...}`.
- `GET /` — renders the UI shell.
- `POST /api/analyze` — validates a GitHub URL, fetches repository metadata and the git
  tree for the resolved ref, and reports what it saw.

**Not built yet:** file selection, content extraction, summaries, diagnostics, SQLite
persistence (nothing is stored — every call is a fresh lookup), and the endpoints for
runs/files/chunks/diagnostics.

**The UI form is inert.** `templates/index.html` renders an input form, but
`static/js/main.js` intercepts submit and shows an alert. It does not call `/api/analyze`.
Use the API directly until the UI is wired up.

### POST /api/analyze

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -H "Content-Type: application/json" -d "{\"repo_url\": \"https://github.com/owner/repo\", \"branch_or_ref\": \"main\"}"
```

Request fields: `repo_url` (required), `branch_or_ref` (optional; defaults to the
repository's default branch). There is **no** `github_token` request field — see below.

Response on success:

| Field | Meaning |
|---|---|
| `repo_url`, `owner`, `name` | the validated and normalized input |
| `branch_or_ref` | what you asked for, or `null` |
| `resolved_ref` | the ref GitHub actually answered for. **`null` when the tree call failed** — the field never claims a ref was resolved when it wasn't. On success it is your `branch_or_ref`, else the default branch |
| `metadata` | `full_name`, `private`, `default_branch`, `description`, `archived`, `fork`, `stargazers_count`, `language` |
| `tree_preview` | first 50 entries, each `{path, type, size, mode}`. `size` is `null` for directories |
| `tree_entry_count` | entries GitHub returned. Not a total — if `tree_truncated` is true, the repo has more |
| `tree_truncated` | `true` when GitHub truncated the tree (very large repos) |
| `tree_error` | `null` on a clean run; otherwise what went wrong, including the truncation warning |
| `classification` | file classification summary, or `null` if the tree never arrived — see below |

Status codes:

| Code | When |
|---|---|
| 200 | metadata retrieved. The tree may still have failed — check `tree_error` |
| 400 | the URL is not a valid github.com repository URL |
| 404 | the repository does not exist, or you named a `branch_or_ref` that does not |
| 429 | GitHub rate-limited us (primary or secondary); the message includes when it resets |
| 502 | GitHub was unreachable, or returned a 5xx |

A tree failure that is *not* a bad ref (rate limit, network, upstream 5xx) returns **200**
with metadata intact, `tree_error` populated, and `resolved_ref` null, rather than failing the
whole request. There is no separate "attempted ref" field: with an explicit request you already
have `branch_or_ref`, and without one you have `metadata.default_branch`, so what *would* have
been used stays derivable without a third field asserting anything unverified.

GitHub's raw response body is never echoed back.

### The `classification` object

Every file entry GitHub returned is classified into exactly one status, and nothing is
dropped. Directories are counted separately rather than classified — "will we read this
file's content?" is not a meaningful question about a directory, and counting them as
skipped would make the skip totals misleading.

| Field | Meaning |
|---|---|
| `total_entries` | every entry in the tree, matching `tree_entry_count` |
| `directories` | entries of type `tree`, counted not classified |
| `selected_count` / `skipped_count` / `failed_count` | totals across the **whole** tree |
| `skipped_count_by_reason` | skip counts grouped by reason code, e.g. `{"non_text_asset": 6, "lockfile": 2}` |
| `accounts_for_every_entry` | `true` when `directories + selected + skipped + failed == total_entries` |
| `sample_limit` | the cap applied to the three `*_sample` arrays (50) |
| `selected_sample` | up to 50 files, each `{path, extension, size}` |
| `skipped_sample` | up to 50 files, each `{path, reason, message}` |
| `failed_sample` | up to 50 entries that could not be classified at all |

**`*_count` fields cover everything; `*_sample` arrays are capped.** The counts are the
source of truth — `kubernetes/kubernetes` returns 37,393 entries and the response does not
carry them inline.

Skip reasons are a closed set, so consumers can group by them:
`excluded_directory`, `submodule`, `lockfile`, `non_text_asset`,
`unsupported_extension`, `too_large`. Every skipped file carries both the code and a
specific human-readable `message` such as `'node_modules/' is excluded by default`.

`classification` is `null` — not an empty summary — when the tree call failed, since zero
counts would read as "we looked and found nothing" rather than "we never looked".

Supported types, the skip rules and the thresholds are defined in
`specs/001-repobridge-v0.1/spec.md` section 7.3.

### GitHub token

Optional, and read **only** from the `REPOBRIDGE_GITHUB_TOKEN` environment variable. It
raises the rate limit from 60 to 5000 requests/hour. Each `/api/analyze` call makes two
GitHub requests.

```bash
export REPOBRIDGE_GITHUB_TOKEN=your_token_here
```

There is deliberately no per-request token field: v0.1 is local-first and single-user, so a
per-request secret would buy nothing while flowing into persistence, diagnostics, and logs.
See `specs/001-repobridge-v0.1/spec.md` section 5.

### Tests

```bash
python -m pytest -v
```

All GitHub responses in the suite are mocked; the tests never touch the network.

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
