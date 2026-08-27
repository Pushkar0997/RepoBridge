# RepoBridge — Orchestrator Handoff

**Purpose of this document.** RepoBridge was built across a long conversation between
Pushkar Kumar (the owner) and an orchestrating LLM, which wrote slice prompts for a
coding agent (Claude Code) working directly on the repository. The repo's own
`specs/` directory records *what* was built and *what was decided*. This document
records *how the work is done* and *why the decisions were made* — context that
exists nowhere in the code.

Read this first if you are an LLM picking up orchestration duty in a fresh
conversation. Read the repo docs second. Do not start proposing work until you have
read both.

**Status when written:** v0.1 complete, tagged, and deployed at
`https://repobridge.pushkarkumar.me`. A feedback round with friends, seniors and
working engineers is in flight. v0.2 direction is drafted but deliberately not
committed to, pending that feedback.

---

## 1. What RepoBridge is

A local-first tool that turns a public GitHub repository into grounded, traceable
context for LLMs.

The problem it exists to solve: ask most AI tools about a GitHub repository and they
either cannot fetch it, read only the README, or produce a confident summary
assembled from training-data priors without saying what they actually read. The
output looks identical either way. A reader cannot distinguish an informed summary
from a plausible one.

RepoBridge's central promise is **accountability**: every file GitHub reports is
accounted for, every omission carries a reason, and every summary states what it was
built from.

That promise is not a feature. It is the product. Every architectural decision in the
codebase traces back to it, and any future work that weakens it is a regression even
if it ships more capability.

---

## 2. Current state — precise

| | |
|---|---|
| Version | v0.1.0, tagged |
| Tests | 696 passing |
| Milestones | 11 of 11 closed, each with a recorded verdict in `evals.md` |
| Smoke runs | 12 recorded in `smoke.md` against real repositories |
| Deployment | Railway, `repobridge.pushkarkumar.me`, shared demo mode |
| Repo visibility | **Private** |
| Licence | All Rights Reserved (unchanged; decision deliberately deferred) |

**Pipeline, end to end:** URL validation → repo metadata → file tree → classification
of every entry → ranked, capped content reads → text extraction (notebooks flattened
cell by cell) → grounded summary via Gemini → diagnostics timeline → persistence.

**Surfaces:** REST API and a server-rendered web UI (analyze form, recent runs with
filters, run detail with summary and provenance, file listing with status/reason/path
filters, diagnostics timeline).

**Stack:** Python, FastAPI, SQLAlchemy + aiosqlite, Jinja2, hand-written CSS/JS,
Google Gemini for summarisation, pytest. No frontend framework, no build step. That
constraint held for all eleven milestones and should be treated as load-bearing
rather than incidental — it is why the project has no toolchain rot and why a fresh
agent can read the whole UI.

---

## 3. The repo documents and what each is authoritative for

Located in the repository. **These are authoritative over anything in this document
or in any conversation.** If they disagree with a summary, the documents win.

| File | Authoritative for |
|---|---|
| `AGENTS.md` | The project constitution. Engineering standards, AI-assisted development rules, quality gates. Read first, always. |
| `specs/001-repobridge-v0.1/spec.md` | What v0.1 is: goals, non-goals, inputs, outputs, requirements, architecture. Carries dated amendments. |
| `specs/001-repobridge-v0.1/plan.md` | Milestone structure and deliverables. Carries the scope-split amendment and deferred design items. |
| `specs/001-repobridge-v0.1/tasks.md` | Task breakdown per milestone. |
| `specs/001-repobridge-v0.1/evals.md` | Acceptance criteria and **recorded verdicts** for every milestone. |
| `specs/001-repobridge-v0.1/selection.md` | File selection rules: supported types, skip-reason enum, precedence order, amendment history. Split out of `spec.md` when it outgrew a subsection. |
| `specs/001-repobridge-v0.1/smoke.md` | Live run log with a summary index. Twelve runs. |
| `README.md` | User-facing: what works, every endpoint, environment variables, honest limitations. **Kept honest by tests that read `app.openapi()` and fail in both directions if code and README drift.** |

**Amendment convention.** When scope or a decision changes, it is recorded as a
**dated amendment** in the relevant file — what changed, why, and the measurement or
event that prompted it. Criteria are never deleted; when a milestone is split,
criteria move intact to the new milestone. This has happened four times. Preserve the
convention.

---

## 4. How the work is done — the process that produced this

This matters more than any individual decision. The process is why the project has
696 tests instead of 40, and why a mid-project context reset was a non-event.

### 4.1 The slice loop

1. The orchestrator writes a **single slice prompt** — one coherent unit of work,
   scoped tightly, with the reasoning behind each requirement stated so the agent can
   push back rather than comply blindly.
2. Claude Code executes and reports: a diff, real verification output, and a
   **"found, not fixed"** list of everything else it noticed.
3. The orchestrator reads the output critically, decides which found-not-fixed items
   to take now versus record versus ignore, and writes the next prompt.
4. **Pushkar commits.** The agent never touches git.

### 4.2 The standing constraints given to Claude Code

Every slice prompt includes these. Do not drop them.

```
- Do NOT run git add, git commit, git push, or any mutating git command.
  Read-only git is fine.
- Change only what the slice covers. List anything else you find without fixing it.
- Live API calls are expensive: the Gemini free tier allows ~500 requests/day on
  gemini-3.5-flash-lite (20/day on quality Flash models). Verify live ONCE at the end
  of a slice, deliberately. Never probe or iterate against a live API — reproduce
  problems with mocks.
```

The git constraint exists so Pushkar sees every change before it lands and stays in
the loop rather than rubber-stamping automation. The live-call constraint exists
because an early session burned an entire day's Gemini quota on diagnostic probing.

### 4.3 The fresh-session preamble

When starting a new Claude Code session:

```
Fresh session on the RepoBridge project. Read AGENTS.md first, then
specs/001-repobridge-v0.1/ — spec.md, plan.md, tasks.md, evals.md, selection.md and
smoke.md. Those carry the full project state: eleven closed milestones with recorded
verdicts, several dated amendments, and twelve live smoke runs. Do not assume
anything about the project that is not in those files or the code.

[standing constraints]

[the slice]
```

This has been tested. A session died mid-milestone; a fresh session read the specs,
correctly assessed 85%-complete uncommitted work, and found four defects the dead
session had shipped. The documentation is the handoff mechanism and it works.

### 4.4 The rules that kept quality high

- **A milestone closes only when every criterion is backed by a test or a recorded
  live result.** Not by inspection, not by "it obviously works."
- **Never round up a PARTIAL.** M6 was held open twice. The second time, the agent
  itself refused to close it because the grounding property had only been
  demonstrated on the easiest input in the suite. That refusal produced the project's
  most valuable finding (§6.1).
- **Audit before continuing** when picking up unknown state. Ask for an assessment
  and an explicit *stop* before any code is written.
- **Measure before implementing** when a design choice is contested. The file-ranking
  fix was preceded by a measurement showing that the obvious approach (reuse the
  chunk-ranking signals) would not have worked.
- **Fix the cause, not the symptom.** When tests wouldn't collect, the fix was
  `pip install -e .`, not a `sys.path` hack in `conftest.py`.
- **Commit when a slice is green.** Chaining slices before committing was a mistake
  made repeatedly in this project; it makes rollback expensive and makes progress
  feel invisible.

### 4.5 Commit message convention

Multi-line, stating what changed *and why*, including negative results. Written via a
PowerShell here-string to avoid quoting problems:

```powershell
@'
Milestone N: short description

- Bullet stating a change and the reasoning behind it
- Bullet recording something that did NOT work, if applicable

Suite: X tests -> Y.
'@ | Out-File -Encoding utf8 commit-msg.txt

git add .
git commit -F commit-msg.txt
Remove-Item commit-msg.txt
git push
```

`commit-msg.txt` is gitignored.

---

## 5. Decisions already made — do not relitigate without new information

Each of these was argued and recorded. A fresh orchestrator proposing the opposite
without new evidence is wasting the owner's time.

| Decision | Reasoning |
|---|---|
| **Per-file contents API, not tarball** | `spec.md` §7.4 names it, and per-file HTTP status is load-bearing for the `selected == read + failed + not_fetched` identity. A tarball would download everything to read a subset, and lose per-file error granularity. The cap neutralises the tarball's only advantage. |
| **Read cap, rank-ordered** | Uncapped fetching costs 11,215 calls on `github/docs`. Cap default 200 local / 100 shared. Ranking is required, not optional — see §6.1. |
| **Gemini over Groq** | Groq's free tier is ~6–12K tokens/minute; a single repo-summary prompt is ~17K. Wrong tool, not a tuning problem. |
| **Requests-per-day is the binding constraint** | Not tokens. Quality Flash models allow 20/day; Flash Lite allows ~500/day. This drives the default model choice and the shared-instance rate limits. |
| **Google free tier trains on prompts — recorded as a *blocking prerequisite*** | Acceptable only because v0.1 is public-repos-only. **Private repo support must move to a paid tier with training disabled, or a different provider, before the first private repository is read.** This is the single most important constraint on the roadmap. |
| **No token or key as a request field** | Environment only. A per-request secret would flow into persistence, diagnostics and logs. Also matches how MCP servers receive secrets. |
| **No Alembic for v0.1** | Every stored row derives from a public repo and regenerates on re-run, so a reset costs quota, not information. What was hardened instead is the *failure*: a stale database names the file path and the policy. Revisit when data becomes unreproducible. |
| **No API version prefix** | A prefix is a promise v0.1 cannot keep — the schema moved four times and M8 rewrote every error body. Shipping `/v1/` and breaking it is worse than not shipping it. A test fails if a prefix appears without the README changing. |
| **Logs cover process facts only** | Diagnostics explain a *run*. Per-module logging hooks would create a second narrative of the same run that drifts from the timeline — the exact failure diagnostics was built to prevent. |
| **`/api/runs/{id}/tree` deliberately not built** | The tree *is* the classified entries; `/files` already serves them with filtering and pagination. Two contracts for one fact is worse than one. |
| **No adapter abstraction for LLM providers** | One provider, isolated in one module. The interface should be designed against real usage, not guessed at in advance. |

---

## 6. The findings that matter

### 6.1 The `psf/requests` finding — the most important result in the project

The read cap originally took the alphabetically-first N files.

`psf/requests` capped at 20 read **18 files from `.github/`** and no source at all.
README and every module of `src/requests/` went unread. The summary described the
project as *"heavily structured around GitHub infrastructure and automation."*

Every individual fact was grounded. No unread file was named. It violated no rule in
the system instructions. And it was **materially wrong** about what one of Python's
most-used libraries is.

The control made it rigorous: `github/docs` read **1.8%** of its selected files and
got the repository right — because a docs site is docs-shaped throughout, so an
alphabetical slice is representative. Same machinery, same disclosure, opposite
outcome. **The variable was never the summariser; it was which files the cap chose.**

The failure mode had been predicted five milestones earlier and recorded in `plan.md`
as an open item: a summary "grounded in the wrong 2%."

The fix required a distinction that is easy to miss: **chunk ranking orders content
already read**, so every area is in the pool and sorting only decides what comes
first. **File ranking decides what is read at all**, so an area the cap never reaches
is absent from the evidence entirely. Reusing the chunk signals alone still read zero
`src/requests/` files — it just moved the concentration from `.github/` to `docs/`.
The working fix was ranking **plus a round-robin across top-level areas**.

Re-run at the same cap of 20, it now opens: *"This repository contains Requests, a
simple and elegant HTTP library for Python built for human beings."*

The old ordering is pinned as a regression test.

**Why this matters for future work:** grounded-but-unrepresentative is a distinct
failure mode from hallucination, it is invisible to per-claim verification, and any
future sampling decision (language coverage, chunk budgets, MCP tool responses) can
reintroduce it.

### 6.2 The founding audit

The project began by auditing a claim that a milestone was complete. The audit found
`pytest` collected **zero** tests due to an import error, and the milestone was
roughly one third done. Everything since has been built on: *a claim without evidence
is not a claim.*

### 6.3 Other findings worth carrying

- **Connection pooling: 99.6s → 7.5s** on a 107-file extraction (13.3×), identical
  call count. Bounded concurrency alone bought only 2×; the bottleneck was a fresh
  TCP+TLS handshake per file.
- **GitHub's `/rate_limit` endpoint is stale** — measured reporting figures 17 calls
  behind reality. Per-response headers are authoritative. Do not build quota displays
  on `/rate_limit`.
- **Gemini's daily-quota 429 advertises a misleading ~58s `retryDelay`** when the
  real reset is at the day boundary. Detected and failed fast rather than burning a
  retry budget against a wall it cannot clear.
- **A one-file repo summary declined to characterise the project** — *"it is not
  possible to further characterise the repository or its organisation"* — with
  nothing mechanically forcing that caveat.
- **65 claims across six live summaries audited mechanically** against the chunks the
  model actually saw (the prompt is deterministically reconstructible). Zero
  hallucinated files.

---

## 7. Defect patterns this project has hit repeatedly

A fresh orchestrator should watch for these; each occurred more than once.

**Definition-time binding.** A function default evaluated at import silently ignores
runtime configuration. Hit twice: the M5 extraction cap (`cfg=DEFAULT_CONFIG`) and
the M6 summarisation config. Both would have made an environment variable a no-op.

**Tests that assert nothing.** Three instances: a test constructing its own
`Recorder` and asserting on it (a tautology); `install_transport` silently ignoring a
second handler so any two-handler test tested the wrong thing; and
`tests/test_end_to_end.py` sitting **empty** while named in two milestones' task
lists — a filename that read as coverage for five milestones.

**A case that is two things at once, tested one at a time.** Hit twice in consecutive
milestones. M7's diagnostics banner handled partial *or* degraded but not both, so a
run with 81% of files unread announced only "completed with failures." M9's run
detail said a repository "never resolved" while printing its default branch four rows
below. Both were found by live walkthroughs, not by the suite.

**A field that asserts a stage that did not run.** `resolved_ref` named a ref the
tree call never confirmed. `tree_error` held a metadata failure that never attempted
a tree. Both fixed; the pattern recurs wherever a value is set optimistically.

**Stale documents.** The README claimed extraction, summaries and diagnostics were
"not built yet" two milestones after they shipped. Now guarded by conformance tests.
`spec.md` §9 and §10 predated the milestones they described. The lesson: when code
and spec disagree, **make them agree** — do not silently follow either.

---

## 8. Open questions — the forks that need deciding

### 8.1 The pivot (see `PRODUCT.md` and `specs/002-repobridge-v0.2/`)

Three candidate directions, ranked by the orchestrator's current read:

1. **MCP server** — strongest. Nothing equivalent exists. Architecturally close: the
   API is already the tool surface and provenance is already structured. Inverts the
   quota problem, since the user's client brings its own model.
2. **Language coverage** — a prerequisite, not a pivot. Kubernetes reports 17,167
   files as `unsupported_extension` because Go is out of scope. Any Go developer who
   tries the demo concludes it does not work, because for them it does not.
3. **Multi-user SaaS** — most work, least validated. Every hard part is a hard part
   of any SaaS and none is RepoBridge-specific. Hold until someone asks to pay.

**This ranking is the orchestrator's opinion formed inside a long conversation with
the owner, and should be treated with suspicion accordingly.** The feedback round is
the check on it.

### 8.2 What the feedback should decide

| If testers say | Then |
|---|---|
| The coverage disclosure is what they'd miss elsewhere | MCP, immediately |
| They shrug at provenance but like the file inventory | This is a repo browser, a different product |
| "Can I point this at my work repo?" | Private repos, and the provider question becomes urgent |
| Nothing at all | Take that seriously rather than explaining it away |

The questions being asked: *"Paste a repo you know well. Would the summary have
misled you about what that project is?"* and *"Did you notice what it said about how
much it read? Did you care?"*

### 8.3 Standing open items

- **Licence.** Currently All Rights Reserved, chosen when the direction was
  unsettled. The orchestrator's recommendation was Apache-2.0 (MIT-like adoption plus
  a patent grant). **The owner has not decided and this is his call. Do not implement
  a licence change.** Note also that the README's own "private and proprietary"
  status line deters adoption more than the licence does; the two should agree.
- **Repo visibility.** Private. Deployment does not require publishing.
- **`CREDENTIAL_LIKE` skip reason.** Recorded in `plan.md`, not built. `.pem`/`.key`/
  `.crt` currently skip as merely `unsupported_extension`. Cannot land before content
  is available, since distinguishing a test fixture from a real secret needs the file.
- **No retention or delete.** Re-analysing the same repo ten times stores ten copies.
- **`chars // 4` token estimate**, not a tokenizer. Under-counts code.
- **Truncation is mock-only.** GitHub did not truncate even at 37,393 entries; the
  threshold is ~100k.
- **The shared instance is unauthenticated**, so anyone with the URL can call
  `POST /api/analyze` directly. Rate limits apply at the endpoint, but there is no
  other barrier. Recorded in `plan.md` Milestone 10.5 as a consequence.
- **The Dockerfile has never been built.** Static consistency tests cover the class of
  failure, but the image itself is untested.

---

## 9. Deployment — current posture

**Shared demo, not multi-user.** One instance, the operator's keys, one database
visible to every visitor. Recorded in `plan.md` as Milestone 10.5, deliberately
interim.

Environment variables on the host:

```
REPOBRIDGE_DEPLOYMENT=shared
REPOBRIDGE_STORAGE=ephemeral
REPOBRIDGE_GITHUB_TOKEN=...
REPOBRIDGE_GEMINI_API_KEY=...
REPOBRIDGE_GEMINI_MODEL=...       (optional; defaults to a Flash Lite model)
```

**Rate limits and their arithmetic** — this is a worked constraint, not a guess:

```
instance   20 analyses/hour     client  5 analyses/hour
max repo   5,000 tree entries   read cap 100 files (shared) / 200 (local)

per analysis    2 + 100 = 102 GitHub calls, 1 Gemini request
saturated hour  20 x 102 = 2,040 GitHub  -> 41% of 5,000/hour
saturated day   20 x  24 =   480 Gemini  -> inside ~500/day
```

The instance limit is set by **Gemini, not GitHub** — an hourly limit cannot
otherwise bound a daily quota. `test_the_shared_defaults_fit_both_quotas` recomputes
this from the shipped values and fails naming the quota exceeded. **If you change any
of the four numbers, rebalance; do not loosen the test.**

Limits are per-process and reset on restart; run a single worker. Per-visitor
identity is a client-controlled header — a fairness measure between honest testers,
not a security control.

---

## 10. How to orchestrate a slice — template

```
[Fresh-session preamble if the session is new]

Same constraints: no git add/commit/push, change only what's below, list anything
else you find without fixing it.

[Live-call budget statement]

Read AGENTS.md and the relevant sections of spec.md, plan.md, tasks.md and evals.md.
Those are authoritative. If they disagree with what was built, report the divergence
rather than silently following either.

SLICE: [one coherent unit of work]

[Numbered requirements. State the REASONING behind each, not just the instruction —
the agent has caught orchestrator errors several times when given the reason.]

[If a design choice is contested: ask it to MEASURE before implementing, and to
defend the choice in its output.]

[If honesty-critical code is touched: name the properties that must survive, and say
that a failing test is the guardrail working rather than an obstacle.]

TESTS: [what must be covered, especially combined conditions]

VERIFY: full pytest. [Any live verification, budgeted explicitly.]

OUTPUT: diff, verification, [any decision you want defended]. Then stop.
```

**Reading the response.** Look hardest at: whether it judged against the spec files or
its own assumptions (if it never quotes them, push back); whether verification is real
output or assertion; whether the found-not-fixed list contains something that
invalidates the slice; and whether any test could pass while asserting nothing.

**Two things the agent has done well and should be encouraged to keep doing:**
correcting the orchestrator when the stated reasoning is wrong (it has been wrong
about pytest-asyncio behaviour, about which file contained a bundling problem, and
about a verification command that would have passed on a broken app), and refusing to
close milestones on insufficient evidence.

---

## 11. About the owner

Second-year B.Tech student. This is his largest project. He is capable and moves
fast, and the main failure mode to guard against is not under-ambition — it is
building further before validating demand.

Two things worth remembering when orchestrating:

- He asked, mid-project, whether the work was actually useful. The honest answer given
  was that RepoBridge may or may not find users, but has already succeeded at
  demonstrating he can build software properly, and that those are separable. That
  remains true and is worth saying plainly if it comes up again.
- The orchestrator in this conversation has been agreeing with him for eleven
  milestones. Some of that is warranted; some is the shape of these conversations.
  A fresh orchestrator should feel free to disagree, and should say so when the
  evidence is thin.
