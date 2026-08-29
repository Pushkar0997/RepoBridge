# RepoBridge v0.1 — Capability Register

**What this file is for.** Every capability RepoBridge does **not** have, in one place,
so an agent can check before building on an imagined one. The gap was recorded in
`AGENT_LOG.md` (2026-08-28) and in `specs/002-repobridge-v0.2/plan.md` under "Deferred
design items"; that entry proposed `architecture.md`, which does not exist, so the
register lives here beside the rules it qualifies.

**How to read a row.** Every entry carries a **kind** and a **recorded in**:

| Kind | Meaning |
|---|---|
| **Deliberate** | Decided against. Do not "fix" it. Reopening needs a dated amendment. |
| **Gap** | Not decided against — simply not built, or built and not verified. Fair game. |
| **Gated** | Decided *yes, later*, behind a stated condition. Check the condition first. |

**Sourcing.** Every row was checked against the code on 2026-08-29, not against memory.
Where the code and a spec file disagree, the row says so. Anything found with **no
written home** is in section 9 — those are the dangerous ones, because nothing stops an
agent assuming the opposite.

This file is descriptive. It does not create or reverse a decision; `CONTRACT.md`,
`spec.md`, `selection.md` and `specs/decisions.md` do that.

---

## 1. Sources RepoBridge cannot read

| # | Cannot | Kind | Recorded in | Where it bites |
|---|---|---|---|---|
| 1.1 | Read a **private repository** | **Gated** — on summarisation moving off a provider tier that trains on submitted prompts. Non-negotiable. | `spec.md` 7.6 ("blocking prerequisite"); `CONTRACT.md` "Never do this"; `decisions.md` D3; v0.2 `plan.md` gated table | No auth flow exists at all. A private repo 404s like a missing one. |
| 1.2 | Read a host other than **github.com** | **Deliberate** | `spec.md` 3 and 11 ("no crawling or reading arbitrary websites") | `core/input.py:33` — the netloc must equal `github.com` exactly, so `www.github.com` and any GitHub Enterprise host are rejected. |
| 1.3 | Crawl a website, or run a **headless browser** | **Deliberate** | `spec.md` 3 and 11; `AGENTS.md` v0.1 boundaries | No HTTP client exists outside `core/github_client.py` and `core/summarization.py`. |
| 1.4 | Read a **gist, PR, issue, release, wiki or commit history** | **Gap** | Nowhere. See section 9. | Only repo metadata, `git/trees?recursive=1`, and per-file `contents` are ever called. |
| 1.5 | Invent a run for a repo with **no resolvable tree** | **Deliberate** | `CONTRACT.md` I-3, I-7 | An empty repo or unresolvable ref produces a stored failed/degraded run, never a fabricated one. |

---

## 2. File types RepoBridge will not read

The closed sets live in `config.py:SelectionConfig`; the reasoning lives in
`selection.md` section 3, "Deliberately not supported". Every one of these is
**Deliberate**.

| # | Cannot read | Reported as | Recorded in |
|---|---|---|---|
| 2.1 | Source in any language beyond `.py`, `.js`, `.ts`, `.sh`, `.bat` — Go, Rust, Java, Ruby, C, C++, C#, PHP, Swift, Kotlin | `unsupported_extension` | `selection.md` 3. Scheduled for v0.2 M1; `kubernetes/kubernetes` reports 17,167 files this way. |
| 2.2 | `.csv`, `.tsv`, `.parquet` and tabular data | `unsupported_extension` / `non_text_asset` | `selection.md` 3 — "neither prose nor structure" |
| 2.3 | `.html`, `.css` | `unsupported_extension` | `selection.md` 3 — presentation, frequently generated |
| 2.4 | `.xml` | `unsupported_extension` | `selection.md` 3 — dominated by build output |
| 2.5 | `.svg` — **a judgement, not an omission** | `non_text_asset` | `selection.md` 3; `config.py` comment. SVG *is* text; committed SVGs are export artifacts whose content is path coordinates. |
| 2.6 | Anything inside an excluded directory (`node_modules`, `vendor`, `dist`, `build`, `.git`, `__pycache__`) — **even a supported type** | `excluded_directory` | `selection.md` 4; `config.py:excluded_directories`. Position beats type. |
| 2.7 | Dependency **lockfiles**, despite several being valid `.json`/`.yaml` | `lockfile` | `selection.md` 3; `decisions.md` asymmetry 4 |
| 2.8 | Files over **1,000,000 bytes** | `too_large` | `config.py:max_file_bytes`; `selection.md` 4 |
| 2.9 | **Submodule** contents | `submodule` | `selection.md` 3 — they live in another repository |
| 2.10 | Non-UTF-8 bytes that pass classification | per-file `failed` | `core/github_client.py:352` — a `UnicodeDecodeError` is a per-file failure, never a run failure. No encoding detection, no `latin-1` fallback. |
| 2.11 | Distinguish a **credential-shaped file** (`.pem`, `.key`, `.crt`, `.csr`) from any other unknown type | **Gap, scoped** — `CREDENTIAL_LIKE` proposed, not built | `plan.md` M3 "Candidate for a later milestone"; `selection.md` 6; v0.2 `plan.md` deferred. The open question is false positives, not whether. |

---

## 3. Reading and extraction

| # | Cannot | Kind | Recorded in |
|---|---|---|---|
| 3.1 | Read more than **200 files per run** (100 on a shared instance). The rest are stored as `not_fetched`, never dropped. | **Deliberate** | `spec.md` 7.4 amendment 2026-08-18; `config.py:max_files_per_run`; `CONTRACT.md` constants |
| 3.2 | Download the repo as a **tarball or zipball** | **Deliberate** | `decisions.md` D1 — per-file HTTP status is load-bearing for `selected == read + failed + not_fetched` |
| 3.3 | **Split a file into multiple chunks.** One chunk per file; only notebooks split, one chunk per cell. A 1 MB file is one ~250k-token chunk. | **Gap** | `core/extraction.py:extract_file`; v0.2 `plan.md` deferred. `chunk_index` already exists, so adding splitting will not change the model. |
| 3.4 | Count tokens accurately — the estimate is **`chars // 4`** | **Deliberate**, with a known bias | `CONTRACT.md` conventions; `config.py:chars_per_token`; v0.2 `plan.md` deferred — it under-counts code, so the risk is overspending the budget |
| 3.5 | Read more than **8 files concurrently** | **Deliberate** — higher concurrency provokes GitHub's *secondary* rate limits | `config.py:max_concurrent_reads` |
| 3.6 | Parse or understand code — no AST, call graph, type graph, static analysis, symbol index | **Deliberate** | `spec.md` 3 and 11 — "a context bridge, not a static analyzer" |
| 3.7 | Search or embed content — no vector store, no semantic search, no full-text index | **Deliberate** | `spec.md` 3; `AGENTS.md` v0.1 boundaries. The only content filter is `path` substring matching. |

---

## 4. Summarisation

| # | Cannot | Kind | Recorded in |
|---|---|---|---|
| 4.1 | Use any provider other than **Google Gemini** | **Deliberate** — one real integration before an adapter | `spec.md` 7.6 amendment; `decisions.md` D2; `core/summarization.py` module docstring |
| 4.2 | Accept a provider or model as a **request field** | **Deliberate** | `spec.md` 5 (`llm_provider` removed 2026-08-18); `decisions.md` D4. The model is `REPOBRIDGE_GEMINI_MODEL`, read at call time. |
| 4.3 | Exceed roughly **500 provider requests/day** (~20/day on quality-tier models) | External constraint, **accepted** | `AGENTS.md` budget clause; `config.py:SummarizationConfig`; `CONTRACT.md` quota arithmetic |
| 4.4 | Recover from a **daily-quota 429** by retrying — it deliberately fails immediately | **Deliberate**, and counter-intuitive: the advertised ~58 s `RetryInfo` is wrong | `spec.md` 7.6 Decision 3; `CONTRACT.md` "Never do this". **Absent from `decisions.md`** — see section 9. |
| 4.5 | Retry any other 4xx | **Deliberate** — a rejected request does not become valid by repetition | `spec.md` 7.6 Decision 3 |
| 4.6 | Summarise a run with **zero chunks**, or a degraded run | **Deliberate** — the provider is never called; `NO_CONTENT` is returned | `core/summarization.py` grounding rule 2 |
| 4.7 | **Stream** a summary, or show live progress while one generates | **Gap** | Nowhere as a decision. `spec.md` 8 asks the system to "surface progress or state rather than freezing"; the request is synchronous. See section 9. |
| 4.8 | Keep more than one summary per run — re-summarising **overwrites** | **Gap** | `POST /api/runs/{id}/summarize` exists (`spec.md` 7.6 Decision 4); there is no version history. See section 9. |
| 4.9 | Guarantee the model obeys the prompt's disclosure instructions | **Deliberate and stated** — the weakest of three grounding mechanisms, which is why provenance is computed independently, before the call | `core/summarization.py` grounding rule 3 |

---

## 5. Storage, state and lifecycle

| # | Cannot | Kind | Recorded in |
|---|---|---|---|
| 5.1 | **Migrate a schema.** A schema change means deleting `repobridge.db`. | **Deliberate**; **Gated** on holding data that cannot be regenerated | `decisions.md` D5; README "Upgrading"; v0.2 `plan.md` gated table |
| 5.2 | **Delete a run, or expire old ones.** Ten analyses of one repo store ten copies. | **Gap**; **Gated** on storage growth becoming a real problem | v0.2 `plan.md` deferred and gated table. No delete endpoint exists. |
| 5.3 | Run against anything but **SQLite** | **Deliberate** for v0.1 | `spec.md` 8; `config.py:DatabaseConfig` requires an async driver URL |
| 5.4 | Detect a wiped filesystem — `REPOBRIDGE_STORAGE=ephemeral` is **declared, not detected** | **Deliberate** — a wiped database and a new one are indistinguishable | `plan.md` M10.5 "What was built" |
| 5.5 | Serve **more than one worker** — the rate limiters are per-process and in memory, so the limits silently double | **Deliberate**, and the boundary is stated | `core/limits.py` "What this deliberately does not do"; `plan.md` M10.5; README "Run one worker" |
| 5.6 | Survive a restart with rate-limit state intact | **Deliberate** — same boundary as 5.5 | `core/limits.py` |

---

## 6. Access, identity and deployment

| # | Cannot | Kind | Recorded in |
|---|---|---|---|
| 6.1 | **Authenticate anyone.** No accounts, no login, no sessions, no roles. | **Deliberate**; **Gated** on someone asking to pay or repeatedly hitting the shared limits | `spec.md` 3; `plan.md` M10.5 "What is deliberately not built"; `decisions.md` D10; v0.2 gated table |
| 6.2 | Protect `POST /api/analyze` — the API is **unauthenticated**, so anyone with the URL bypasses the UI | **Deliberate, recorded as an accepted consequence** | `plan.md` M10.5 "Recorded consequence, not resolved"; `decisions.md` D10 |
| 6.3 | Isolate visitors on a shared instance — **every run is visible to every visitor** | **Deliberate**, and disclosed on the landing page | `plan.md` M10.5 |
| 6.4 | Identify a client by anything stronger than an **IP address from a client-controlled header** | **Deliberate** — "fairness between honest testers, not a security control" | `core/limits.py`; `plan.md` M10.5 "The boundary this posture must not be allowed to blur" |
| 6.5 | Accept a **secret as a request field** | **Deliberate** | `CONTRACT.md` I-6; `spec.md` 5; `decisions.md` D4 |
| 6.6 | Bill, meter or charge anyone | **Deliberate**; **Gated** with 6.1 | `spec.md` 3 and 11 |

---

## 7. API and interface surface

| # | Cannot | Kind | Recorded in |
|---|---|---|---|
| 7.1 | Offer a **versioned API**. Endpoints are unversioned and declared unstable. | **Deliberate**; **Gated** on an external consumer existing to pin it | `decisions.md` D6; README "API stability"; enforced by `test_no_endpoint_has_acquired_a_version_prefix` |
| 7.2 | Serve `GET /api/runs/{id}/tree` — **deliberately not built**, despite `spec.md` 9 and `evals.md` naming it | **Deliberate** | `decisions.md` D8. `/files` serves the same fact with filtering and pagination. Note that `src/repobridge/api/routes_tree.py` exists as an empty file — see section 9. |
| 7.3 | Wrap successful responses in a `data` envelope, as `tasks.md` suggests | **Deliberate** | `api/errors.py` "Successes are not wrapped". **Absent from `decisions.md`** — see section 9. |
| 7.4 | Act as an **MCP server** | **Deliberate for v0.1**; scheduled for v0.2 M2–M4, itself gated on M0 and M1 | `spec.md` 3; `AGENTS.md`; v0.2 `plan.md` |
| 7.5 | Push, webhook, subscribe or notify — every interaction is a synchronous request | **Gap** | Nowhere. See section 9. |
| 7.6 | Compare two runs, or diff a repository against an earlier analysis | **Gap** | Nowhere. See section 9. |
| 7.7 | Filter file or chunk listings by anything but `status`, `reason` and a `path` substring | **Gap** | `api/routes_files.py`, `api/routes_chunks.py` |

---

## 8. Verification RepoBridge has not done

Not missing capabilities — **capabilities whose evidence is thinner than the rest**.
Recorded here because an agent reading only the PASS rows would over-trust them.

| # | Unverified | Kind | Recorded in |
|---|---|---|---|
| 8.1 | **Truncation has never been exercised live.** The largest tree retrieved was 37,393 entries and GitHub did not truncate it; the threshold is near 100k. Every truncation path is mock-only, end to end, since Milestone 2. | **Gap**, openly held | `evals.md` M2, M4, M6, M8 caveats; `smoke.md`; v0.2 `plan.md` deferred |
| 8.2 | **A live GitHub rate limit has never been reproduced.** Five tests cover it; reproducing it means deliberately exhausting a real quota. | **Gap**, openly held | `evals.md` M7 verdict row |
| 8.3 | **The Dockerfile has never been built.** Static consistency tests cover the class of failure; the image itself is untested. | **Gap** | v0.2 `plan.md` deferred |
| 8.4 | **No balanced mixed repository** is in the live sample. `twemoji` skips almost everything; `Hello-World` is one file. | **Gap** | `evals.md` M3 |
| 8.5 | **Ranking is measured on one repository** (`psf/requests`, cap 20). `CONTRACT.md` I-5 says re-check whenever the sampled set changes — and v0.2 M1 changes it. | **Gap**, with a standing instruction | `CONTRACT.md` I-5; `core/ranking.py`; v0.2 `plan.md` M1 risk |

---

## 9. Found while writing this, recorded nowhere else

**These are the rows that matter most.** Everything above had a written home; nothing
below did. Listed so the next agent does not assume the opposite. **None of these were
fixed** — this was a documentation task.

1. **The extraction identity is never verified from stored rows.** `CONTRACT.md` I-1
   claims both identities are "recomputed from stored rows". Only the classification one
   is (`api/routes_runs.py:937` `stored_identity_holds`, and
   `test_identity_is_reconstructible_from_stored_rows_alone`).
   `selected == read + failed + not_fetched` is checked only in memory
   (`core/extraction.py:154`). `storage.content_status_counts` — the function that would
   close it — **exists at `infra/storage.py:467` and is called by nothing in `src/` or
   `tests/`**. Dead code and an unenforced half-invariant, together.

2. **No test scans a log line for a secret.** I-6 says "never a log line" and claims
   detection by value scans. The value scans cover stored rows and rendered pages only.
   `api/errors.py:_unhandled` states outright that the traceback reaching the log has
   **had no redaction performed**. `core/diagnostics.py:redact` also matches whole
   secrets only, not the 8-character fragments the rendered-page scan checks for.

3. **A repository refused for size reaches GitHub and stores nothing.** I-7 says every
   attempt that reached GitHub leaves a stored trace, with URL validation as *the*
   deliberate exception. The shared-instance 413 path (`api/routes_runs.py:455`) spends
   two GitHub calls, then raises without creating a run or persisting events.
   `test_the_size_refusal_is_recorded_in_diagnostics` confirms it in a comment: "no run
   row is created … the trace is the log and the response". Either a second deliberate
   exception or a defect; it is currently neither.

4. **The daily-quota 429 is never retried** — a real, counter-intuitive decision with a
   measured rationale, recorded in `spec.md` 7.6 and `CONTRACT.md`, but **absent from
   `decisions.md`**, which is where an agent is told to look for settled questions.

5. **Successes are deliberately not wrapped in a `data` envelope**, rejecting
   `tasks.md`'s suggestion. Reasoned at length in `api/errors.py` and recorded in no
   spec file.

6. **There is deliberately no `WARNING` diagnostic level.** `core/diagnostics.py` argues
   it out — "having both a precise and a vague option guarantees the vague one gets
   used". Recorded in a module docstring only.

7. **`src/repobridge/api/routes_tree.py` and `src/repobridge/infra/logging.py` are both
   zero-byte files.** They are named for exactly the two things `decisions.md` D8 and D7
   say were deliberately *not* built. An agent finding them will reasonably assume
   unfinished work and fill them in.

8. **No gist, PR, issue, release, wiki or commit-history support** (1.4), **no streaming
   or progress for a generating summary** (4.7), **no summary history** (4.8), **no
   push, webhook or subscription** (7.5), and **no run-to-run comparison** (7.6) are
   recorded anywhere as either decisions or gaps.

9. **`spec.md` 11 says "No deployment scripts for cloud or containers"** and README's
   "Out of scope" says "cloud or multi-user deployment", but Milestone 10.5 shipped a
   `Dockerfile`, platform `HOST`/`PORT` handling and a live shared instance. The
   multi-user half still holds; the cloud and container half is stale.

10. **README "Limitations" says "Local and single-user"** while a shared demo is live.
    The same staleness as 9, in the document a new user reads first.
