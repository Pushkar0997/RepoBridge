# RepoBridge v0.2 — Plan (DRAFT)

**Status: DRAFT, pending Milestone 0.** Milestones 2 onward assume the feedback
confirms the accountability guarantee is what users value. If it does not, re-scope
before proceeding.

Milestone numbering continues the v0.1 convention. Each milestone closes only when
every criterion in `evals.md` is backed by a test or a recorded live result.

---

## Milestone 0 — Reconcile with feedback **(BLOCKING)**

**Deliverables**
- Feedback collected and recorded, verbatim where possible
- An explicit answer to: did anyone notice or care about the coverage disclosure?
- A dated amendment to `spec.md` stating what the feedback established
- A go / re-scope decision, written down

**Expected behaviour**
- If feedback contradicts the premise, the plan changes and the change is recorded.
  Proceeding unchanged despite contradicting feedback is the failure mode here.

**Validation**
- The amendment exists and names what was learned, including anything that was
  learned by nobody replying.

---

## Milestone 1 — Language coverage

**Deliverables**
- Extended supported-extension set in config
- `selection.md` amendment recording each addition and each deliberate exclusion
- Ranking re-measured on a repository in each newly-supported ecosystem
- Tests for classification and extraction of each new type

**Expected behaviour**
- Newly-supported files move from `skipped` to `selected`
- The accounting identity holds unchanged
- No previously-supported behaviour changes
- A capped run on a Go or Rust repository reads a representative sample

**Validation**
- `kubernetes/kubernetes` classifies Go as `selected`; identity holds at 37,393
- Live summaries for three newly-supported ecosystems, mechanically audited
- The representativeness check applied the way `psf/requests` was

**Watch for:** widening the set changes which files a capped run reads. Ranking is
re-measured, not assumed. This is the most likely place for the v0.1 failure mode to
reappear.

---

## Milestone 2 — MCP server, core tools

**Deliverables**
- MCP server exposing `analyze_repository` and `list_repository_files`
- Credentials from the client's MCP config
- The design questions in `spec.md` §6.2 decided, with reasoning recorded

**Expected behaviour**
- A real MCP client connects and completes an analysis
- Every response carries its own completeness information
- The existing REST API and web UI are unaffected

**Validation**
- End-to-end against a real MCP client, not only a mock
- A filtered list response is tested to state its unfiltered total

---

## Milestone 3 — MCP server, content and summary tools

**Deliverables**
- `get_file_content`, `get_repository_summary`, `get_repository_diagnostics`
- Summarisation made optional, so a client with its own model spends no provider quota

**Expected behaviour**
- A request for an unread file returns an explicit reason, never an empty result
- A summary response carries the provenance object, not only prose
- With summarisation disabled, no provider request is made and the client is told why
  no summary is present

**Validation**
- Adversarial check: hand a client a deliberately partial result and confirm the
  provenance is sufficient for it to notice
- A run with summarisation disabled completes and spends zero provider quota

---

## Milestone 4 — MCP hardening and documentation

**Deliverables**
- Installation and configuration documentation for MCP clients
- Behaviour under long-running analyses settled and documented
- Error and timeout behaviour appropriate to a tool context

**Expected behaviour**
- A user can install and configure the server from documentation alone
- A long analysis does not appear stuck

**Validation**
- Someone other than the author installs it from the docs and reports where they got
  stuck. This is the milestone's real test and cannot be self-administered.

---

## Milestone 5 — Release v0.2

**Deliverables**
- Verdicts recorded for every v0.2 milestone
- README and smoke suite updated
- Tag

**Validation**
- Clean-machine path executed, not reviewed — the v0.1 M10 method, which found four
  real defects including an empty test file that had read as coverage for five
  milestones

---

## Deferred design items

Carried from v0.1, still open, not scheduled:

- **`CREDENTIAL_LIKE` skip reason.** `.pem`/`.key`/`.crt` currently skip as merely
  `unsupported_extension`. Distinguishing a test fixture from a real secret needs file
  content. Open question: false positives.
- **Logging hooks in core modules.** Resolved in v0.1 as *not* to be built — per-module
  hooks would create a second narrative of a run that drifts from the diagnostics
  timeline. Revisit only if diagnostics prove insufficient.
- **`excluded_directories` case-sensitivity.** Deliberately case-sensitive while
  filenames and lockfiles fold, because directory names are meaningfully
  case-sensitive on Linux. Recorded so a future reader does not "fix" it.
- **Token estimate.** `chars // 4`, not a tokenizer. Under-counts code.
- **Chunk splitting.** One chunk per file except notebooks. A 1MB file is one large
  chunk. `chunk_index` already exists, so adding splitting will not change the model.
- **Truncation is mock-only.** GitHub did not truncate at 37,393 entries.
- **The Dockerfile has never been built.** Static consistency tests cover the class of
  failure; the image itself is untested.

## Gated, not scheduled

See `spec.md` §7. Private repositories, multi-user, retention, migrations and an API
version prefix each have a stated condition. **The private-repo gate — moving off a
training-enabled provider tier — is non-negotiable and predates this plan.**
