# RepoBridge v0.1 Smoke Suite

The repeatable smoke list `evals.md` asks for under "Recommended smoke test suite", with the
fields it names recorded per run.

Purpose: close plan.md Milestone 2 validation item V1 — "use a small set of sample public
repos for smoke tests" — with recorded outcomes rather than a single ad-hoc check.

---

## How to run

No token is required. Each repo costs **two** unauthenticated GitHub calls (metadata + tree)
against a 60/hour per-IP quota, so a full pass costs ~11 calls. A nonexistent repo costs one,
because it fails at the metadata step.

```bash
python -m pytest -v
```

The suite itself is exercised in-process via FastAPI's `TestClient` against `POST
/api/analyze`; it does not need a running server.

Record for each repo: URL, outcome, file count, chunk count, summary quality notes,
diagnostics issues, manual observations — the fields `evals.md` specifies.

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
