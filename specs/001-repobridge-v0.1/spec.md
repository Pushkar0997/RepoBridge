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
   - Supported types for v0.1 *(widened 2026-08-17 — see amendment below)*:
     - **Prose and docs:** `.md`, `.markdown`, `.rst`, `.txt`
     - **Code:** `.py`, `.js`, `.ts`, `.sh`
     - **Notebooks:** `.ipynb`
     - **Structured config:** `.json`, `.yml`, `.yaml`, `.toml`, `.cfg`, `.ini`, `.in`
     - **Template variants:** `.example`, `.template`, `.sample` — a config file committed
       in placeholder form (`.env.example`, `config.yml.template`) is text by construction
       and is often the only committed form of that config.
     - **Recognised extensionless files, matched by exact filename:**
       `Dockerfile`, `Makefile`, `Rakefile`, `Vagrantfile`, `Procfile`, `Gemfile`,
       `Pipfile`, `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, `AUTHORS`, `CONTRIBUTORS`,
       `README`, `CHANGELOG`, `CODEOWNERS`, `.gitignore`, `.gitattributes`,
       `.dockerignore`, `.editorconfig`, `.coveragerc`, `.flake8`, `.pylintrc`,
       `.npmrc`, `.nvmrc`, `.python-version`, `.ruby-version`, `.tool-versions`,
       `.prettierrc`, `.eslintrc`, `.babelrc`, `.browserslistrc`, `.gitmodules`,
       `.git-blame-ignore-revs`
   - Skip binaries and junk (e.g., large images, archives, lockfiles, `node_modules`‑style folders).
   - **`.svg` is skipped as a non‑text asset.** This is a judgement, not an omission: SVG is
     XML text, so it could be read, but committed SVGs are overwhelmingly machine‑generated
     export artifacts whose content is path coordinates. That content costs context budget
     and explains nothing about a repository. Revisit if hand‑authored SVG proves valuable.
   - **Deliberately not supported in v0.1**, so the exclusion is a decision rather than an
     oversight:
     - Source in languages beyond Python/JS/TS (`.go`, `.rs`, `.java`, `.rb`, `.c`, `.cpp`,
       `.cs`, `.php`, …). Adding them is a scope increase, not a bug fix; a Go repository
       will legitimately report most of its source as `unsupported_extension` until a later
       version widens this.
     - `.csv`, `.tsv`, `.parquet` and similar data files — tabular rows are neither prose nor
       structure, and a moderately sized CSV consumes context budget without explaining
       anything.
     - `.html`, `.css` — presentation, and frequently generated.
     - `.xml` — dominated by build output and generated descriptors; the genuinely useful
       cases (`pom.xml`) do not justify pulling in the rest yet.

   #### Amendment — 2026-08-17: supported list widened

   **Trigger.** A live smoke run of the Milestone 3 classifier against `psf/requests`
   returned **78 skipped of 153 entries, 72 of them `unsupported_extension`**. The skipped
   set was `.yml`, `.toml`, `.cfg`, `.rst`, `.in` and extensionless dotfiles — all readable
   text, much of it the repository's configuration and prose. `evals.md` Milestone 3 requires
   that "no important readable files are accidentally excluded", so the original list failed
   its own eval on a mainstream Python repository.

   **What changed.** The original list (`.md`, `.markdown`, `.py`, `.ipynb`, `.json`, `.txt`,
   optionally `.js`/`.ts`) was written for prose, code and notebooks and omitted the
   configuration layer entirely. It now covers structured config, reStructuredText, shell
   scripts, template variants, and a closed set of recognised extensionless filenames.

   **What did not change.** The skip rules. Lockfiles, vendored directories, binaries and the
   size threshold are unaffected — this widened what counts as readable, it did not weaken
   what counts as junk. `package-lock.json` is still skipped as a lockfile despite `.json`
   being supported.

   **Why filenames as well as extensions.** `Dockerfile`, `Makefile` and `.gitignore` carry
   real signal about how a project builds and runs, and none of them has an extension.
   Matching them by exact name keeps the rule closed and predictable; anything extensionless
   that is *not* on the list is still skipped, and says so by name.

   #### Amendment — 2026-08-17 (second pass): residue swept

   **Trigger.** After the first amendment, `psf/requests` still reported 23
   `unsupported_extension` of 153 entries. Enumerating them individually — rather than
   accepting the count — showed that most were correctly skipped, but a handful were excluded
   by *omission* rather than by decision. `evals.md` Milestone 3 requires that no important
   readable file is *accidentally* excluded; accidental is precisely the distinction.

   **Added: `.cnf`.** OpenSSL configuration files (4 in the residue). Plain-text `key = value`
   config, structurally identical to `.ini` and `.cfg`, both already supported. Excluding it
   while supporting its near-identical siblings was an oversight.

   **Added: `.bat`.** Windows batch scripts (`docs/make.bat` in the residue). `.sh` is already
   supported, and `.bat` is its direct counterpart — the same build or documentation command,
   written for the other platform. Excluding one while supporting the other was **asymmetry,
   not judgement**: there is no reading of "readable text" under which a shell script is
   content and a batch script is not. On a Windows-developed repository the `.bat` file may be
   the *only* committed form of the build entry point.

   **Added: `py.typed` and `.nojekyll`, by filename.** Both are zero-byte marker files whose
   *existence* is the signal: `py.typed` (PEP 561) declares that a package ships type hints,
   `.nojekyll` tells GitHub Pages not to run Jekyll. The decision is to **support** them rather
   than improve their skip message. Classification answers "is this part of the repository's
   readable inventory?", and for a marker file the answer is yes — a reader scanning the
   selected list learns something real from seeing `py.typed` there. The cost is one empty
   file at extraction; the alternative was to skip them under a code reading
   `unsupported_extension`, which is simply the wrong description of a file that is not
   unsupported but empty. Matched by exact filename, so the closed set stays tight — a
   `.typed` extension is *not* broadly supported.

   **Checked and deliberately left skipped.** The remaining residue after this amendment is
   16 entries, every one of them a decision rather than an omission:
   - 14 credential-shaped files (`.key` ×4, `.csr` ×3, `.pem` ×3, `.crt`, `.srl`, and two
     extensionless files named `ca`). These are TLS test fixtures. They stay skipped, and are
     the subject of the deferred `CREDENTIAL_LIKE` proposal in `plan.md` — the open question
     is how to name them, not whether to read them.
   - `.css` and `.html`, already recorded above as deliberately not supported.

   Driving the count to zero was not the goal. The goal was that every remaining exclusion be
   traceable to a decision written down somewhere.

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