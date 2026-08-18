# RepoBridge v0.1 Spec

## 1. Summary

RepoBridge is a lightweight local-first tool that turns public GitHub repositories into grounded, structured context for LLM workflows. It runs on a single developer’s machine, exposes a small web UI and a local REST API, uses official GitHub APIs to retrieve repository trees and contents, extracts normalized text from supported files, generates a grounded summary, and surfaces diagnostics that explain what was accessed, skipped, or failed.

The goal of v0.1 is to prove that a simple, trustworthy “repo-to-context bridge” is useful and technically sound, without becoming a heavy platform.

---

## 2. Goals

- Let a user analyze a public GitHub repository locally via a simple UI and API.
- Use official GitHub endpoints as the primary retrieval path (trees, contents). 
- Extract readable structure and content from supported files (markdown, code, notebooks, text).
- Generate a grounded summary based only on retrieved content.
- Show clear diagnostics for selected, skipped, and failed files.
- Keep the architecture lightweight, modular, and understandable.
- Prepare a clean base for later MCP/tool integration, without committing to it in v0.1.

---

## 3. Non‑Goals (v0.1)

- Arbitrary website crawling.
- Browser automation.
- Auth and user accounts.
- Billing, subscriptions, or payments.
- Cloud deployment and sync.
- Team collaboration features.
- Private repository support.
- Advanced code intelligence (e.g., static analysis, graph algorithms).
- Vector search or multi‑agent orchestration.
- MCP server implementation (only future consideration).

---

## 4. Target User & Use Cases

Primary user:
- Solo developer, student, or AI power user running a local machine.

Initial use cases:
- Quickly understand an unfamiliar GitHub repo with a grounded summary.
- Inspect which files are considered “readable” and see why others were skipped.
- Use the local API to feed structured repo context into LLM scripts or tools.

---

## 5. Inputs

- **repo_url** (string, required)  
  A public GitHub repository URL, e.g. `https://github.com/owner/repo`.

- **branch_or_ref** (string, optional)  
  Branch, tag, or commit to analyze. If omitted, default to repository default branch.

- **github_token** — *environment only in v0.1; not a request input.*  
  An optional personal access token may be supplied via the `REPOBRIDGE_GITHUB_TOKEN`
  environment variable to improve rate limits. It is deliberately **not** accepted per
  request: v0.1 is local-first and single-user, so a per-request secret would buy nothing
  while flowing into persistence, diagnostics, and logs. Kept local and never logged.

- **llm_provider** (string, optional)  
  Choice of LLM backend for summary generation (e.g., “openrouter”, “groq”). Defaults may be configured locally.

---

## 6. Outputs

For each analysis run:

- **Run metadata**  
  repo_url, owner, repo_name, branch/ref, timestamps, status.

- **Repo tree**  
  Directory and file structure with paths, types, sizes, and selection status.

- **File selection**  
  List of files marked as “selected”, “skipped”, or “failed”, with reasons.

- **Extracted content**  
  Normalized text chunks from selected files, including notebook cells.

- **Summary**  
  Human‑readable overview describing repository purpose, main components, and structure, grounded in extracted content.

- **Diagnostics**  
  Structured log of events and decisions: API calls, rate‑limit hits, parsing errors, selection rationales.

---

## 7. Functional Requirements

1. **Repo URL intake & validation**
   - Validate that `repo_url` is a GitHub repository URL.
   - Normalize it into `owner` and `repo_name`.
   - Reject malformed or unsupported URLs with clear error messages.

2. **Repository metadata & tree retrieval**
   - Use GitHub APIs to fetch repository metadata and the file tree for the specified branch/ref. 
   - Handle “repo not found”, “branch not found”, and rate‑limit errors gracefully.

3. **File selection & classification**
   - Classify every file into exactly one of: selected (supported readable files), skipped
     (unsupported or obviously non‑readable, always with a reason), or failed (errors during
     retrieval or parsing).
   - Directories are counted rather than classified, and no entry may vanish:
     `total_entries == directories + selected + skipped + failed`.
   - Skip binaries and junk (e.g., large images, archives, lockfiles, `node_modules`‑style
     folders). Every skip carries a closed‑enum reason code and a specific human‑readable
     message.
   - **The supported type list, the skip reason enum, the rule precedence order and the
     amendment history live in [`selection.md`](selection.md).** They were moved out of this
     section on 2026-08-17: the rules had grown several times longer than any sibling
     requirement here, and they change on their own cadence as real repositories are measured.
     `selection.md` is authoritative for the details; this section states the requirement.

4. **File content retrieval**
   - For selected files, request contents via GitHub contents APIs.
   - Store raw content plus metadata (path, size, type, hash).
   - Handle partial failures without aborting the entire run.
   - **Reading is capped per run** (`ExtractionConfig.max_files_per_run`, default 200).
     Selected files beyond the cap are recorded as `not_fetched`, never silently dropped.

   #### Amendment — 2026-08-18: retrieval model and the read cap

   **Trigger.** Measuring Milestone 3 against real repositories showed the cost of an
   uncapped per-file read. `github/docs` selects **11,215 files**; at one contents-API call
   each that is more than twice the *entire* authenticated hourly quota (5,000) for a single
   repository. `kubernetes/kubernetes` selects 8,376. Fetching cannot be uncapped.

   **Two models were weighed.**

   *(a) Per-file contents API* — one call per file. Native per-file error isolation, no new
   machinery, and the model this section already specifies.

   *(b) Tarball/zipball* — one call for the whole repository, then read locally. Far cheaper
   in API calls, but it changes the retrieval model, needs archive extraction, temporary disk
   and decompression limits, downloads everything including the files selection already
   decided to skip (22,924 of them for `kubernetes`), and **collapses per-file HTTP errors
   into a single archive-level success or failure**.

   **Decision: (a), with a per-run cap.** Three reasons, in order of weight:

   1. **Per-file status is load-bearing.** This specification requires partial failures not to
      abort a run, and the accounting identity requires every selected file to end in a known
      state. Under (b) there is no per-file HTTP result to record — a file that could not be
      read would be indistinguishable from one that decoded badly, and `failed` would stop
      meaning anything precise.
   2. **The cap solves the actual problem.** (b)'s advantage is call count; a cap bounds call
      count at `limit + 2` per run whatever the repository's size. `github/docs` costs 202
      calls, not 11,215. Once bounded, (b)'s remaining differences are all costs.
   3. **Scope.** Archive handling means temp files, cleanup, and decompression-bomb limits —
      surface that `AGENTS.md`'s "small, local, focused" boundary argues against for v0.1.

   **What the cap does not do.** It does not hide anything. A capped run reports
   `read N of M selected files`, and every unread file carries `content_status =
   not_fetched` with the reason. The identity extends rather than weakens:

   ```
   selected == read + failed + not_fetched
   ```

   **Revisit (b) if** whole-repository extraction becomes a goal, at which point the per-file
   status model needs redesigning first, not retrofitting.

5. **Extraction & normalization**
   - Convert markdown files into plain text with basic structure preserved.
   - Treat code files as text with markers for file boundaries.
   - Parse Jupyter notebooks by reading JSON and extracting:
     - markdown cells as prose,
     - code cells as code blocks.
   - Produce normalized text chunks with identifiers linking back to source files.

6. **Summary generation**
   - Generate a repository summary from the normalized content.
   - Summary must:
     - describe repo purpose and high‑level architecture where possible,
     - mention major directories/modules/files,
     - avoid claims about skipped or unseen content,
     - acknowledge limitations when coverage is sparse.
   - Summaries must be grounded in extracted text and metadata only.

7. **Diagnostics**
   - Log key stages and decisions:
     - URL validation,
     - API calls and responses (status, errors),
     - rate‑limit events,
     - selection and skip reasons,
     - extraction and parsing outcomes,
     - summary generation events.
   - Provide a diagnostics view per run in both API and UI layers.

8. **Local persistence**
   - Store run records, file records, and chunk records in SQLite.
   - Allow listing recent runs and reopening past analyses.
   - Do not store secrets (e.g., tokens) in DB.

9. **REST API**
   - Provide endpoints for:
     - creating a new analysis run,
     - listing runs,
     - viewing run metadata,
     - viewing tree,
     - viewing files and selection status,
     - viewing extracted chunks,
     - viewing diagnostics.

10. **Small web UI**
    - Single‑page or small multi‑page interface:
      - input form for repo URL (and optional branch/token),
      - list of recent runs,
      - run detail view (summary + key metadata),
      - tree and file list view,
      - diagnostics view.

---

## 8. Non‑Functional Requirements

- **Local‑first**  
  The app must be runnable on a normal personal computer using a local FastAPI server and SQLite, without mandatory cloud deployment.

- **Performance (v0.1 guidance, not hard SLA)**  
  - URL validation and initial response: under ~300 ms locally.
  - Tree retrieval for small/medium repos: target under a few seconds, assuming normal network.
  - Summary generation time depends on chosen LLM provider; the system must surface progress or state (e.g., “generating summary”) rather than freezing.

- **Reliability**
  - No single file failure should crash the entire run.
  - Rate‑limit and API errors must be detected and surfaced clearly.
  - Diagnostics must help debug common problems without reading app source code.

- **Security**
  - Only public repos in v0.1.
  - If a GitHub token is used, it must remain local and not be logged.
  - No unapproved network calls beyond GitHub and configured LLM providers.
  - No silent transmission of repo data to third parties beyond configured summarization calls.

- **Maintainability**
  - Code organized into modules (input, GitHub client, selection, extraction, summarization, diagnostics, API, UI).
  - Clear separation between backend logic and UI layer.
  - Tests for core services and endpoints.
  - Configuration via environment or config file, not hardcoded.

---

## 9. Architecture Overview

High‑level modules:

- `core/input` — URL validation and normalization.
- `core/github_client` — repository metadata, tree, and contents retrieval.
- `core/selection` — file classification (selected / skipped / failed).
- `core/extraction` — file content fetching and normalization.
- `core/summarization` — LLM adapters and summary generation.
- `core/diagnostics` — run events and diagnostics aggregation.
- `infra/storage` — SQLite models and persistence layer.
- `api` — FastAPI endpoints for runs, tree, files, chunks, diagnostics.
- `ui` — Jinja/HTMX or minimal JS views for user interaction.

Interactions:

1. UI/API accepts repo URL → input module validates and normalizes.
2. GitHub client fetches metadata and tree.
3. Selection decides which files to process.
4. Extraction fetches contents and normalizes into chunks.
5. Summarization generates grounded summary.
6. Diagnostics record events and outcomes.
7. Storage persists runs and related data.
8. UI/API expose all of this to the user and external tools.

---

## 10. Acceptance Criteria (v0.1, high‑level)

RepoBridge v0.1 is considered complete when:

1. A user running the app locally can:
   - open the UI,
   - submit a public GitHub repo URL,
   - see a completed analysis run with:
     - summary,
     - tree view,
     - file selection view,
     - diagnostics.

2. For a small to medium public repo:
   - the file tree is accurately represented,
   - supported files are selected correctly,
   - obviously non‑readable files are skipped with reasons,
   - extraction outputs text that matches source content reasonably,
   - summary is grounded and acknowledges limitations.

3. For error cases (invalid URL, nonexistent repo, rate‑limit, malformed files):
   - the system surfaces clear error messages,
   - diagnostics show where and why things failed,
   - the app does not crash or corrupt its own storage.

4. The local API:
   - returns consistent JSON for documented endpoints,
   - handles invalid inputs and missing runs gracefully,
   - can be used by an external script or LLM wrapper to consume analysis results.

5. The codebase:
   - is structured into clear modules,
   - has basic tests for critical paths,
   - is documented sufficiently in README and inline comments to be maintainable by a single developer.

---

## 11. Out‑of‑Scope Clarifications (to prevent drift)

- No crawling or reading arbitrary websites.
- No headless browser or automation engine.
- No team user management or role system.
- No paid features or billing implementation.
- No deployment scripts for cloud or containers.
- No guarantee of exhaustive code understanding; this is a context bridge, not a static analyzer.
- No language‑specific deep code intelligence (e.g., type graph, call graph) in v0.1.

---