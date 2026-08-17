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
   - Classify files into:
     - selected (supported readable files),
     - skipped (unsupported or obviously non‑readable),
     - failed (errors during retrieval/parsing).
   - Supported types for v0.1:
     - `.md`, `.markdown`
     - `.py`
     - `.ipynb`
     - `.json`
     - `.txt`
     - optionally `.js`, `.ts` if simple text extraction is used.
   - Skip binaries and junk (e.g., large images, archives, lockfiles, `node_modules`‑style folders).

4. **File content retrieval**
   - For selected files, request contents via GitHub contents APIs.
   - Store raw content plus metadata (path, size, type, hash).
   - Handle partial failures without aborting the entire run.

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