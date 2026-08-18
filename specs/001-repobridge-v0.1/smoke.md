# RepoBridge v0.1 Smoke Suite

The repeatable smoke list `evals.md` asks for under "Recommended smoke test suite", with the
fields it names recorded per run.

Purpose: close plan.md Milestone 2 validation item V1 — "use a small set of sample public
repos for smoke tests" — with recorded outcomes rather than a single ad-hoc check.

---

## Current state

Latest recorded result per repo. The run log below is the historical record; this table is
the answer to "where do we stand". Update it whenever a run is added.

| Repo | Latest run | Date | Entries | Selected | Skipped | Rows stored | Leading skip reason |
|---|---|---|---|---|---|---|---|
| `kubernetes/kubernetes` | Run 5 | 2026-08-18 | 37393 | 8376 | 22924 | 37393 | `unsupported_extension` (17167) |
| `github/docs` | Run 4 | 2026-08-17 | 14901 | 11215 | 2227 | not stored | `non_text_asset` (1814) |
| `twitter/twemoji` | Run 3 | 2026-08-17 | 7413 | 17 | 7389 | not stored | `non_text_asset` (7378) |
| `psf/requests` | Run 5 | 2026-08-18 | 153 | 107 | 23 | 153 | `unsupported_extension` (16) |
| `Pushkar0997/quantum-toybox` | Run 5 | 2026-08-18 | 40 | 30 | 0 | 40 | — (nothing skipped) |
| `octocat/Hello-World` | Run 4 | 2026-08-17 | 1 | 1 | 0 | not stored | — (nothing skipped) |
| `Pushkar0997/definitely-not-a-real-repo-zzz` | Run 1 | 2026-08-17 | — | — | — | — | 404 at metadata, as intended |

Every repo in the suite has been classified. "Rows stored" reads *not stored* for repos last measured
before persistence existed (Runs 3 and 4) — their classification figures are still valid, they
simply predate the database.

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

---

## How to run

Each repo costs **two** GitHub calls (metadata + tree); a nonexistent repo costs one, because
it fails at the metadata step. A full pass is ~13 calls.

**A token is strongly recommended.** Without `REPOBRIDGE_GITHUB_TOKEN` set you are on the
unauthenticated 60/hour per-IP quota, which a full pass will exhaust if anything else has used
it — that is exactly what happened during the first attempt at Run 1, recorded below. With a
token the quota is 5000/hour. **Runs 1 through 5 were all authenticated at 5000/hour.**

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
