# RepoBridge v0.2 — Specification (DRAFT)

**Status: DRAFT, pending feedback.** v0.1 shipped, tagged and deployed. A feedback
round is in flight. This document proposes the v0.2 scope; Milestone 0 is to
reconcile it against what testers actually said.

**Do not begin Milestone 2 or later until Milestone 0 is complete and this document
has been amended with what the feedback established.**

Everything in `specs/001-repobridge-v0.1/` remains authoritative for existing
behaviour. This document adds; it does not supersede.

---

## 1. Premise

v0.1 proved the pipeline works and the accountability guarantee holds. Two things
prevent it from being usable by anyone other than its author:

1. **It cannot read most repositories.** Go, Rust, Java, Ruby, C++, C# and PHP source
   files are classified `unsupported_extension`. `kubernetes/kubernetes` reports
   17,167 such files. A developer in any of those ecosystems concludes RepoBridge
   does not work, correctly.
2. **It is a destination, not infrastructure.** The value — a provenance guarantee an
   LLM can check — is locked behind a web UI a person has to operate.

v0.2 addresses both, in that order, because the second is worthless without the first.

## 2. Goals

- **G1.** Read the languages a working engineer actually encounters.
- **G2.** Expose the pipeline as an MCP server so any MCP-capable LLM client can use
  RepoBridge as a tool.
- **G3.** Carry the accountability guarantee into the tool surface intact — every
  tool response must be self-describing about its own completeness.
- **G4.** Do not regress any v0.1 honesty property. The 696-test suite is the
  guardrail; a failing honesty test is the guardrail working.

## 3. Non-goals for v0.2

- Private repositories (**gated** — see §7)
- Multi-user, auth, or billing (**gated** — see §7)
- Semantic code analysis: call graphs, dependency resolution, symbol indexing
- A conversational interface over a repository
- Additional LLM providers, unless the MCP work makes the current one unnecessary

## 4. Milestone 0 — Reconcile with feedback (BLOCKING)

Before any implementation:

1. Collect what testers said, verbatim where possible.
2. Answer explicitly: **did anyone notice or care about the coverage disclosure?**
3. Record the answer in this document as a dated amendment.
4. If the answer is *no*, stop and re-scope. §5 and §6 assume the guarantee is the
   product; if it is not, v0.2 is the wrong plan and building it would be building
   further on an unvalidated premise.

Deliverable: an amendment to this file stating what the feedback established and
whether the v0.2 scope survives it unchanged.

## 5. Language coverage

### 5.1 Requirements

- **L1.** Extend the supported-extension set to cover mainstream compiled and
  scripting languages. Candidate set, to be defended rather than accepted:
  `.go`, `.rs`, `.java`, `.kt`, `.rb`, `.c`, `.h`, `.cpp`, `.hpp`, `.cs`, `.php`,
  `.swift`, `.scala`, `.m`, `.sql`, `.vue`, `.svelte`.
- **L2.** Each addition is recorded in `selection.md` as a dated amendment with the
  measurement that prompted it, per the existing convention. Anything deliberately
  excluded is recorded as a *decision*, not left as an omission — the distinction
  that mattered in M3.
- **L3.** Extraction for new languages is raw text unless measurement shows
  structure-aware extraction improves summary quality. Do not build language-specific
  parsers speculatively.
- **L4.** **Re-verify ranking after widening.** Widening the supported set changes
  which files a capped run reads. The `psf/requests` failure mode — grounded but
  unrepresentative — can reappear. Ranking must be re-measured on a repository in each
  newly-supported ecosystem, not assumed to still hold.
- **L5.** The accounting identity must hold unchanged. Newly-supported files move from
  `skipped` to `selected`; nothing may become unaccounted for.

### 5.2 Acceptance

- `kubernetes/kubernetes` classifies with Go files `selected` rather than
  `unsupported_extension`, and the identity holds at 37,393 entries.
- At least one repository in each of three newly-supported ecosystems is summarised
  live, with the summary audited mechanically against the chunks the model saw.
- A capped run on a newly-supported repository reads a representative sample —
  demonstrated the way `psf/requests` was, by checking whether the summary describes
  what the project *is*.

## 6. MCP server

### 6.1 Requirements

- **M1.** An MCP server exposing the pipeline as tools. Provisional surface:
  `analyze_repository`, `list_repository_files`, `get_file_content`,
  `get_repository_summary`, `get_repository_diagnostics`.
- **M2.** **Every tool response carries its own provenance.** Specifically:
  - a filtered list states its unfiltered total
  - a paginated response states the full count and what fraction is returned
  - a request for an unread file returns an explicit reason, never an empty result
  - a summary carries the provenance object, not only the prose
- **M3.** The failure mode to design against is a client receiving a partial result
  and reporting it as complete. This is the v0.1 failure mode one layer up, and the
  client cannot be relied on to read a field it was not told about.
- **M4.** The server runs locally with credentials from the client's MCP config —
  the same environment-variable posture as v0.1, which is also how MCP servers
  conventionally receive secrets.
- **M5.** Summarisation becomes optional. A client with its own model may want files
  and inventory and to summarise itself. When it does, RepoBridge spends no provider
  quota — which removes the binding constraint on the whole project.
- **M6.** The existing REST API and web UI continue to work unchanged. MCP is an
  additional surface, not a replacement.

### 6.2 Open design questions — decide with measurement, not preference

- **Does `analyze_repository` block or return a run id immediately?** A large repo
  takes minutes. Blocking is simpler; a run id plus polling is honest about duration.
  Decide against how MCP clients actually behave on long calls.
- **What does a tool return when a repo exceeds the read cap?** The cap is a v0.1
  honesty feature. In a tool context the client may prefer to raise it. Whether the
  cap is client-configurable is a real question with a real risk attached.
- **Is `get_file_content` per-file or batched?** Per-file is more calls; batched risks
  a client silently receiving fewer files than it asked for.
- **Does the MCP server reuse the SQLite store, or is it stateless per invocation?**
  Reuse gives caching and history; stateless is simpler and avoids concurrent-access
  questions with the web app.

### 6.3 Acceptance

- A real MCP client connects and completes an end-to-end repository analysis.
- A tool response for a filtered or capped result is *tested* to carry its own
  completeness information.
- An adversarial check: give a client a deliberately partial result and confirm the
  provenance is present and sufficient for the client to notice.

## 7. Gated work — must not be built in v0.2 without the stated condition

| Work | Gate |
|---|---|
| **Private repositories** | Summarisation must first move to a provider tier that does not train on submitted prompts. Recorded in v0.1 `spec.md` as a blocking prerequisite. Non-negotiable. |
| **Multi-user, auth, billing** | Someone must ask to pay, or repeatedly hit the shared instance's limits and ask for their own. |
| **Retention / delete** | Only when storage growth is a real problem. Currently ten analyses of one repo store ten copies; nobody has complained. |
| **Alembic migrations** | Only when a database holds data that cannot be regenerated by re-running. |
| **API version prefix** | Only when an external consumer exists to pin it. |

## 8. Carried-forward constraints

These held for all of v0.1 and continue unless deliberately amended:

- No frontend framework, no build step, no dependency without a stated reason
- Secrets from the environment only; never a request field, never stored, never logged
- A milestone closes only when every criterion is backed by a test or a recorded live
  result; PARTIAL is never rounded up
- Scope changes are recorded as dated amendments; criteria move intact rather than
  being deleted
- Live API calls are budgeted and spent once per slice, deliberately

## Amendments

### 2026-10-17 — Hosted multi-user platform request

The owner requested planning for a future hosted platform with an anonymous shared
demo pool and optional Google-authenticated, per-user workspaces using each user's
own GitHub and Gemini credentials. The request opens a **scoping and feasibility
draft only** in `specs/003-repobridge-hosted-platform/`; it does not add this work to
v0.2 or authorize implementation.

M0 remains BLOCKING. Its tester-feedback deliverables and coverage-disclosure question
are unchanged and unanswered. The existing multi-user gate remains in force for v0.2.
The future draft is subordinate to `CONTRACT.md`; in particular, no request-supplied
credential path may be implemented until a narrow, dated security amendment to I-6 is
reviewed and approved.
