# RepoBridge v0.2 — Evals

How correctness is proven. Criteria before the work; **recorded verdicts after**.

**PASS only where a test or a recorded live result backs it.** Not inspection, not
"it obviously works."

**Never round up a PARTIAL.** The strongest temptation in the system and the most
important rule in it. In v0.1 the milestones held open on thin evidence produced the
project's most valuable finding.

---

## 1. How to run

```
python -m pytest -v
```

Must pass before any deploy. Non-zero exit on failure.

Live verification is budgeted separately: **one provider request per slice, at the
end, deliberately.** Never probe against the live API — reproduce with mocks.

## 2. Invariant tests

One per `CONTRACT.md` invariant. An invariant without a test is a hope.

| ID | Invariant | Assertion |
|---|---|---|
| INV-1-T | I-1 accounting identity | `directories + selected + skipped + failed == total_entries`, recomputed from stored rows, never from denormalised columns |
| INV-1b-T | I-1 read identity | `read + failed + not_fetched == selected` |
| INV-2-T | I-2 reasons | every SKIPPED row has a non-null enum code and a message that is not a restatement of the code; every enum member is reachable |
| INV-3-T | I-3 no false stage | `resolved_ref` is null unless the tree call succeeded; `error` and `tree_error` are never both non-null |
| INV-3b-T | I-3 exception | a truncated tree keeps `resolved_ref` populated |
| INV-4-T | I-4 partial says partial | a run that is both partial and degraded states both conditions in the banner text, not the first match only |
| INV-5-T | I-5 representativeness | the pre-ranking ordering is pinned as a regression; `rank_files` is a permutation over the input |
| INV-6-T | I-6 no secrets | no stored value and no rendered page contains a key or any 8-character fragment of one |
| INV-7-T | I-7 failures persist | metadata failure, bad ref, rate limit and network error each store a readable run; a malformed URL stores nothing |
| INV-Q-T | quota arithmetic | worst-case hour and day recomputed from the shipped constants stay inside both ceilings |

## 3. Golden values

Literal expected values. Agents recompute descriptions differently; they cannot
recompute a number.

| ID | Input | Expected |
|---|---|---|
| G-01 | `kubernetes/kubernetes` classified | 37,393 entries, identity true |
| G-02 | `psf/requests` selected | 107 of 153 entries |
| G-03 | `psf/requests` capped at 20, ranked | summary names the HTTP library, not CI infrastructure |
| G-04 | `octocat/Hello-World` summarised | declines to characterise; no padding |
| G-05 | shared defaults | 20 × 102 = 2,040 GitHub/hour; 20 × 24 = 480 provider/day |

## 4. Negative tests

**More important than the positive ones.** These catch regressions positive tests
miss.

| ID | Assertion |
|---|---|
| N-01 | a nonexistent branch returns 404 naming the ref — never 200 with metadata |
| N-02 | a filtered count is never returned without its unfiltered total |
| N-03 | a tool response for an unread file returns a reason, never an empty result |
| N-04 | **combined conditions**: for every state pair that can co-occur, the display states both. Neither single-condition test may pass in place of this |
| N-05 | a raw upstream response body never reaches a caller |
| N-06 | a daily-quota 429 is not slept against its advertised retry delay |
| N-07 | a stale database refuses to start with a readable message, not `OperationalError` |
| N-08 | a capped run's summary does not describe the repository from an unrepresentative slice — checked by what it says the project *is* |

## 5. Per-milestone criteria

### M0 — Reconcile with feedback

| Criterion | How judged |
|---|---|
| Feedback recorded verbatim | `feedback.md` contains quotes, not a summary |
| Disclosure question answered | yes / no / mixed, with the supporting quotes |
| Amendment written | dated entry in `spec.md` naming what changed |
| Scope decision made | go or re-scope, in writing |

**Failure signals**
- Feedback summarised in a way that happens to confirm the existing plan
- Silence treated as neutral rather than as a finding
- M1 started before the amendment exists

### M1 — Language coverage

| Criterion | How judged |
|---|---|
| New extensions classified | tests per type; live per ecosystem |
| Additions recorded | `selection.md` amendment with the prompting measurement |
| Exclusions recorded as decisions | anything unsupported is a written judgement, not an omission |
| Identity holds | G-01, recomputed from rows |
| Ranking re-verified | N-08 on a newly-supported ecosystem |
| No regression | full v0.1 suite unchanged |

**Failure signals**
- Extensions added without a recorded reason
- Ranking assumed rather than re-measured
- A grounded summary that describes the wrong thing

### M2 — MCP core tools

| Criterion | How judged |
|---|---|
| Real client connects | live, not a mock |
| Filtered totals honest | N-02 at the tool boundary |
| No credential leaks | INV-6-T extended to tool responses |
| No regression | REST and UI suites unchanged |
| Design questions decided | entries in `specs/decisions.md` naming rejections |

**Failure signals**
- Pipeline logic duplicated in the MCP path rather than reused
- A tool response that is partial without saying so

### M3 — MCP content and summary tools

| Criterion | How judged |
|---|---|
| Content or reason | N-03 per status: skipped, not-fetched, failed |
| Provenance travels | the object, not only the prose |
| Summarisation optional | zero provider requests, and the absence explained |
| Adversarial provenance | a partial result is detectable by a client that did not know which field to read |
| Diagnostics ordering stable | across re-summarisation |

**Failure signals**
- An empty result where a reason belongs
- Prose that could be quoted without its provenance and still read as complete

### M4 — MCP hardening and docs

| Criterion | How judged |
|---|---|
| Installable from docs | **someone other than the author does it and reports where they got stuck** |
| Long analyses legible | live, on a large repository |
| Tool-appropriate errors | actionable by a model, not a stack trace |

**Failure signals**
- Any instruction in the docs that has never been executed as written
- A silent multi-minute call

### M5 — Release

| Criterion | How judged |
|---|---|
| All verdicts recorded | this file, one row per criterion |
| README matches reality | conformance tests, including the MCP surface |
| Clean-machine path | **executed**, not reviewed |
| Tagged | `v0.2.0` |

---

## 6. Recorded verdicts

*Written after a milestone. One row per criterion with the evidence that justifies it.
This table is what catches a milestone being 60% done and called finished.*

### Template

```
### <YYYY-MM-DD> — M<n> verdict

| Criterion | Verdict | Evidence |
|---|---|---|
| <from the exit criteria> | PASS | `test_name` / smoke run N |
| <...> | PARTIAL | <exactly what is missing> |

**Closes?** <yes — or no, and precisely what would close it>
**Caveats carried forward:** <recorded as notes, not blockers>
```

*(no v0.2 verdicts yet — M0 is open)*

---

## 7. Standing criteria

Apply to every milestone. These are `CONTRACT.md` properties that must survive all
work. **A failing test here is the guardrail working, not an obstacle to route
around.**

- The accounting identity holds, recomputed from stored rows
- Every omission carries a code and a specific message
- No field asserts a stage that did not run
- Every partial view says it is partial where a person reads
- Every sampled selection is ranked, and representativeness is re-checked whenever
  the sampled set changes
- No secret is stored, logged, rendered or returned
- Every attempt that reached GitHub leaves a stored trace
- Combined conditions are tested, not only single ones

## 8. Pre-deploy gate

- [ ] Tests pass
- [ ] `smoke.md` checklist passes for the affected area
- [ ] Quota arithmetic test passes with the shipped constants
- [ ] No draft or placeholder content reachable in production
- [ ] README conformance tests pass
