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
│       ├── selection.md      # File selection rules (moved out of spec.md 7.3)
│       ├── smoke.md          # Smoke suite: sample repos and recorded run results
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

## What actually works today

The full v0.1 pipeline runs end to end: URL in, stored run with classified files,
extracted chunks, a grounded summary and a diagnostics timeline out. Milestones 0–7 are
closed with recorded verdicts in `specs/001-repobridge-v0.1/evals.md`; live results per
repository are in `smoke.md`.

**Working:**

- **Analysis** — validate a GitHub URL, fetch metadata and the git tree, classify every
  entry, read and extract the selected files, summarise from what was read, and record a
  diagnostics timeline. All of it stored in SQLite.
- **REST API** — nine endpoints, documented below, with one error shape.
- **Web UI** — the form on `/` submits and opens the run it creates; `/runs/{id}` shows
  metadata, counts, chunk previews and the summary; `/runs/{id}/tree` browses classified
  entries with filters and pagination; `/runs/{id}/diagnostics` shows the run's timeline.

**Not built:** the items listed under "Out of scope" below. Nothing in the pipeline is
stubbed.

---

## API

Base URL when running locally: `http://127.0.0.1:8000`.

Interactive docs are served by FastAPI at `/docs` (Swagger UI) and `/redoc`.

### The error envelope

**Every** non-2xx response from this application has one shape:

```json
{
  "error": {
    "status": 404,
    "code": "run_not_found",
    "message": "Run 'abc123' was not found.",
    "details": {"run_id": "abc123"}
  }
}
```

Match on `code`, not on `message`: codes are the contract, messages are written for people
and may be reworded. `details` is always an object and may be empty.

| Code | Status | Meaning |
|---|---|---|
| `invalid_request` | 422 | the request could not be parsed into the expected schema. `details.fields` lists each violation |
| `invalid_repo_url` | 400 | parsed, but not a usable public github.com repository URL |
| `invalid_value` | 400 | a query parameter value is not one of a known set. `details.valid` lists the accepted values |
| `run_not_found` | 404 | no stored run with that id |
| `repo_not_found` | 404 | GitHub has no such repository. `details.run_id` opens the stored failed run |
| `ref_not_found` | 404 | the repository exists; the branch, tag or commit you named does not. `details.run_id` opens the stored failed run |
| `rate_limited` | 429 | GitHub rate-limited the request. The message says when it resets |
| `github_error` | 502 | GitHub was unreachable or returned a 5xx |
| `internal_error` | 500 | RepoBridge itself failed. The detail is in the server log, deliberately not in the response |

Status codes name the faulting party: 4xx means your request, 429/502 means GitHub, 500
means RepoBridge. No endpoint returns a 4xx for an upstream or internal problem.

### Pagination

Every list endpoint takes `limit` and `offset` and returns the same four fields:

| Field | Meaning |
|---|---|
| `total` | items matching your filters |
| `unfiltered_total` | items ignoring every filter — **so a filtered count can never be read as a whole one** |
| `limit`, `offset` | echoed back |
| `items` | the page |
| `filters` | echoed back, with `null` for anything you did not set |

Maximum `limit` differs by endpoint because payload sizes do: runs 100, files 500,
chunks 200, diagnostics 1000. Exceeding it is a `422 invalid_request`.

### GET /health

Liveness. Returns `{"status": "ok", "service": "repobridge", "version": "0.1.0"}`.

### POST /api/analyze

Run the full pipeline against a repository.

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -H "Content-Type: application/json" -d "{\"repo_url\": \"https://github.com/psf/requests\"}"
```

Request: `repo_url` (required), `branch_or_ref` (optional, defaults to the repository's
default branch). There is **no** `github_token` request field — see "Environment" below.

| Field | Meaning |
|---|---|
| `run_id` | id of the stored run |
| `repo_url`, `owner`, `name` | the validated, normalised input |
| `branch_or_ref` | what you asked for, or `null` |
| `resolved_ref` | the ref GitHub actually answered for. **`null` when the tree call failed** — never claims a ref was resolved when it was not |
| `metadata` | `full_name`, `private`, `default_branch`, `description`, `archived`, `fork`, `stargazers_count`, `language` |
| `tree_preview` | first 50 entries, each `{path, type, size, mode}` |
| `tree_entry_count` | entries GitHub returned. Not a total — if `tree_truncated`, the repo has more |
| `tree_truncated` | `true` when GitHub truncated the tree |
| `tree_error` | `null` on a clean run; otherwise what went wrong, including the truncation warning |
| `classification` | counts and samples per status, or `null` if the tree never arrived — see below |
| `extraction` | what was read — see below |
| `summary` | the generated summary and its provenance — see below |

Status codes: `200` when metadata was retrieved (the tree may still have failed — check
`tree_error`), `400` invalid URL, `404` repository or ref not found, `429` rate limited,
`502` GitHub unreachable or 5xx.

A tree failure that is *not* a bad ref returns **200** with metadata intact,
`tree_error` populated and `resolved_ref` null, rather than failing the whole request. A
bad ref you explicitly named is a 404 — with a stored run, reachable via
`error.details.run_id`.

GitHub's raw response body is never echoed back.

### GET /api/runs

Stored runs, newest first. Paginated and filterable.

| Filter | Meaning |
|---|---|
| `status` | `completed`, `degraded` or `failed` |
| `owner` | repository owner, case-insensitive exact match |
| `since`, `until` | ISO 8601 date or timestamp, inclusive. A bare date means midnight UTC |

```bash
curl "http://127.0.0.1:8000/api/runs?status=degraded&owner=psf&since=2026-08-18&limit=5"
```

`total` counts matches; `unfiltered_total` counts every stored run.

### GET /api/runs/{run_id}

One stored run: everything in a `/api/runs` item, plus `stored_rows` — the counts
recomputed from the stored entry rows rather than read off the run's own columns, so a
drifted count cannot report itself as consistent. `stored_rows.stored_identity_holds` is
`true` when they agree, and `null` for a degraded run that stored no entries.

**Use `status`, not the error fields, to tell what happened:**

| `status` | Meaning | `error` | `tree_error` |
|---|---|---|---|
| `completed` | metadata and tree both retrieved | `null` | `null`, unless GitHub truncated the tree |
| `degraded` | metadata retrieved, tree call failed | `null` | set |
| `failed` | metadata never resolved, or a named ref did not exist | set | `null` |

A client checking only `tree_error` sees `null` on a **failed** run and would conclude it
succeeded.

### GET /api/runs/{run_id}/files

Every classified entry, paginated. Filters: `status`
(`directory`/`selected`/`skipped`/`failed`), `reason` (a skip reason code), `path`
(substring). Each item carries `path`, `entry_type`, `status`, `extension`, `size`,
`reason`, `message`, and the content outcome `content_status`, `content_error`,
`content_bytes`.

`run_entry_count` is what the *tree* said the run contained. It sits alongside
`unfiltered_total` (rows actually stored) rather than replacing it, because the two can
differ and that difference is what `stored_identity_holds` reports.

Skip reasons are a closed set: `excluded_directory`, `submodule`, `lockfile`,
`non_text_asset`, `unsupported_extension`, `too_large`. Every skipped file carries both
the code and a human-readable message. Rules and thresholds are in
`specs/001-repobridge-v0.1/selection.md`.

### GET /api/runs/{run_id}/chunks

Normalised text chunks, paginated. Filters: `chunk_type`, `path` (substring).
`include_text=true` returns full chunk text; the default returns a 300-character
`text_preview` plus `text_truncated`, because a chunk body is a whole file for everything
except notebooks.

Each item: `source_path`, `chunk_index`, `cell_index` (notebooks only), `chunk_type`,
`char_count`, `token_estimate`. Chunk types: `markdown`, `text`, `code`, `data`,
`notebook_markdown`, `notebook_code`, `notebook_raw`.

### GET /api/runs/{run_id}/summary

The stored summary and the provenance recorded with it, returned together deliberately:
the prose is only trustworthy to the extent you can check it against what was read.

`status` is the *summary's* status (`ok`, `no_content`, `not_configured`,
`provider_error`); `run_status` is the run's. `provenance` carries `files_selected`,
`files_read`, `files_not_fetched`, `read_cap`, `tree_truncated`, `chunks_total`,
`chunks_included`, `chunks_excluded`, `token_budget`, `is_partial` and a `limitations`
list.

### POST /api/runs/{run_id}/summarize

Re-generate the summary for a stored run from its stored chunks. No GitHub call, no file
re-read. Exists because summarisation is the one stage that fails independently of the
work that fed it — a 503 or an exhausted daily quota would otherwise leave a run
permanently without a summary.

Returns the same body as `GET /api/runs/{run_id}/summary`. Returns **200 even when the
provider failed**: the request did what it said — it attempted a re-summarisation and
recorded the outcome — and the outcome is in `status`. Check `status`, not the HTTP code.

### GET /api/runs/{run_id}/diagnostics

The ordered account of what a run did. Paginated. Filters: `stage`, `level`.

| Field | Meaning |
|---|---|
| `outcome` | `worst_level`, `clean`, `is_partial`, `has_failures` |
| `counts_by_level` | events per level, **over the whole run, never the filtered page** |
| `stages` | one row per stage that produced events, in pipeline order, with its worst level |
| `items` | the events: `sequence`, `created_at`, `stage`, `level`, `message`, `path`, `details` |

Stages: `validation`, `metadata`, `tree`, `classification`, `content`, `extraction`,
`summarization`, `persistence`. A stage that never ran is **absent** rather than shown as
healthy.

Levels: `info`; `partial` (the stage completed with a quantified shortfall — always
carries numbers); `degraded` (the stage did not complete, the run continued); `error` (the
stage did not complete, the run ended).

Filters narrow `items` but never `outcome`, `counts_by_level` or `stages`, so a run cannot
be made to look clean by viewing it through a narrow enough lens.

### Web UI pages

`GET /` (form and recent runs), `GET /runs/{run_id}` (detail), `GET /runs/{run_id}/tree`
(classified entries), `GET /runs/{run_id}/diagnostics` (timeline). Server-rendered HTML;
these are not part of the JSON API.

There is deliberately no `GET /api/runs/{run_id}/tree`: the tree is stored as classified
entries, and `/files` is that data with filtering and pagination. A second endpoint
returning the same rows in a different shape would be two contracts for one fact.

---

## Environment

All optional. Nothing is required to start the server.

| Variable | Default | What it does |
|---|---|---|
| `REPOBRIDGE_GITHUB_TOKEN` | unset | Raises the GitHub rate limit from 60 to 5000 requests/hour. Strongly recommended: one analysis costs 2 requests plus one per file read |
| `REPOBRIDGE_GEMINI_API_KEY` | unset | Enables summarisation. Without it, runs complete normally and the summary status is `not_configured` |
| `REPOBRIDGE_GEMINI_MODEL` | `gemini-3.5-flash-lite` | Which model summarises. The free-tier daily quota is **per model**, so switching this is the documented way to keep working after exhausting one |
| `REPOBRIDGE_SUMMARY_TOKEN_BUDGET` | `120000` | Prompt token budget. Chunks beyond it are excluded and the shortfall is disclosed in the summary |
| `REPOBRIDGE_MAX_FILES_PER_RUN` | `200` | The read cap. See "Limitations" |
| `REPOBRIDGE_DATABASE_URL` | `sqlite+aiosqlite:///./repobridge.db` | Where runs are stored |

```bash
export REPOBRIDGE_GITHUB_TOKEN=your_token_here
export REPOBRIDGE_GEMINI_API_KEY=your_key_here
```

There is deliberately no per-request token field: v0.1 is local-first and single-user, so a
per-request secret would buy nothing while flowing into persistence, diagnostics and logs.
See `specs/001-repobridge-v0.1/spec.md` section 5.

---

## Limitations

Stated plainly, because a tool whose pitch is honesty about what it did should be honest
about what it is.

- **Public repositories only.** No authentication flow, no private repos.
- **The read cap.** A run reads at most `REPOBRIDGE_MAX_FILES_PER_RUN` files (default 200).
  Above that, files are ranked — README and orienting docs first, shallower paths, prose
  before code, then spread across top-level areas — and the rest are recorded as
  `not_fetched`. The run always reports how many of how many it read, and the summary
  discloses it. `github/docs` selects 11,217 files; a default run reads 200 of them.
- **The summary provider's free tier is small.** Roughly 500 requests/day on
  `gemini-3.5-flash-lite`, counted **per model per project**. A daily-quota 429 is detected
  and deliberately not retried — the provider advertises a ~58 s retry delay that is wrong,
  since the allowance does not return until the quota day rolls over. Repository content
  sent for summarisation may be used by Google to improve their models on the free tier.
- **No database migrations.** The schema version is checked at startup; a database written
  by a different version is reported with a readable message and must be deleted. Stored
  runs are re-creatable by re-analysing.
- **GitHub truncates very large trees.** When it does, the run says so and never presents
  the listing as complete.
- **Local and single-user.** No accounts, no authentication, no concurrent-writer story.

---

## Out of scope for v0.1

Arbitrary website crawling, browser automation, auth and accounts, billing, cloud or
multi-user deployment, private repositories, multi-agent orchestration, vector databases,
and an MCP server. See `AGENTS.md`.

---

## Tests

```bash
python -m pytest -v
```

The suite never touches the network: every GitHub and provider response is mocked. Live
verification is recorded separately in `specs/001-repobridge-v0.1/smoke.md`.

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
