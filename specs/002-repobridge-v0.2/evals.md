# RepoBridge v0.2 — Evaluation Criteria (DRAFT)

How each v0.2 milestone will be judged. Same rules as v0.1:

- **PASS only where a test or a recorded live result backs it.** Not inspection, not
  "it obviously works."
- **PARTIAL is never rounded up.** A milestone stays open until the evidence supports
  closing it. In v0.1 this produced the project's most valuable finding.
- Verdicts are recorded here, dated, criterion by criterion, with the file, line or
  test name that justifies each.

---

## Milestone 0 — Reconcile with feedback

| Criterion | How judged |
|---|---|
| Feedback collected | Recorded verbatim where possible, not paraphrased into agreement |
| The disclosure question answered | An explicit yes/no/mixed with evidence, not an interpretation |
| Amendment written | Exists in `spec.md`, dated, states what was established |
| Scope decision made | Go or re-scope, written down with reasoning |

**Failure signals**
- Feedback summarised in a way that happens to confirm the existing plan
- Silence treated as neutral rather than as information
- Proceeding to Milestone 1 without the amendment

---

## Milestone 1 — Language coverage

| Criterion | How judged |
|---|---|
| New extensions classified correctly | Tests per type; live on a real repository per ecosystem |
| Additions recorded | `selection.md` amendment, dated, with the prompting measurement |
| Exclusions recorded as decisions | Anything deliberately unsupported is written down as a judgement, not left as an omission |
| Identity holds | `kubernetes/kubernetes` at 37,393 entries, verified from stored rows |
| No regression | The full v0.1 suite passes unchanged |
| **Ranking re-verified** | A capped run on a newly-supported repository reads a representative sample, checked the way `psf/requests` was |
| Live summaries audited | Three ecosystems, claims checked mechanically against the chunks sent |

**Failure signals**
- Extensions added without a recorded reason
- Ranking assumed to still hold rather than re-measured
- A summary that is grounded but describes the wrong thing — the v0.1 failure mode
  reappearing through a widened file set
- Identity drift on any repository

---

## Milestone 2 — MCP server, core tools

| Criterion | How judged |
|---|---|
| Server connects | A real MCP client, not only a mock |
| `analyze_repository` works end to end | Live, against a real repository |
| `list_repository_files` filters correctly | Tests, including that a filtered total is never presented as the whole |
| Credentials from client config | Test that no key is read from anywhere else, and none is logged or returned |
| Design questions decided | `spec.md` §6.2 answered with reasoning recorded, not left implicit |
| No regression | REST API and web UI unchanged; full suite passes |

**Failure signals**
- A tool response that is partial without saying so
- A filtered count that could be mistaken for a total
- The MCP path duplicating pipeline logic rather than reusing it — two
  implementations will drift, and the drift will be silent

---

## Milestone 3 — MCP content and summary tools

| Criterion | How judged |
|---|---|
| `get_file_content` returns content or a reason | Tested for read, not-fetched, failed and skipped files — never an empty result standing in for an explanation |
| `get_repository_summary` carries provenance | The object, not only the prose |
| `get_repository_diagnostics` returns the timeline | Ordering stable across re-summarisation, as fixed in v0.1 M7 |
| Summarisation optional | A run with it disabled completes, spends zero provider quota, and says why no summary is present |
| **Adversarial provenance check** | A deliberately partial result is handed to a client; the provenance is sufficient for the client to notice |

**Failure signals**
- An empty result where a reason belongs
- A summary tool response whose prose could be quoted without its provenance and
  still read as complete
- A client that could not have known the result was partial

---

## Milestone 4 — MCP hardening and documentation

| Criterion | How judged |
|---|---|
| Installable from documentation | **Someone other than the author does it and reports where they got stuck.** This cannot be self-administered. |
| Long analyses do not appear stuck | Live, on a large repository |
| Errors appropriate to a tool context | A failure returns something a model can act on, not a stack trace |

**Failure signals**
- Documentation that assumes knowledge only the author has
- A silent multi-minute call
- Any instruction in the docs that has never been executed as written

---

## Milestone 5 — Release

| Criterion | How judged |
|---|---|
| Every v0.2 milestone has a recorded verdict | This file |
| README matches reality | The v0.1 conformance tests still pass; new surfaces documented |
| Clean-machine path | **Executed, not reviewed.** The v0.1 method found four real defects. |
| Smoke suite updated | New runs recorded, index updated |
| Tagged | v0.2.0 |

**Failure signals**
- A verdict rounded up to close the version
- The README describing an MCP capability that has not been exercised
- A clean-machine path reasoned about rather than run

---

## Standing criteria — apply to every milestone

These are v0.1 properties that must survive v0.2. A failing test here is the guardrail
working, not an obstacle.

- The accounting identity holds:
  `total_entries == directories + selected + skipped + failed`
- Every skip carries a machine-readable code and a specific human message
- Every partial view says it is partial, in the sentence a reader actually reads
- No secret is stored, logged, or returned — value scans, not name checks, including
  partial fragments
- No response asserts a stage that did not run
- Combined conditions are tested, not only single ones. Two consecutive v0.1
  milestones shipped a defect where a case that was two things at once was handled as
  though it were one, and both were found by live walkthroughs rather than the suite.
