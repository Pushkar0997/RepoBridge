# RepoBridge v0.1 Tasks

This file turns the v0.1 plan into concrete tasks. Each task should be completed and reviewed against its acceptance criteria before moving on.

Follow the milestones in order. Do not skip ahead unless the spec and plan are updated.

---

## Milestone 0 – Project skeleton

- Create FastAPI app entrypoint in `src/repobridge/main.py`, define `app = FastAPI()`, add a `/health` route that returns `{"status": "ok"}`.
- Add basic configuration module in `src/repobridge/config.py`, handle settings like app name, debug flag, database URL.
- Implement SQLite connection in `src/repobridge/infra/db.py`, create a simple function to get a connection or session.
- Add logging setup in `src/repobridge/infra/logging.py`, configure structured logging with level, format, and logger helper.
- Wire up routing modules under `src/repobridge/api/`, include router for health and root routes in `main.py`.
- Create base UI route in `src/repobridge/ui/__init__.py`, serve `index.html` template from a simple `GET /` route.
- Create `templates/base.html` and `templates/index.html` with minimal HTML boilerplate, show “RepoBridge v0.1 – Local” text.
- Update `pyproject.toml` with dependencies like FastAPI, Uvicorn, Jinja2, httpx, and any test libraries.
- Run the app locally via Uvicorn, confirm `/health` and `/` work, and commit the initial skeleton.

---

## Milestone 1 – Repo URL intake and validation

- Implement URL parsing and validation in `src/repobridge/core/input.py`, extract `owner` and `repo_name` from GitHub URLs, enforce HTTPS, enforce github.com domain.
- Define a small Pydantic model in `src/repobridge/core/models.py` for incoming analyze requests, fields include `repo_url`, `branch_or_ref`, `github_token`.
- Add error types for invalid URL and unsupported input in `src/repobridge/core/input.py`, return explicit reason strings.
- Create API endpoint `POST /api/analyze` in `src/repobridge/api/routes_runs.py`, accept analyze requests, run validation, return normalized owner/repo or error.
- Add simple UI form in `templates/index.html`, fields include repo URL, optional branch, optional token, submit to `/api/analyze` or a UI-specific route.
- Write tests in `tests/test_input.py` for valid GitHub URLs, invalid URLs, non-GitHub URLs, and edge cases like trailing slashes.
- Write tests in `tests/test_api.py` for analyze endpoint with valid and invalid payloads, verify JSON structure.
- Run tests and manual checks, confirm that no GitHub calls happen before validation passes, and commit changes.

---

## Milestone 2 – GitHub repository retrieval

- Implement GitHub client functions in `src/repobridge/core/github_client.py`, functions to fetch repo metadata and tree using official GitHub APIs.
- Add configuration for GitHub API base URL and version in `config.py`, allow optional token for authenticated requests.
- Handle common error cases in `github_client.py`, including repository not found, branch not found, rate limit responses, network errors.
- Extend `analysis` data model in `models.py` to store repo metadata like owner, name, default branch, and status.
- Update `routes_runs.py` to trigger metadata and tree retrieval after URL validation.
- Write tests in `tests/test_github_client.py` using mocked httpx responses, cover success, not found, and rate limit scenarios.
- Write tests in `tests/test_api.py` for the analyze endpoint's tree behavior, cover truncation, bad refs, and degraded runs.
- Run manual smoke tests against a small set of public repos, verify tree correctness and error handling, then commit.

> Persistence of analysis runs and the UI tree view were moved out of this milestone into
> Milestone 4 by the 2026-08-17 amendment in `plan.md`. They are not dropped; see below.

---

## Milestone 3 – File selection and classification

- Implement file classification logic in `src/repobridge/core/selection.py`, mark files as selected, skipped, or failed based on extension, size, and path patterns.
- Define supported extensions list and skip rules in one place in `selection.py`, include `.md`, `.markdown`, `.py`, `.ipynb`, `.json`, `.txt`, optionally `.js` and `.ts`.
- Extend file models in `models.py` and database schemas in `infra/schemas.py` to store path, extension, size, status, and skip_reason.
- Update the GitHub retrieval flow to populate file records with classification results after tree retrieval.
- Create API endpoints in `routes_files.py` for `GET /api/runs/{run_id}/files`, returning selected, skipped, and failed files with reasons.
- Add a UI view `templates/tree.html` or similar to display files grouped by status, show skip reasons in a simple readable way.
- Write tests in `tests/test_selection.py` for classification on mixed file sets, including markdown, code, notebooks, binaries, and large or vendor files.
- Run manual checks on example repos, confirm that supported files are selected and junk is skipped, and commit.

---

## Milestone 4 – Persistence and tree view

Moved out of Milestone 2 by the 2026-08-17 amendment in `plan.md`. Placed after file
selection so there is a real classification result to persist and display.

- Implement persistence for analysis runs in `infra/schemas.py` and `infra/db.py`, save metadata and status.
- Update `routes_runs.py` to create an analysis run record in the database when an analysis runs.
- Add a simple tree view in UI, showing path list or nested structure for a completed run, reading from the database.
- Persist the truncation flag with the run, so a stored tree is never displayed as complete when it was not.
- Write tests covering run creation, retrieval after restart, and that no token is written to the database.
- Run manual checks: create a run, restart the app, confirm it is still listed and readable, then commit.

---

## Milestone 5 – Extraction and normalization

- Implement content fetching in `github_client.py`, functions to get raw file contents for selected files via GitHub contents APIs.
- Add extraction logic in `src/repobridge/core/extraction.py` for markdown, text, code, JSON, and notebooks, produce normalized chunks with source path and type.
- Extend chunk models in `models.py` and database schemas in `infra/schemas.py` to store chunk id, file reference, chunk index, chunk type, text content, and token estimate.
- Connect extraction step to the analysis pipeline in `routes_runs.py` or a dedicated analysis orchestrator module, run extraction after classification.
- Implement notebook parsing using Python JSON reading in `extraction.py`, separate markdown cells and code cells clearly.
- Add an API endpoint `GET /api/runs/{run_id}/chunks` in `routes_chunks.py`, return chunk previews and metadata.
- Write tests in `tests/test_extraction.py` for markdown files, Python files, JSON files, valid notebooks, and malformed notebooks.
- Add a simple UI section to preview a subset of extracted chunks for a run, help users see where summaries will come from.
- Run manual checks with example repos containing notebooks and mixed file types, confirm that extraction output is sensible, then commit.

---

## Milestone 6 – Grounded summary generation

- Implement a summarization service in `src/repobridge/core/summarization.py`, with a function that takes extracted chunks and metadata and returns a summary string.
- Add configuration in `config.py` for LLM provider selection and API keys, keep keys out of source and logs.
- Design a summary prompt or template inside `summarization.py` that emphasizes grounding, repo purpose, major components, and limitations.
- Integrate summarization into the analysis pipeline, trigger it after extraction finishes and save the result to the analysis run record.
- Create an API endpoint `GET /api/runs/{run_id}/summary` in `routes_runs.py`, return summary and basic metadata.
- Add a summary section to the run detail UI in `templates/run_detail.html`, show summary text and key stats like file counts.
- Write basic tests in `tests/test_end_to_end.py` that simulate a small repo analysis and check that a non-empty summary is produced when chunks exist.
- Run manual checks on known repos, review whether summaries remain grounded and honest about limitations, then commit.

---

## Milestone 7 – Diagnostics and observability

- Implement a diagnostics event model in `models.py`, include run_id, stage, level, message, and metadata.
- Create helper functions in `src/repobridge/core/diagnostics.py` to record events at key stages, such as URL validation, GitHub calls, classification, extraction, summarization errors.
- Extend database schemas and persistence logic to store diagnostics events per run.
- Add an API endpoint `GET /api/runs/{run_id}/diagnostics` in `routes_diagnostics.py`, return ordered event list.
- Build a diagnostics UI page in `templates/diagnostics.html`, show event timeline with stage, level, and short messages.
- Add logging hooks in core modules to keep logs and diagnostics aligned, ensure no major error is missed.
- Write tests in `tests/test_api.py` or a dedicated diagnostics test file to verify diagnostics retrieval for runs with successes and induced failures.
- Manually induce failures by using bad URLs, non-existent repos, and malformed files, confirm diagnostics show what went wrong, then commit.

---

## Milestone 8 – Local API surface completion

- Review and finalize all API routes under `src/repobridge/api/`, ensure endpoints and paths match what is described in `spec.md` and `plan.md`.
- Standardize API response schema, include consistent `data` and `error` fields or similar pattern.
- Add error response helpers for common cases, such as invalid input, not found, and internal error.
- Improve `tests/test_api.py` to cover runs listing, tree retrieval, files listing, chunks retrieval, summary retrieval, and diagnostics retrieval.
- Add simple API documentation in README or a small OpenAPI description via FastAPI’s built-in docs.
- Run manual tests with curl or a small Python script to consume the API, confirm it behaves predictably, then commit.

---

## Milestone 9 – Small UI completion

- Polish the `index.html` page to include input form and recent runs list.
- Improve `run_detail.html` to show summary, key stats, direct links to tree and diagnostics views.
- Refine `tree.html` to show directories and files clearly, highlight selected vs skipped vs failed.
- Improve `diagnostics.html` to show a readable timeline of events and errors.
- Add basic CSS styles in `static/css/main.css`, keep everything lightweight and responsive enough for common screen sizes.
- Wire up any necessary JavaScript in `static/js/main.js` for form submission, navigation, and simple interactions, avoid heavy framework usage.
- Test the full UI flow locally from URL input to run completion and inspection, fix rough edges.
- Commit all UI polishing changes.

---

## Milestone 10 – Release hardening

- Review README and update sections like “Running”, “Usage”, and “Scope” to match the implemented v0.1 behavior.
- Ensure `pyproject.toml` lists all required dependencies and minimal optional extras.
- Add or refine tests in `tests/test_end_to_end.py` to cover a full small-repo analysis from API perspective.
- Create a simple smoke test script or checklist to run against several sample public repos and record outcomes.
- Review logs for noise and missing context, adjust logging configuration to be helpful but not overwhelming.
- Run setup from a clean clone on your machine, follow README instructions, ensure everything works end to end.
- Tag v0.1 in Git, or at least create a clear commit marking “RepoBridge v0.1 baseline”.

---

## Working rules

- Complete tasks in milestone order, unless the spec and plan explicitly change.
- Before implementing a task, reread the relevant section in `spec.md` and `plan.md`.
- Use small commits tied to task descriptions.
- Keep AGENTS.md up to date if major workflow changes are introduced.