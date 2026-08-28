# Agent Log

Append-only. **Newest entry at the top.** Never edit a past entry — append a
correction as a new one. This is a history; `BRIEF.md` is the status page.

Archive entries older than the last two milestones into `docs/agent-log-archive.md`
once this passes ~50 entries. Do not delete.

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
