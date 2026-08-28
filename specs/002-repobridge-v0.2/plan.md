# RepoBridge v0.2 — Plan

**Status: draft, gated on M0.** Sequential. Do not start M(n+1) before M(n)'s exit
criteria are met.

**Currently active: M0.**

Exit criteria are written to be checkable by someone who did not do the work. If a
criterion needs the author to explain it, it is not a criterion yet.

Everything in `specs/001-repobridge-v0.1/` remains authoritative for existing
behaviour. `CONTRACT.md` outranks this file.

---

## M0 — Reconcile with feedback ⏱ days · cost: 0

**Why first:** every milestone after this assumes the accountability guarantee is what
users value. That is a hypothesis, and it is currently being tested. Building on it
before it returns is the most expensive mistake available.

**Deliverables**
- Feedback collected verbatim, in `specs/002-repobridge-v0.2/feedback.md`
- A written answer to: **did anyone notice or care about the coverage disclosure?**
- A dated amendment to `spec.md` recording what the feedback established
- A go / re-scope decision

**Exit criteria**
- [ ] `feedback.md` exists and contains what people actually said, not a summary that
      agrees with the plan
- [ ] The disclosure question is answered yes / no / mixed, with the quotes that
      support it
- [ ] `spec.md` carries a dated amendment naming what changed and what did not
- [ ] If the answer was no or mixed, the scope of M2–M4 has been revisited in writing

**Risk:** nobody replies. That is data, not an absence of data — record it as such
and treat "the guarantee did not motivate anyone to respond" as a finding.

**Anti-goals for this stage** — things that will feel productive and are not:
- Adding languages, MCP tools, or any feature while M0 is open
- Polishing the UI
- Re-reading the code looking for something to improve

---

## M1 — Language coverage ⏱ 1 week

**Why now:** nobody will use an MCP server that cannot read their repository.
`kubernetes/kubernetes` currently reports 17,167 files as `unsupported_extension`. A
Go developer trying RepoBridge concludes it does not work, correctly.

**Deliverables**
- Extended supported-extension set in config
- `selection.md` amendment: each addition with its prompting measurement, each
  deliberate exclusion recorded as a decision rather than left as an omission
- Ranking re-measured on a repository in each newly-supported ecosystem
- Classification and extraction tests per new type

**Exit criteria**
- [ ] `kubernetes/kubernetes` classifies Go files as `selected`, and the accounting
      identity holds at 37,393 entries, recomputed from stored rows
- [ ] Three repositories from three newly-supported ecosystems are summarised live
      and recorded in `smoke.md`, with claims audited against the chunks sent
- [ ] For at least one of them, a **capped** run produces a summary that describes
      what the project is — checked the way `psf/requests` was, not by reading it and
      approving
- [ ] The full v0.1 suite passes unchanged
- [ ] Every extension in the new set appears in `selection.md` with a reason

**Risk:** widening the file set changes which files a capped run reads. CONTRACT I-5
applies directly. Re-measure ranking; do not assume it survives.

**Anti-goals**
- Language-specific parsers. Raw text first; structure only where measurement shows
  it improves summary quality
- Supporting every extension anyone might name. Each addition is a decision

---

## M2 — MCP server, core tools ⏱ 1–2 weeks

**Deliverables**
- MCP server exposing `analyze_repository` and `list_repository_files`
- Credentials from the client's MCP config
- The design questions in `spec.md` §6.2 decided, with reasoning in
  `specs/decisions.md`

**Exit criteria**
- [ ] A real MCP client connects and completes an end-to-end analysis — not a mock
- [ ] A filtered `list_repository_files` response states its unfiltered total, proven
      by test
- [ ] No credential appears in any tool response, log line, or error, proven by a
      value scan including 8-character fragments
- [ ] The REST API and web UI behave identically to before, proven by the unchanged
      suite
- [ ] Each §6.2 question has a decision entry naming what was rejected

**Risk:** the MCP path duplicating pipeline logic instead of reusing it. Two
implementations will drift and the drift will be silent.

**Anti-goals**
- Building all five tools before one works end to end
- An adapter abstraction over MCP transports

---

## M3 — MCP content and summary tools ⏱ 1 week

**Deliverables**
- `get_file_content`, `get_repository_summary`, `get_repository_diagnostics`
- Summarisation made optional, so a client with its own model spends no provider quota

**Exit criteria**
- [ ] `get_file_content` on a file that was skipped, not-fetched, or failed returns an
      explicit reason — never an empty result standing in for an explanation, proven
      per status
- [ ] `get_repository_summary` returns the provenance object alongside the prose
- [ ] A run with summarisation disabled completes, makes zero provider requests, and
      states why no summary is present
- [ ] **Adversarial check:** a deliberately partial result is handed to a client, and
      the response contains enough for the client to determine it was partial without
      knowing which field to look for
- [ ] Diagnostics ordering is stable across re-summarisation

**Risk:** a model receiving a partial tool result and reporting it as complete. This
is CONTRACT I-4 one layer up, and the client cannot be relied on to read a field it
was never told about.

**Anti-goals**
- A conversational layer over a repository
- Caching that could serve a stale inventory without saying so

---

## M4 — MCP hardening and documentation ⏱ 3–5 days

**Deliverables**
- Installation and configuration documentation for MCP clients
- Long-running-analysis behaviour settled and documented
- Error and timeout behaviour appropriate to a tool context

**Exit criteria**
- [ ] **Someone other than the author installs it from the documentation alone and
      reports where they got stuck.** This is the milestone's real test and cannot be
      self-administered
- [ ] A multi-minute analysis does not appear stuck to a client
- [ ] A failure returns something a model can act on, not a stack trace

**Risk:** documentation that assumes knowledge only the author has. The v0.1
clean-machine pass found four real defects by executing the README rather than
reviewing it; do the same here.

**Anti-goals**
- Writing docs from memory of how it works instead of from a clean run

---

## M5 — Release v0.2 ⏱ 2–3 days

**Deliverables**
- Recorded verdicts for M0–M4 in `evals.md`
- README and `smoke.md` updated
- Tag `v0.2.0`

**Exit criteria**
- [ ] Every M0–M4 criterion has a verdict row with the evidence that justifies it
- [ ] No criterion is marked PASS on inspection
- [ ] The clean-machine path is **executed**, not reviewed
- [ ] README conformance tests pass, including for the new MCP surface

**Anti-goals**
- Rounding up a PARTIAL to ship on a date

---

## Sequencing rules

- **M0 blocks everything.** It is cheap and it decides whether M2–M4 are the right
  work at all.
- M1 blocks M2: an MCP server that cannot read a Go repository is not worth shipping.
- M2 blocks M3: prove one tool end to end before adding four more.
- M4 cannot be self-administered. Budget for finding a second person.

## Deferred design items

Real questions, deliberately not scheduled. Recorded so nobody re-raises them as new
or "fixes" them by accident.

- **`CREDENTIAL_LIKE` skip reason** — `.pem`/`.key`/`.crt` skip as merely
  `unsupported_extension`, the blandest possible reason for the most interesting files
  in a repository. Cannot land before content is available; open question is false
  positives, since test fixtures and real secrets look identical by extension.
- **Chunk splitting** — one chunk per file except notebooks, so a 1 MB file is one
  ~250k-token chunk. `chunk_index` already exists, so adding splitting will not change
  the model.
- **Token estimate** — `chars // 4`, not a tokenizer. Under-counts code, so the risk
  is overspending the budget rather than being rejected.
- **Retention and delete** — ten analyses of one repository store ten copies.
- **Truncation is mock-only** — GitHub did not truncate at 37,393 entries; the
  threshold is ~100k.
- **The Dockerfile has never been built** — static consistency tests cover the class
  of failure; the image itself is untested.
- **Capability register** — the "not supported" facts are spread across
  `selection.md`, `spec.md` non-goals and gated work. A single register in
  `architecture.md` would stop an agent building on an imagined capability.

## Gated work

| Work | Gate — the condition that unblocks it |
|---|---|
| Private repositories | Summarisation moved off a provider tier that trains on submitted prompts. **Non-negotiable** — see `CONTRACT.md` and D3. |
| Multi-user, auth, billing | Someone asks to pay, or repeatedly hits the shared limits and asks for their own instance |
| Alembic migrations | A database holds data that cannot be regenerated by re-running |
| API version prefix | An external consumer exists to pin it — the MCP server is the likely trigger |
| Retention / delete | Storage growth becomes a real problem |

## Amendments

*When scope changes, record it here. Dated. State what moved, why, and what prompted
it. Criteria move intact — they are never deleted.*

*(none yet for v0.2)*
