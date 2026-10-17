# RepoBridge — Brief

*One page. Rewritten whenever state changes — a dashboard, not a maintained document.*

**What:** a local-first tool that turns a public GitHub repository into grounded,
traceable context for LLMs. It never claims to have read something it did not read.

## Where things stand

**v0.1 complete and tagged.** 11 milestones, 696 tests, 12 smoke runs.
**Live:** https://repobridge.pushkarkumar.me (shared demo, operator's keys)
**Repo:** private · **Licence:** All Rights Reserved (undecided)

**Current milestone: v0.2 M0 — reconcile with feedback. BLOCKING.**
A feedback round is out with friends, seniors and working engineers. Nothing in
v0.2 may start until M0 closes, because everything after it assumes the
accountability guarantee is what users value — and that is exactly what is being
tested.

The owner has requested a future hosted multi-user platform. A v0.3 discovery draft
now records the two modes, isolation and quota requirements, and free-tier blockers.
This is planning only: M0 remains open, and no implementation has started.

## Next action

Collect feedback verbatim. Answer one question in writing: **did anyone notice or
care about the coverage disclosure?** Record the answer as a dated amendment in
`specs/002-repobridge-v0.2/spec.md`, then decide go or re-scope.

## Copy-paste prompt for the next agent session

```
Read AGENTS.md, then CONTRACT.md, then specs/002-repobridge-v0.2/plan.md and
specs/001-repobridge-v0.1/evals.md. Then read the top 3 entries of AGENT_LOG.md.

Tell me which milestone is active, what closed most recently, and which task you
propose next. Do not write any code yet.
```

## The three things most likely to break

1. **Ranking, when the supported file set widens.** Adding Go/Rust/Java changes
   which files a capped run reads. `psf/requests` proved a capped summary can be
   factually perfect and materially wrong. Re-measure; do not assume.
2. **The shared instance's quota arithmetic.** Four numbers must keep summing inside
   both ceilings. A test enforces it — rebalance, never loosen.
3. **Combined-condition displays.** Twice, a run that was two things at once was
   announced as one. Both found by walking the system, not by the suite.

## Where everything else lives

| | |
|---|---|
| `CONTRACT.md` | what must never break — read before every task |
| `specs/001-repobridge-v0.1/` | shipped version: spec, plan, tasks, evals, selection, smoke |
| `specs/002-repobridge-v0.2/` | next version — draft, gated on M0 |
| `specs/003-repobridge-hosted-platform/` | future hosted workspaces — discovery draft, gated on M0 and free/security feasibility |
| `specs/decisions.md` | settled questions and their rejected alternatives |
| `AGENT_LOG.md` | what happened, newest first |
| `HANDOFF.md` | orchestrator context: how the work is run, and why |
