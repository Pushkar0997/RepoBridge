# RepoBridge v0.1 Smoke Suite

The repeatable smoke list `evals.md` asks for under "Recommended smoke test suite", with the
fields it names recorded per run.

Purpose: close plan.md Milestone 2 validation item V1 — "use a small set of sample public
repos for smoke tests" — with recorded outcomes rather than a single ad-hoc check.

---

## Current state

Latest recorded result per repo. The run log below is the historical record; this table is
the answer to "where do we stand". Update it whenever a run is added.

| Repo | Latest run | Date | Entries | Selected | Skipped | Rows stored | Files read | Chunks | Leading skip reason |
|---|---|---|---|---|---|---|---|---|---|
| `kubernetes/kubernetes` | Run 5 | 2026-08-18 | 37393 | 8376 | 22924 | 37393 | not read | — | `unsupported_extension` (17167) |
| `github/docs` | Run 8 | 2026-08-18 | 14903 | 11217 | 2227 | 14903 | 200 of 11217 | 198 | `non_text_asset` (1814) |
| `twitter/twemoji` | Run 3 | 2026-08-17 | 7413 | 17 | 7389 | not stored | not read | — | `non_text_asset` (7378) |
| `psf/requests` | Run 8 | 2026-08-18 | 153 | 107 | 23 | 153 | 107 of 107 | 104 | `unsupported_extension` (16) |
| `Pushkar0997/quantum-toybox` | Run 7 | 2026-08-18 | 40 | 30 | 0 | 40 | 30 of 30 | 127 | — (nothing skipped) |
| `octocat/Hello-World` | Run 8 | 2026-08-18 | 1 | 1 | 0 | 1 | 1 of 1 | 1 | — (nothing skipped) |
| `Pushkar0997/definitely-not-a-real-repo-zzz` | Run 1 | 2026-08-17 | — | — | — | — | — | — | 404 at metadata, as intended |

> **`psf/requests` stays at its Run 8 figures deliberately.** Run 9 re-ran the same
> repository at a deliberate cap of 20 to test file ranking, so its "files read" is 20 of
> 107 by design. Recording that as the repository's current state would misreport how
> RepoBridge behaves by default. Run 9 is in the run log below.

Every repo in the suite has been classified. "Rows stored" reads *not stored* for repos last
measured before persistence existed (Runs 3 and 4), and "Files read" reads *not read* for repos
last measured before extraction existed (Runs 3-5) — those figures are still valid, they simply
predate the feature. Only the two repos in Run 6 have been through the full pipeline.

**The accounting identity holds on every one of them**, including `kubernetes/kubernetes` at
37,393 entries: `6093 + 8376 + 22924 + 0 == 37393`, with `accounts_for_every_entry: true`. No
tree entry has gone unaccounted for in any run, at any scale tried.

| Run | Date | What it covered |
|---|---|---|
| Run 1 | 2026-08-17 | Milestone 2 retrieval: six repos, three error cases, quota-exhaustion observations |
| Run 2 | 2026-08-17 | Milestone 3 classification, first spec amendment |
| Run 3 | 2026-08-17 | Binary-heavy repo added; second spec amendment re-measured |
| Run 4 | 2026-08-17 | Classification backfilled for the three Run 1 repos; identity tested at 37,393 entries |
| Run 5 | 2026-08-18 | Persistence and the UI: runs stored and read back, two-process restart, tree-page scale honesty |
| Run 6 | 2026-08-18 | Extraction: content read and chunked, notebook flattening verified against source, connection pooling measured |
| Run 7 | 2026-08-18 | Summarisation on the new default model, through the new re-summarise endpoint; one live provider request |
| Run 8 | 2026-08-18 | Four summaries chosen to exercise partial coverage; the read cap hit live for the first time; one overgeneralisation found |
| Run 9 | 2026-08-18 | The Run 8 capped case repeated with rank-ordered file selection; the overgeneralisation is gone |

---

## How to run

Each repo costs **two** GitHub calls (metadata + tree); a nonexistent repo costs one, because
it fails at the metadata step. A full pass is ~13 calls.

**A token is strongly recommended.** Without `REPOBRIDGE_GITHUB_TOKEN` set you are on the
unauthenticated 60/hour per-IP quota, which a full pass will exhaust if anything else has used
it — that is exactly what happened during the first attempt at Run 1, recorded below. With a
token the quota is 5000/hour. **Runs 1 through 6 were all authenticated at 5000/hour.**

```bash
export REPOBRIDGE_GITHUB_TOKEN=your_token_here
```

Runs are exercised in-process via FastAPI's `TestClient` against `POST /api/analyze`; no
running server is needed. The unit suite is separate:

```bash
python -m pytest -v
```

Record for each repo: URL, outcome, file count, chunk count, summary quality notes,
diagnostics issues, manual observations — the fields `evals.md` specifies.

> **When you record a run, update the "Current state" index above.** A stale index is worse
> than no index: the run log is append-only history, so the table at the top is the only place
> that answers "where do we stand", and a reader will trust it. Add the run to the run-index
> table too.

**Field availability at v0.1 Milestone 2.** `chunk count` and `summary quality` depend on
extraction (Milestone 5) and summarization (Milestone 6), and `diagnostics issues` depends on
Milestone 7. Those columns are marked `n/a (Mn)` rather than left ambiguous — they are not
failures, they are not built yet. `file count` is reported as `tree_entry_count`, which counts
every tree entry (directories included), not readable files; file classification is
Milestone 3.

---

## Sample repos

| # | Category | Repo |
|---|---|---|
| 1 | tiny | `octocat/Hello-World` |
| 2 | medium | `psf/requests` |
| 3 | notebook-heavy | `Pushkar0997/quantum-toybox` |
| 4 | docs-heavy | `github/docs` |
| 5 | deeply nested / multi-directory | `kubernetes/kubernetes` |
| 6 | intentionally nonexistent | `Pushkar0997/definitely-not-a-real-repo-zzz` |
| 7 | asset-dominated / binary-heavy | `twitter/twemoji` |

`twitter/twemoji` was added for plan.md Milestone 3's "test binary-heavy repos" validation
item. It qualifies: it is an emoji asset library whose contents are ~7,000 SVG and PNG files
with a thin shell of build tooling, so `non_text_asset` should be the dominant skip reason by
a wide margin. It is also large enough (7,413 entries) to stress the accounting identity,
which is the property most likely to break at scale.

---

## Run log

### Run 1 — 2026-08-17

- **Date:** 2026-08-17, 08:52:06–08:52:22 UTC (16 s for the whole suite)
- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token value never read
  or logged; only the presence of the `Authorization` header was checked.
- **Commit:** `2b63b32`, with `src/` and `tests/` unmodified (`git diff -- src tests` empty).
- **Method:** in-process `TestClient` against `POST /api/analyze`, one call per repo with no
  `branch_or_ref`, so each row also exercises the default-branch fallback.

| # | Repo | Ref resolved | HTTP | file count (`tree_entry_count`) | truncated | tree_error | chunk count | summary quality | diagnostics issues | Observations |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `octocat/Hello-World` | `master` | 200 | 1 | false | none | n/a (M5) | n/a (M6) | n/a (M7) | Default branch is `master`, not `main`; fallback resolved it from metadata correctly. 1.8 s |
| 2 | `psf/requests` | `main` | 200 | 153 | false | none | n/a (M5) | n/a (M6) | n/a (M7) | Preview capped at 50 of 153, `tree_entry_count` reports the true 153. 1.9 s |
| 3 | `Pushkar0997/quantum-toybox` | `main` | 200 | 40 | false | none | n/a (M5) | n/a (M6) | n/a (M7) | Notebook-heavy (`language: Jupyter Notebook`); all 40 entries fit the preview. 1.7 s |
| 4 | `github/docs` | `main` | 200 | 14901 | false | none | n/a (M5) | n/a (M6) | n/a (M7) | Docs-heavy. 14.9k entries returned complete, **not** truncated. 2.6 s |
| 5 | `kubernetes/kubernetes` | `master` | 200 | 37393 | false | none | n/a (M5) | n/a (M6) | n/a (M7) | Deeply nested. 37.4k entries, still **not** truncated. 3.6 s |
| 6 | `Pushkar0997/definitely-not-a-real-repo-zzz` | — | 404 | — | — | `Repository not found on GitHub.` | n/a | n/a | n/a (M7) | Fails at the metadata step, so costs one call not two. 0.8 s |

**Error-case checks**

| Case | Expected | Actual |
|---|---|---|
| nonexistent repo | 404, repo-not-found message | **PASS** — 404 `{"detail":{"message":"Repository not found on GitHub."}}` |
| nonexistent branch on a real repo | 404 naming the ref | **PASS** — 404 `{"detail":{"message":"Branch or ref 'does-not-exist-xyz' was not found in Pushkar0997/quantum-toybox."}}` |
| non-GitHub URL | 400 | **PASS** — 400 `{"detail":{"message":"Only github.com repository URLs are supported in v0.1."}}` |

**Outcome: PASS.** Six of six repos behaved as specified, all three error cases returned the
right status and a specific message. Longest retrieval 3.6 s, inside spec.md's "a few
seconds" guidance for tree retrieval.

#### Unplanned live results, retained

Two behaviours were observed live on 2026-08-17 at ~08:35 UTC during an **earlier, aborted
attempt at this suite on the unauthenticated 60/hour quota**. The quota ran out mid-suite.
These were not planned test cases — they are recorded because they exercise, against real
GitHub, two paths the mocked tests only approximate:

- **Degraded-run path (plan E4), observed live.** `Pushkar0997/quantum-toybox` returned
  **HTTP 200** with metadata intact (`full_name`, `default_branch: main`, `language: Jupyter
  Notebook` all present), `tree_entry_count: 0`, and
  `tree_error: "Tree retrieval failed: GitHub API rate limit exceeded while fetching the
  repository tree. The limit resets at 2026-08-17 09:04:07 UTC."` — the metadata-succeeded /
  tree-failed split behaving as designed on a real rate limit, with the true reset time.
- **Status mapping (plan E3), observed live.** Subsequent calls (`github/docs`, and the
  nonexistent repo) returned **HTTP 429**, not 403, with
  `"GitHub API rate limit exceeded while fetching repository metadata. The limit resets at
  2026-08-17 09:04:07 UTC."` — confirming the 403→429 remap against real GitHub headers.

#### Limitations of this run

- **No live truncation observed.** The largest tree retrieved was 37,393 entries
  (`kubernetes/kubernetes`) and GitHub still returned `truncated: false`; its limits are
  around 100k entries / 7 MB. The `tree_truncated` path therefore remains covered by mocked
  tests only (`test_truncated_tree_sets_flag_and_warns_in_tree_error`). Finding a repo that
  truncates for real is still open.
- **Deep nesting is not verifiable from the response.** Only the first 50 entries are
  exposed, so the deepest path visible for `kubernetes/kubernetes` was 2 levels. The
  50-entry preview is a display cap, not a retrieval limit — `tree_entry_count` is the whole
  tree — but the response shape cannot demonstrate nesting depth.
- **`/rate_limit` reported stale figures.** It showed `remaining: 4995, used: 5` immediately
  before and after a 13-call suite, while a real request's own `X-RateLimit-Remaining` header
  read `4978`. The per-response header is authoritative, which is what `_is_rate_limited()`
  reads — the endpoint is not a reliable accounting source and should not be used for one.
- **Chunk count, summary quality and diagnostics columns are structurally empty** at this
  milestone, not blank by oversight. They become fillable at Milestones 5, 6 and 7.

### Run 2 — 2026-08-17: file classification (Milestone 3)

- **Date:** 2026-08-17, after Run 1.
- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token value never read
  or logged.
- **Scope:** classification only. Retrieval behaviour is unchanged from Run 1 and was not
  re-measured; entry counts match Run 1 exactly, which is itself a retrieval regression check.
- **Method:** in-process `TestClient` against `POST /api/analyze`, no `branch_or_ref`.

| Repo | Entries | Directories | Selected | Skipped | Failed | Identity holds | Skipped by reason |
|---|---|---|---|---|---|---|---|
| `Pushkar0997/quantum-toybox` | 40 | 10 | 30 | 0 | 0 | yes | — |
| `psf/requests` | 153 | 23 | 100 | 30 | 0 | yes | `non_text_asset: 7`, `unsupported_extension: 23` |

"Identity holds" is `directories + selected + skipped + failed == total_entries`, returned by
the API as `accounts_for_every_entry`. It was `true` for both repos: no entry vanished.

**Effect of the 2026-08-17 spec amendment.** `psf/requests` was measured twice, before and
after the supported-extension list was widened:

| | Selected | Skipped | `unsupported_extension` |
|---|---|---|---|
| Before amendment | 52 | 78 | 72 |
| After amendment | 100 | 30 | 23 |

The 49 files recovered were `.yml`, `.toml`, `.cfg`, `.rst`, `.in` and recognised
extensionless config filenames — the repository's configuration and prose layer, which the
original list omitted entirely.

**The 23 remaining unsupported on `psf/requests`:** `.key` ×4, `.cnf` ×4, extensionless ×3,
`.csr` ×3, `.pem` ×3, `.css`, `.html`, `.bat`, `.typed`, `.crt`, `.srl`. Judged in `evals.md`
under the Milestone 3 recorded verdict; `.cnf` and `.bat` are flagged there as readable text
excluded by omission rather than decision, which is why that criterion is PARTIAL.

**Notes and limitations**

- **`quantum-toybox` skips nothing at all** — every non-directory entry is a supported type.
  A clean result, but it exercises no skip path, so it validates selection and the accounting
  identity rather than the skip rules.
- **The reason code `binary_extension` was renamed `non_text_asset`** between this run and
  the previous slice's measurement. Counts were re-verified afterwards and are identical; only
  the key changed. Any earlier note quoting `binary_extension` refers to the same rule.

---

### Run 3 — 2026-08-17: binary-heavy repo, and the second spec amendment

- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token never read
  or logged.
- **Purpose:** (a) close plan.md Milestone 3's "test binary-heavy repos" validation item with
  a live asset-dominated repository; (b) re-measure the two Run 2 repos after the second
  `selection.md` amendment added `.cnf`, `.bat`, `py.typed` and `.nojekyll`.

| Repo | Entries | Dirs | Selected | Skipped | Failed | Identity | Skipped by reason |
|---|---|---|---|---|---|---|---|
| `twitter/twemoji` | 7413 | 7 | 17 | 7389 | 0 | **yes** | `non_text_asset: 7378`, `unsupported_extension: 10`, `lockfile: 1` |
| `Pushkar0997/quantum-toybox` | 40 | 10 | 30 | 0 | 0 | yes | — |
| `psf/requests` | 153 | 23 | 107 | 23 | 0 | yes | `non_text_asset: 7`, `unsupported_extension: 16` |

**Binary-heavy result.** `twitter/twemoji` retrieved in 2.4 s, untruncated at 7,413 entries.
`non_text_asset` is the dominant skip reason at **7,378 of 7,389 skips (99.9%)**, which is
what an SVG/PNG asset library should look like. The accounting identity held at this scale:
`7 + 17 + 7389 + 0 == 7413`. This was the case most likely to break it, and it did not.
Selected content is the 17-file build and documentation shell around the assets.

**Effect of the second amendment** on `psf/requests`, measured before and after:

| | Selected | Skipped | `unsupported_extension` |
|---|---|---|---|
| Run 2 (after 1st amendment) | 100 | 30 | 23 |
| Run 3 (after 2nd amendment) | 107 | 23 | 16 |

The 7 recovered are `.cnf` ×4, `docs/make.bat`, `src/requests/py.typed`, `docs/.nojekyll`.
`quantum-toybox` was unchanged at 30/0, as expected — it contained none of the newly
supported types.

**The 16 remaining unsupported on `psf/requests`**, every one a recorded decision rather than
an omission: `.key` ×4, `.csr` ×3, `.pem` ×3, extensionless `ca` ×2, `.crt`, `.srl` — 14
credential-shaped TLS test fixtures, deferred to the `CREDENTIAL_LIKE` proposal in `plan.md` —
plus `.css` and `.html`, listed in `selection.md` as deliberately not supported.

**Limitation.** `twemoji` skips almost everything, and `quantum-toybox` skips nothing. Neither
is a balanced mixed repository; `psf/requests` remains the only live sample exercising several
skip reasons at once.

---

### Run 4 — 2026-08-17: classification backfilled, identity tested at scale

- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token never read or
  logged; only the presence of the `Authorization` header was checked.
- **Purpose:** close the `n/c` cells in the index. `kubernetes/kubernetes`, `github/docs` and
  `octocat/Hello-World` had retrieval figures from Run 1 but predated the Milestone 3
  classifier, so they had never been classified.
- **Method:** in-process `TestClient` against `POST /api/analyze`, no `branch_or_ref`.

| Repo | Entries | Dirs | Selected | Skipped | Failed | Identity | Time |
|---|---|---|---|---|---|---|---|
| `kubernetes/kubernetes` | 37393 | 6093 | 8376 | 22924 | 0 | **yes** | 3.8 s |
| `github/docs` | 14901 | 1459 | 11215 | 2227 | 0 | **yes** | 3.9 s |
| `octocat/Hello-World` | 1 | 0 | 1 | 0 | 0 | yes | 2.1 s |

Skip reasons:

| Repo | `unsupported_extension` | `excluded_directory` | `non_text_asset` | `lockfile` | `too_large` |
|---|---|---|---|---|---|
| `kubernetes/kubernetes` | 17167 | 5692 | 19 | 39 | 7 |
| `github/docs` | 301 | 5 | 1814 | 1 | 106 |

**The accounting identity at 37,393 entries.** This was the case flagged as most likely to
break it, and it did not:

```
6093 directories + 8376 selected + 22924 skipped + 0 failed = 37393
total_entries                                               = 37393
accounts_for_every_entry: true
```

Both the arithmetic and the flag the API computes were checked independently, and agree.

**New live coverage from this run.** Two skip reasons fired against real repositories for the
first time:

- **`too_large`** — 7 files in `kubernetes/kubernetes`, 106 in `github/docs`, over the
  1,000,000-byte `max_file_bytes` threshold. Previously mock-only.
- **`excluded_directory`** — 5,692 in `kubernetes/kubernetes`, overwhelmingly its `vendor/`
  tree. Previously exercised live only in the single-digit range.

Between Run 3 and Run 4, every one of the six skip reasons except `submodule` has now been
observed on a real repository.

**Observations**

- `kubernetes/kubernetes` reports 17,167 `unsupported_extension`, the largest single skip
  group in any run. That is `.go` source, and it is the expected consequence of the decision
  in `selection.md` not to support languages beyond Python/JS/TS in v0.1 — a Go repository
  will legitimately have most of its source unread. It is a scope limit, not a defect, but it
  means RepoBridge currently has little to say about Go projects.
- `github/docs` is the most favourable real repo measured: 11,215 selected of 14,901, because
  a docs site is mostly Markdown. Its leading skip reason is `non_text_asset` (1,814 images).
- Neither large repo was truncated by GitHub, so `tree_truncated` remains mock-only even at
  37,393 entries.

---

### Run 5 — 2026-08-18: persistence and the UI (Milestone 4)

- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token never read or
  logged.
- **Purpose:** exercise the stored path end to end — analyse through the API, read the run
  back, and render it in the UI — and check that the tree page tells the truth about how much
  of a large repository it is showing.
- **Method:** in-process `TestClient` against a scratch database outside the repo.

| Repo | Entries | Rows stored | Dirs | Selected | Skipped | Identity | Tree page, page 1 |
|---|---|---|---|---|---|---|---|
| `Pushkar0997/quantum-toybox` | 40 | 40 | 10 | 30 | 0 | yes | `Showing 1–40 of 40 entries.` |
| `psf/requests` | 153 | 153 | 23 | 107 | 23 | yes | `Showing 1–100 of 153 entries.` |
| `kubernetes/kubernetes` | 37393 | 37393 | 6093 | 8376 | 22924 | yes | `Showing 1–100 of 37393 entries.` |

Stored row counts equal the entry counts the analyze response reported, for all three. The
API-reported `stored_identity_holds` was `true` in every case.

**Two-process restart.** The criterion is "a run survives a restart", so it was tested with
two separate interpreters rather than a disposed engine:

```
process 1 (pid 19172): created run 884e4eb3… for psf/requests, 153 entries, then exited
process 2 (pid 17868): GET /api/runs total = 1
                       run reopened: psf/requests, status completed
                       stored rows 153, identity true, dirs 23 / sel 107 / skip 23
                       home page lists it: yes
                       tree page: HTTP 200, 153 rows
```

Nothing was lost across the process boundary.

**Tree-page scale honesty, `kubernetes/kubernetes` (37,393 entries).** The full table is in
`evals.md` under the Milestone 4 verdict. The essential results:

| View | Scope line |
|---|---|
| page 1 | `Showing 1–100 of 37393 entries.` |
| last page | `Showing 37301–37393 of 37393 entries.` |
| `path=staging/src/k8s.io/api/core/v1/types.go` | `Showing 1–1 of 1 matching entries (of 37393 in this run).` |
| `path=go.mod` | `Showing 1–39 of 39 matching entries (of 37393 in this run).` |
| `path=vendor/golang.org` | `Showing 1–100 of 1007 matching entries (of 37393 in this run).` |
| `path=OWNERS` | `Showing 1–100 of 604 matching entries (of 37393 in this run).` |
| `path=vendor/` + `status=skipped` | `Showing 1–100 of 5574 matching entries (of 37393 in this run).` |

The single-file lookup returned `staging/src/k8s.io/api/core/v1/types.go` as
`skipped / unsupported_extension` with its message — the product's core question
("was this file skipped, and why") answered in one query against a 37,393-entry repository.

**Limitations of this run**

- `github/docs`, `twitter/twemoji` and `octocat/Hello-World` were not re-run through
  persistence; their figures in the index are from Runs 3–4 and predate the database.
- No repository has yet been truncated by GitHub, so the truncation banner remains covered by
  tests only.
- Deep pagination was exercised (last page of 374) but not timed; offset scanning is known to
  degrade and was not measured here.

---

### Run 6 — 2026-08-18: content extraction (Milestone 5)

- **Quota:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token never read or
  logged.
- **Purpose:** exercise reading and extraction end to end, verify notebook flattening against
  the actual source file, and measure the effect of connection pooling.
- **Method:** in-process `TestClient` against a scratch database outside the repo.

| Repo | Selected | Read | Failed | Not fetched | Chunks | Identity | Time |
|---|---|---|---|---|---|---|---|
| `Pushkar0997/quantum-toybox` | 30 | 30 | 0 | 0 | 127 | yes | 5.1 s |
| `psf/requests` | 107 | 107 | 0 | 0 | 104 | yes | 7.5 s |

"Identity" is `selected == read + failed + not_fetched`, reported by the API as
`accounts_for_every_selected_file`. Both repos are under the 200-file cap, so nothing was
`not_fetched`; **the cap path has therefore never been exercised live** and is covered by
tests only.

**Chunk types, `quantum-toybox`:** `notebook_code` 69, `notebook_markdown` 46, `markdown` 11,
`text` 1. 115 of 127 chunks came from notebooks, which is what a notebook-heavy repository
should produce.

**Notebook flattening verified against source.** Rather than eyeballing the output,
`01_bell_state/basic_qiskit_implementation.ipynb` was re-fetched raw and compared cell by
cell. 7 source cells, one empty, 6 chunks; every chunk matched its source cell on index, type
and text:

```
cell 0  code      src  133 chars | chunk 0  notebook_code      133 chars | text equal: True
cell 1  markdown  src  638 chars | chunk 1  notebook_markdown  638 chars | text equal: True
cell 2  code      src  299 chars | chunk 2  notebook_code      299 chars | text equal: True
cell 3  code      src  425 chars | chunk 3  notebook_code      425 chars | text equal: True
cell 4  code      src  473 chars | chunk 4  notebook_code      473 chars | text equal: True
cell 5  code      src  130 chars | chunk 5  notebook_code      130 chars | text equal: True
```

A plain file was checked the same way: `01_bell_state/README.md`, 868 characters in the
source and 868 stored, identical after CRLF normalisation.

**Read performance, `psf/requests` (107 files), measured in one session:**

| Configuration | Time | API calls |
|---|---|---|
| Sequential | 99.6 s | 110 |
| Concurrent, bound 8, client per request | 49.1 s | 110 |
| Concurrent, bound 8, **shared client** | **7.5 s** | 110 |

Call count is identical throughout — concurrency and pooling change *when* requests happen,
not how many. The pooling step was the larger win by far: one client per request meant one
TCP+TLS handshake per file, which is why 8x concurrency had only bought 2x. With a shared
connection pool the same bound gives **13.3x** over sequential.

**No rate-limit failures** were observed at bound 8 in any run, checked explicitly rather
than inferred from the run succeeding.

---

#### Untested caveat: tree-404 cause attribution (reasoned, not observed)

**Not verified by this run or any other.** Recorded so it is not mistaken for tested
behaviour.

`/api/analyze` infers "the caller named a bad ref" from the tree call's status code alone: a
404 on `git/trees/{ref}` when the caller supplied an explicit `branch_or_ref` produces
`"Branch or ref '<ref>' was not found in <owner>/<repo>."` Nothing else about the response is
consulted.

A tree 404 with a different underlying cause would therefore be attributed to the caller's
ref. The case we can identify is an **empty repository**: it has no commits and no HEAD, so
the trees endpoint 404s for any ref. Metadata would have succeeded first — the repo exists —
so the run would reach the tree step and report the supplied ref as not found. That message
is *technically true*, since an empty repo contains no refs at all, but it points at the wrong
thing: the useful answer is "this repository is empty", not "your branch name is wrong".

This is reasoned from GitHub's documented behaviour for empty repositories. **No empty
repository has been exercised against `/api/analyze`**, and creating one was out of scope. To
confirm or refute it, run the suite against a public repository with zero commits and record
the actual status and message here.

Judged a cause-attribution weakness rather than mishandling of a ref, which is why the
"wrong branch/ref handling" failure signal is recorded as eliminated in `evals.md`.


---

### Run 7 — 2026-08-18: summarisation on the new default model (Milestone 6, quota slice)

- **Quota, GitHub:** authenticated, 5000/hour (`REPOBRIDGE_GITHUB_TOKEN` set). Token never
  read or logged.
- **Quota, Gemini:** **exactly one** generate request was spent, deliberately. The analyse
  step ran with `REPOBRIDGE_GEMINI_API_KEY` unset, so it stored the run, the files and the
  chunks and recorded the summary as `not_configured` without reaching the provider; the
  key was restored only for the single `POST /api/runs/{id}/summarize`.
- **Purpose:** verify the new default model by calling it (not by reading `/v1beta/models`,
  which lists models that 404), and exercise the re-summarise endpoint end to end.
- **Method:** in-process `TestClient` against a scratch database outside the repo.

| Repo | Entries | Dirs | Selected | Read | Chunks | Identity | Summary | Model |
|---|---|---|---|---|---|---|---|---|
| `Pushkar0997/quantum-toybox` | 40 | 10 | 30 | 30 of 30 | 127 | yes | `ok` | `gemini-3.5-flash-lite` |

Classification and extraction figures are **identical to Run 6** — 40/10/30/0, 127 chunks,
both identities `true` — which is the regression check for everything below summarisation.

**The model.** `gemini-3.5-flash-lite` returned HTTP 200 on the first call. That is the
verification: a model ID is a claim until a request against it succeeds. Prompt was 17,001
estimated tokens (`chars//4`) against a 120,000 budget, so nothing was dropped.

**The endpoint.** `POST /api/runs/{id}/summarize` produced a summary from stored chunks
with **no GitHub request** — visible in the request log, which shows no `api.github.com`
call between the analyse response and the Gemini call other than the `/rate_limit` probe
this script made itself. The stored summary read back identical in text, model and
provenance.

**Provenance returned with the prose:**

```
read 30 of 30 selected files
sent 127 of 127 extracted chunks
is_partial: false, limitations: []
tree_truncated: false, skipped_count: 0, files_not_fetched: 0
```

The summary opened by stating that coverage was complete, named the ten numbered
directories, and named `qiskit`, `qiskit-aer` and `matplotlib` from `requirements.txt` —
every claim checkable against the inventory above.

**Limitations of this run**

- **One repository, one model, one call.** The lite model is verified as *reachable and
  working*; nothing here compares its summary quality against `gemini-3.7-flash`, and the
  rubric in `evals.md` has not been scored across several repos.
- **The daily-quota fast-fail path was not observed live**, by design — provoking it would
  cost a day's allowance. It is reproduced from a real-shaped 429 body in
  `tests/test_summarization_retry.py`, along with every retry and backoff path.
- **`/rate_limit` is still stale**, as Run 1 recorded. It read `used 5, remaining 4995`
  before and after ~32 real calls. Its figures are not an accounting source and the
  "calls spent" arithmetic in this run's script is therefore meaningless; the request log
  is the evidence.


---

### Run 8 — 2026-08-18: four summaries against partial coverage (Milestone 6 closing runs)

- **Quota, GitHub:** authenticated, 5000/hour. `/rate_limit` again reported `used 31`
  unchanged across ~340 real calls, so it is again not an accounting source; the true cost
  is derivable: 22 + 202 + 3 + 109 = **336 calls**.
- **Quota, Gemini:** **four** summaries, one per case, on `gemini-3.5-flash-lite`. No case
  was retried by hand. **Five HTTP attempts were made**: the fourth case returned a
  transient 429 on its first attempt and the retry policy cleared it after a 16.0 s wait
  (`Summarisation attempt 1/3 returned status 429; retrying in 16.0s`), which is why that
  case took 22.2 s against ~2 s for the others. **First live exercise of the retry path**,
  and evidence the daily/per-minute discrimination works: a daily-quota 429 would have
  failed fast instead.
- **Purpose:** close the Milestone 6 PARTIALs, all of which came from having exactly one
  live summary, on a run with complete coverage and nothing to disclose. Each case here
  exercises a limitation the stub tests cannot reach.
- **Method:** in-process `TestClient` against a scratch database outside the repo. Every
  case analysed with `REPOBRIDGE_GEMINI_API_KEY` **withheld**, so the analyse step stored
  the run without touching the provider, then spent exactly one request through
  `POST /api/runs/{id}/summarize`.

| Case | Repo | Selected | Read | Chunks sent | `is_partial` | Limitations | Prose acknowledged them |
|---|---|---|---|---|---|---|---|
| capped | `psf/requests` (cap 20) | 107 | **20** | 20 of 20 | true | 2 | **yes**, with exact figures |
| large partial | `github/docs` | 11217 | **200** | **116 of 198** | true | 3 | **yes**, both figures exact |
| sparse | `octocat/Hello-World` | 1 | 1 | 1 of 1 | false | 0 | **yes** — refused to characterise |
| full code | `psf/requests` | 107 | 107 | **84 of 104** | true | 2 | **yes**, chunk figure exact |

**The read cap fired live for the first time**, on two cases. It has been test-only since
Milestone 5. `accounts_for_every_selected_file` was `true` on all four:
`107 == 20 + 0 + 87` and `11217 == 200 + 0 + 11017`.

Two cases also hit the **token budget** for the first time live — 82 chunks dropped for
`github/docs`, 20 for `psf/requests` at full coverage — which had likewise only ever been
exercised against mocks.

#### The summaries, and what each disclosed

**capped — `psf/requests`, 20 of 107 files.** Opened:

> "Coverage is partial: out of 153 repository entries and 107 selected readable files,
> exactly 20 files were read, and non-text assets and unsupported extensions were skipped."

Every number matches the provenance. It then described contribution guidelines, issue
templates, a security disclosure process, a code of conduct, CODEOWNERS, and workflows for
tests, linting, type checking, CodeQL, thread locking, issue autoclosing and PyPI
publishing — **and concluded that "the project organisation is heavily structured around
GitHub infrastructure and automation".** See the finding below.

**large partial — `github/docs`, 200 of 11,217 files.** Opened:

> "Coverage is partial, as 11,017 selected files were not read due to a read limit of 200
> files, and 82 extracted chunks exceeded the token budget."

Both limitations, both exact, in the first sentence. Despite reading **1.8%** of the
repository it identified the real shape of the project — the Next.js/TypeScript
application, Markdown articles under `content/`, the `docs-internal` split, and the Moda
and Kubernetes deployment configuration.

**sparse — `octocat/Hello-World`, one file.** The case with no mechanical limitation to
lean on (`is_partial: false`, `limitations: []`), so honesty here is the model's alone:

> "The content is extremely sparse and consists only of a README file containing that short
> greeting. … Because the repository inventory contains only a single readable entry and no
> other files, modules, dependencies, licences, or code structures are mentioned in the
> provided text or inventory, it is not possible to further characterise the repository or
> its organisation."

This is `SYSTEM_INSTRUCTIONS` rule 5 obeyed exactly: it declined to characterise rather
than padding. **The strongest result of the run**, and the one the previous verdict most
needed.

**full code — `psf/requests`, 107 of 107 files.** Same repository as the capped case, so
coverage is the only variable:

> "Coverage of this repository is partial, as 20 extracted chunks were omitted from the
> model token budget… The codebase is organised into a main source directory containing
> core logic modules such as api.py, sessions.py, models.py, adapters.py, auth.py, and
> utils.py, alongside a comprehensive documentation directory and a test suite."

#### Mechanical audit

Claims were checked against **the text the model actually saw**, not against everything
stored — `rank_chunks` and `select_within_budget` are deterministic, so the exact prompt
content is reconstructible from the database. That distinction matters here: two runs sent
only part of their chunks, and a claim grounded in a dropped chunk is not grounded.
Reconstruction matched the recorded `chunks_included` and token count exactly on all four.

| Case | Claims checked | Unsupported | Filenames asserted | Verdict |
|---|---|---|---|---|
| capped | 15 | 0 | none | all traced |
| large partial | 16 | 0 | none real (see below) | all traced |
| sparse | 2 | 0 | none | all traced |
| full code | 15 | 0 | 6, **all read** | all traced |

`api.py`, `sessions.py`, `models.py`, `adapters.py`, `auth.py`, `utils.py` were each
checked against `analysis_files`: all six exist and all six have `content_status = read`.
**No summary named a file it had not read, and no summary named a file that does not
exist.**

**Two audit flags were raised and both were defects in the audit, not the summaries.**
Recorded because an audit that is not itself audited is worth little:

- *"simple, yet elegant HTTP library" reported missing.* The source reads "A simple, yet
  elegant, HTTP library." — an extra comma the search term lacked. In the full-coverage run
  it is in `README.md`, which was read. In the **capped** run `README.md` was
  `not_fetched` and the string appears in **zero** read chunks: there it came from the
  **GitHub metadata description**, which `build_prompt` supplies explicitly labelled
  "Description (from GitHub metadata)". Rule 4 permits naming things from the content *or
  the inventory*, so this is grounded — but grounded in metadata, which the prose states as
  flatly as if it had been read.
- *"Next.js" reported as a filename not in the repository.* The filename regex parsed the
  framework name as a `.js` file. It appears in 6 read chunks. False positive.

#### FINDING — a capped summary generalised from an unrepresentative sample

**The most important result of this run, and a negative one.**

The read cap takes the *first* N selected files in classification order, which is GitHub's
tree order, which is roughly alphabetical. For `psf/requests` with a cap of 20, those 20
are:

```
.coveragerc, .git-blame-ignore-revs,
.github/AI_POLICY.md, .github/CODEOWNERS, .github/CODE_OF_CONDUCT.md,
.github/CONTRIBUTING.md, .github/FUNDING.yml, .github/ISSUE_TEMPLATE.md,
.github/ISSUE_TEMPLATE/{Bug_report,Custom,Feature_request}.md, .github/SECURITY.md,
.github/dependabot.yml,
.github/workflows/{close-issues,codeql-analysis,lint,lock-issues,publish,run-tests,typecheck}.yml
```

**18 of 20 are `.github/`.** `README.md` was not read. Every file of
`src/requests/` — `api.py`, `sessions.py`, `models.py`, `adapters.py`, `auth.py` — was
`not_fetched`. The summary then stated:

> "The project organisation is heavily structured around GitHub infrastructure and
> automation."

**Every individual fact in that summary is grounded. The characterisation is not.** It is a
claim about *the project's organisation* inferred from a sample that is 90% one directory,
and it is materially wrong about `psf/requests`, whose organisation is `src/requests/`,
`docs/` and `tests/`. A reader who skims past the first sentence comes away misinformed
about what the library is.

**This is not a summarisation defect.** The summariser disclosed the sample size accurately
and in the first sentence, invented nothing, and named no unread file. The defect is
**which 20 files the cap chose** — precisely the open item recorded in `plan.md` under
"Milestone 5 — open item: which 200 files a capped run reads", which predicted that a
capped run "would be grounded in the wrong 2%". **This run confirms that prediction live,
on a real repository, for the first time.**

The `github/docs` case is the control that proves the point is about *ranking*, not about
partial coverage as such: it read 1.8% and still characterised the repository correctly,
because `github/docs` is docs-shaped all the way down, so an alphabetical slice happens to
be representative. `psf/requests` is not, and the alphabetical slice is its CI shell.

**The fix already exists in the codebase.** `core/summarization.py:rank_chunks` ranks
*chunks* for the prompt by how much they explain a repository — README first, shallow
before deep, `docs/` ahead of `.github/`. Nothing equivalent ranks *files* for reading. The
cap should select files the same way, at which point the capped `psf/requests` run would
read `README.md` and `src/requests/` rather than the issue templates.

#### Rubric

Scored on the same five dimensions as Run 7.

| Case | Grounding | Coverage | Clarity | Honesty | Usefulness | Mean |
|---|---|---|---|---|---|---|
| capped `psf/requests` | 4 | 2 | 5 | 3 | 2 | **3.2** |
| large partial `github/docs` | 5 | 4 | 5 | 5 | 5 | **4.8** |
| sparse `Hello-World` | 5 | 5 | 5 | 5 | 4 | **4.8** |
| full code `psf/requests` | 5 | 5 | 5 | 4 | 5 | **4.8** |

Notes on the scores that are not 5:

- **capped, Grounding 4** — the opening characterisation of the library came from metadata
  rather than from anything read, stated without that distinction.
- **capped, Coverage 2 / Usefulness 2** — as a description of the 20 files read it is
  complete; as a description of `psf/requests` it is wrong. Usefulness is scored against
  what a reader needs, and a reader needs to know this is an HTTP library.
- **capped, Honesty 3** — the disclosure was exact and up front, which is worth a lot; the
  unqualified generalisation that followed is what costs it.
- **large partial, Coverage 4** — correct about the shape, necessarily thin on specifics
  at 1.8%.
- **sparse, Usefulness 4** — there is nothing useful to say about this repository, and it
  says so quickly and truthfully, which is the best available outcome.
- **full code, Honesty 4** — exact on the 20 dropped chunks, but "several non-text and
  unsupported files" where the provenance says 7 and 16.

#### Limitations of this run

- **One model.** All five live summaries to date are `gemini-3.5-flash-lite`. Nothing
  compares against `gemini-3.7-flash`, and the model is configurable, so a reader may be
  running one no run has evaluated.
- **The 429 was not deliberately provoked** and its exact quota was not inspected — the
  retry cleared it and the run continued, which is the designed behaviour. It confirms the
  retry path works live; it does not measure the per-minute limit.
- **Truncation remains mock-only.** `github/docs` at 14,903 entries was still not truncated
  by GitHub.
- **No `no_content` or `provider_error` summary was generated live** in this run; both are
  covered by tests and by Run 7's `not_configured` analyse step.


---

### Run 9 — 2026-08-18: the same capped case, rank-ordered (the Run 8 finding, fixed)

- **Quota, GitHub:** authenticated, 5000/hour. `/rate_limit` read `used 44, remaining 4956`
  both before and after — stale again, as in Runs 1, 7 and 8. True cost: 22 calls.
- **Quota, Gemini:** **one** request, on `gemini-3.5-flash-lite`. No retry was needed; the
  first attempt returned 200 in 4.5 s.
- **Purpose:** repeat the Run 8 `capped` case with **only the file ordering changed**, and
  see whether the summary describes an HTTP library rather than a CI configuration.
- **Method:** identical to Run 8 — `psf/requests`, `REPOBRIDGE_MAX_FILES_PER_RUN=20`,
  in-process `TestClient`, scratch database, provider key withheld during analysis and
  restored only for `POST /api/runs/{id}/summarize`.

#### What the cap chose, before and after

Same repository, same cap, same 107 selected files. The only difference is
`core/ranking.py:rank_files`, applied in `fetch_and_extract` before the cap splits.

| | Run 8 (tree order) | Run 9 (rank-ordered) |
|---|---|---|
| `README.md` | **not read** | **read, first** |
| `src/requests/` files | **0** | **3** (`__init__.py`, `__version__.py`, `_internal_utils.py`) |
| `docs/` files | 0 | 4 (`index.rst`, `api.rst`, `dev/contributing.rst`, `requirements.txt`) |
| `.github/` files | **18 of 20** | **4 of 20** |
| other | `.coveragerc`, `.git-blame-ignore-revs` | `AUTHORS.rst`, `HISTORY.md`, `ext/LICENSE`, `requirements-dev.txt`, 4 × `tests/` |

The full Run 9 selection, in the order the cap took it:

```
README.md                      docs/api.rst                 src/requests/__init__.py
AUTHORS.rst                    docs/dev/contributing.rst    src/requests/__version__.py
HISTORY.md                     docs/index.rst               src/requests/_internal_utils.py
requirements-dev.txt           docs/requirements.txt        tests/__init__.py
ext/LICENSE                    .github/AI_POLICY.md         tests/certs/README.md
.github/CODE_OF_CONDUCT.md     .github/CONTRIBUTING.md      tests/certs/expired/README.md
.github/ISSUE_TEMPLATE.md                                   tests/certs/mtls/README.md
```

#### The summary

> "This repository contains Requests, a simple and elegant HTTP library for Python built for
> human beings. It allows developers to send HTTP/1.1 requests easily with features like
> automatic connection pooling and keep-alive, sessions with cookie persistence,
> browser-style TLS/SSL verification, basic and digest authentication, multipart file
> uploads, SOCKS proxy support, and automatic content decompression.
>
> The repository is organised around a core source directory containing the main Python
> modules, a documentation directory containing reStructuredText files, and a test suite
> with testing certificates and configuration. It also includes community and contribution
> guidelines, an AI usage policy, issue templates, and a detailed release history.
>
> Coverage of this repository is partial. Out of 153 total entries and 107 selected text
> files, only 20 files were read for this analysis, while 87 selected files were skipped due
> to run limits, alongside non-text assets and unsupported extensions."

**The Run 8 defect is gone.** The phrase "heavily structured around GitHub infrastructure"
does not appear; neither does "GitHub infrastructure" or "automation" in any form. The
repository is described as what it is.

Provenance is unchanged in shape from Run 8's capped case — `read 20 of 107 selected files`,
`is_partial: true`, the same two limitations — because ranking changes *which* 20, never how
many. `accounts_for_every_selected_file` was `true`: `107 == 20 + 0 + 87`.

#### Mechanical audit

Same method as Runs 7 and 8: the prompt was reconstructed from the database
(`rank_chunks` + `select_within_budget` are deterministic) and matched the recorded
`chunks_included` and token count exactly — 20 of 20 chunks, 27,659 tokens.

| Check | Result |
|---|---|
| Substantive claims traced to what the model saw | **17 of 17** |
| Unsupported claims | **none** |
| Filenames asserted by the summary | **none** — so no risk of naming an unread file |
| Provenance numbers stated verbatim in the prose | **4 of 4** (153, 107, 20, 87) |

Every feature it lists — connection pooling, keep-alive, cookie-persistent sessions,
browser-style TLS/SSL verification, basic and digest auth, multipart upload, SOCKS proxies,
automatic decompression — appears in `README.md`, which the ranking put first and which
Run 8 never read. It describes `src/requests/` as "a core source directory containing the
main Python modules" **without naming a module it did not read**, having seen only three of
them. That restraint is the criterion "no summary claims about unseen files" behaving
correctly under partial coverage.

Run 8's capped summary stated three of the four provenance figures and omitted the 87;
Run 9 states all four.

#### One regression, recorded

**The coverage paragraph moved to the end.** In Run 8 it was the opening sentence; here it
is the closing one. `SYSTEM_INSTRUCTIONS` rule 3 asks for it "near the start", so this is a
deviation, not a preference. The information is complete and more precise than before, and a
reader who stops early now gets the ungrounded impression the disclosure exists to prevent.
Not judged a blocker — the disclosure is present, exact, and in a three-paragraph summary
the reader will reach it — but it is the single thing most worth watching if summary
placement is ever tightened.

#### Rubric

| Case | Grounding | Coverage | Clarity | Honesty | Usefulness | Mean |
|---|---|---|---|---|---|---|
| Run 8 capped `psf/requests` | 4 | 2 | 5 | 3 | 2 | **3.2** |
| **Run 9 capped `psf/requests`** | **5** | **4** | **5** | **4** | **5** | **4.6** |

- **Grounding 5** — 17 of 17 claims traced; the tagline now comes from `README.md`, which
  was read, rather than from the GitHub metadata description as in Run 8.
- **Coverage 4** — the library, its features, and the top-level layout, from 19% of the
  files. Not 5 because no specific module is characterised, which is correct behaviour
  rather than a flaw, but it is still less than a full-coverage reading gives.
- **Honesty 4** — all four figures exact; docked one for the placement regression above.
- **Usefulness 5** — a reader learns that this is an HTTP library and what it does.

#### Limitations of this run

- **One repository, one cap, one model.** The ranking is verified live on the case that
  exposed the defect; `github/docs` at 200 was measured offline against its stored file list
  (spread across `content`, `src`, `data`, `.github`, root) but was **not** re-summarised
  live, because that would have cost a request to re-confirm a case that already passed.
- **Within an area the order is still path-based.** The three `src/requests/` files read are
  `__init__.py`, `__version__.py` and `_internal_utils.py` — the underscore-first ones, not
  `api.py` or `sessions.py`. `__init__.py` is a genuinely good pick for a Python package and
  that is luck, not design.
- **Equal round-robin over-weights small peripheral areas.** Four `.github/` files and four
  `tests/` files in a 20-file budget is more than either area deserves, and three of the four
  `tests/` files are certificate-directory READMEs.
