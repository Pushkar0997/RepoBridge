# Agent Log

Append-only. **Newest entry at the top.** Never edit a past entry — append a
correction as a new one. This is a history; `BRIEF.md` is the status page.

Archive entries older than the last two milestones into `docs/agent-log-archive.md`
once this passes ~50 entries. Do not delete.

## 2026-10-17 — Free storage candidates added to hosted-platform discovery

**Milestone:** v0.2 M0 — feedback gate; future v0.3 feasibility only
**Task:** record initial managed-storage candidates after checking primary provider
documentation
**Landed:** amended `specs/003-repobridge-hosted-platform/spec.md` and `plan.md` with
Neon Free as the leading compatibility candidate and Cloudflare D1 as an alternate
requiring runtime/storage redesign; recorded candidate status in D18
**Did not land:** no provider selected, no code, no deployment or account changes, no
tests

**Finding:** Neon Free's published Postgres allowance makes it worth a measured proof
against the existing SQLAlchemy path, but recovery, included transfer/compute, storage
exhaustion, and no-charge behavior still need verification. Cloudflare D1 has a more
significant integration gap: the app's maximum 102 GitHub calls is higher than the
Free Worker's 50 subrequests per invocation, and current database access uses
SQLAlchemy/aiosqlite rather than a D1 binding.

**Found, not fixed:** no datastore is selected; M0 feedback is still open; I-6 still
blocks request-supplied credentials; and free-tier limits, provider dashboard quotas,
data recovery, and billing controls remain to be verified before an implementation
decision.

---

## 2026-10-17 — Hosted-platform discovery amendment — v0.2 M0 remains blocking

**Milestone:** v0.2 M0 — feedback gate; future v0.3 platform discovery only
**Tasks attempted:** record the owner's request for optional Google sign-in,
per-user GitHub/Gemini keys and isolated workspaces, while preserving the active M0
gate; verify provider quota and free-hosting assumptions against primary vendor docs
**Landed:** D18 in `specs/decisions.md`; dated amendments in the v0.2 spec and plan;
draft v0.3 hosted-platform spec and sequential plan; `BRIEF.md` status pointer
**Did not land:** no code, contract relaxation, auth, tenant storage, credentials, or
deployment changes
**Blockers:** v0.2 tester feedback is still outstanding; `CONTRACT.md` I-6 still
prohibits request-supplied user keys; no durable $0 datastore has been selected

**Design recorded:** anonymous mode is an owner-key shared pool with hard global
budgets; signed-in users would have logically isolated workspaces and BYOK. A shared
tenant-scoped relational database is preferred over one physical database per user.
The draft does not promise durable storage on Render Free Postgres, which expires
after 30 days and has no backups. GitHub's standard authenticated REST limit is
5,000/hour/user; Gemini limits vary and are project-scoped, not key-scoped.

**Noticed, not fixed:** free-provider terms and quotas can change; existing v0.1/v0.2
quota assumptions still require revalidation before implementation. No durable free
storage provider has been selected, and the future credential flow still requires a
threat model and an explicit I-6 amendment. The M0 feedback question remains open.

**Tests:** not run; this slice changed specifications only.

---

## 2026-09-01 — Opus / chat — v0.2 final audit closure

**Milestone:** v0.2 final audit closure — close the remaining found-not-fixed items and verify the repo is still green
**Tasks attempted:** reconcile the remaining contract drift, secret/logging issues, refusal-handling gaps, stale docs, and repo-state cleanup; then run the full pytest suite
**Landed:** final fixes to `CONTRACT.md` and `specs/decisions.md` to match the code; enforcement of stored-row identity checks and run-loss prevention; secret redaction/log scanning for whole values and fragments; 413 repo-too-large refusal recorded as a failed run with a readable run_id; explicit docstrings in zero-byte stubs; stale `specs/002-repobridge-v0.2/plan.md` reference corrected; `repobridge.db` untracked and ignored state confirmed; repo-level audit closure summary recorded
**Did not land:** nothing in scope beyond the approved audit cleanup
**Blockers:** none; this was a final verification/scope closure pass

**Key corrections recorded in the repo:**
- I-1 identity was not a memory-only claim: stored-row recomputation and drift detection were enforced, with readback checks against the actual persisted rows.
- I-6's secrecy rule was made real: logs and rendered diagnostics were scanned for whole-value and fragment leaks, and redaction coverage was enforced.
- I-7's refusal rule was made real: a 413 repo-too-large rejection no longer disappears silently; it stores a failed run with the GitHub-confirmed counts and returns the run_id through the error details.
- The remaining empty placeholder modules were documented as intentionally not built rather than silently left as zero-byte stubs.
- The repo-state cleanup confirmed the DB is not tracked and the project is otherwise cleanly scoped.

**Tests:** final full suite verified at 710 passed, 1 warning, no test weakening or deletions.

**Noticed, did not fix:** no additional scope expansion beyond the above audit cleanup; the work remained constrained to the explicit contract and repo hygiene issues already identified.

---

## 2026-08-29 — Opus / Claude Code — v0.2 M0 (documentation slice)

**Milestone:** v0.2 M0 — reconcile with feedback (still blocking; this touched none of it)
**Tasks attempted:** verify `CONTRACT.md` and `specs/decisions.md` against the code;
build the capability register; then make `CONTRACT.md` true where it was not
**Landed:** `specs/001-repobridge-v0.1/capabilities.md` (new); `CONTRACT.md` and
`specs/decisions.md` corrected; three enforcement gaps closed in `src/`
**Did not land:** nothing in scope
**Blockers:** M0 itself, unchanged. Feedback still not returned.

**Correction to the entry below.** It records that "`AGENTS.md` predates the
metered-dependency problem and carries no budget clause". That was true when the
observation was made and false when it was committed — the same commit (`039f068`)
added the "Budget for metered dependencies" and "Found, not fixed" sections to
`AGENTS.md`. The gap is closed; the note is superseded, not deleted.

**Three claims in `CONTRACT.md` were false and were fixed by building the enforcement,
not by weakening the claim:**
- I-1's second identity (`selected == read + failed + not_fetched`) was checked in
  memory only. `storage.content_status_counts` existed with zero callers. Wired in as
  `stored_rows.stored_extraction_identity_holds`, with a drift test.
- I-6's "never a log line" was enforced by nothing, and `api/errors.py` documented
  unredacted tracebacks reaching the log. Three log paths now redact; five log scans
  added, all confirmed to fail without the fixes.
- I-7's "every attempt that reached GitHub leaves a stored trace" was violated by the
  413 size refusal, which spent two GitHub calls and stored nothing. Judged a defect,
  not an exception: it now stores a failed run carrying the `resolved_ref` and entry
  count GitHub confirmed. Reasoning in the slice output and in I-7 itself.

**Tests:** 696 → 710, all passing, no existing test weakened or deleted.

**Noticed, did not fix:** `storage.content_status_counts` was dead code for several
milestones; `api/routes_tree.py` and `infra/logging.py` are zero-byte files named for
things D8 and D7 say were deliberately not built; `core/input.py` uses 2-space indent
against 4 everywhere else; `limits.py`'s heading says "fixed window" over a sliding-log
implementation; `github/docs` is recorded as both 11,215 and 11,217 selected files
across four documents; `repobridge.db` is committed and ungitignored; `spec.md` §11 and
the README still call cloud/container deployment out of scope after M10.5 shipped it.

**Spec changes:** `capabilities.md` added and referenced from `CONTRACT.md`'s precedence
note and v0.2 `plan.md`. `decisions.md` gained D12–D17.

**Next action:** unchanged — v0.2 M0-01, collect feedback verbatim.

---

## 2026-08-28 — Opus / chat — v0.2 M0

**Milestone:** v0.2 M0 — reconcile with feedback (blocking)
**Tasks attempted:** adopt the spec-driven-development system on an existing project
**Landed:** `CONTRACT.md`, `BRIEF.md`, `AGENT_LOG.md`, pointer files,
`specs/decisions.md`, revised v0.2 `plan.md` and `evals.md`
**Did not land:** nothing — this was a documentation slice, no source changed
**Blockers:** M0 itself. Feedback has been sent and not yet returned.

**Noticed, did not fix:**
- `specs/001-repobridge-v0.1/` has no capability register in one place. The
  "not supported" facts are spread across `selection.md`'s deliberate-exclusion
  list, `spec.md` non-goals, and `plan.md` gated work. A single register would stop
  an agent building on an imagined capability.
- `AGENTS.md` predates the metered-dependency problem and carries no budget clause,
  though a session did burn a full day's provider quota on diagnostic probing.
- Licence and repo visibility remain undecided; the README's "private and
  proprietary" line deters adoption more than the licence does, and the two should
  agree.

**Spec changes:** v0.2 `plan.md` and `evals.md` restructured — anti-goals per
milestone, exit criteria phrased to be checkable by someone who did not do the work,
invariant and negative tests, and recorded-verdict tables.

**Next action:** v0.2 M0-01 — collect feedback verbatim and answer whether anyone
noticed the coverage disclosure. Start from
`specs/002-repobridge-v0.2/spec.md` §4.
