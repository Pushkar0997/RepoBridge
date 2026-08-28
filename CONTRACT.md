# Correctness Contract

**Every agent reads this before every task.** These are not preferences. They are the
properties that make RepoBridge worth using, and they are never traded for velocity.

Precedence: `CONTRACT.md` > `AGENTS.md` > `spec/architecture.md` > `spec/product.md`
> `spec/plan.md` > `spec/tasks.md`. If this file conflicts with any of them, this
file wins and the other is stale.

**The one-sentence version:** *RepoBridge never claims to have read something it did
not read.* Every invariant below is a way that claim can fail.

---

## Invariants

### I-1 — The accounting identity

```
total_entries == directories + selected + skipped + failed
```

And within the selected set:

```
selected == read + failed + not_fetched
```

**Why:** the product promise is that a user can ask about any file and get an answer.
If an entry can vanish between the tree and the inventory, the promise is void.

**How it gets violated:** a classification path that returns early; a filter applied
before counting; a denormalised count updated in one place and not another; a new
entry type that falls through every branch.

**How it is detected:** `accounts_for_every_entry` and
`accounts_for_every_selected_file`, asserted in tests and recomputed **from stored
rows** — never read from the denormalised count columns, which could drift and then
certify themselves. Verified live at 37,393 entries on `kubernetes/kubernetes`.

### I-2 — Every omission carries a reason

Every skipped file has a machine-readable code from the closed enum **and** a
specific human-readable message. No generic "some files were skipped."

**Why:** a reason code makes omissions groupable and machine-actionable; the message
makes them legible. Either alone is insufficient.

**How it gets violated:** a new skip path added without a code; a message that
restates the code; a code added to the enum that no path can produce.

**How it is detected:** `test_skipped_files_always_carry_a_code_and_a_message` and
`test_every_skip_reason_in_the_enum_is_reachable`.

### I-3 — No field asserts a stage that did not run

A value is set only in the success path of the operation that would confirm it.

**Why:** this is the subtlest form of the core lie. `resolved_ref` naming a ref the
tree call never confirmed is not a factual error — it is a provenance error, and
provenance is the product.

**How it gets violated:** setting a value optimistically before the confirming call;
reusing a field across stages; a column named for one stage holding another stage's
data.

**How it is detected:** `resolved_ref` is null unless the tree call succeeded;
`error` and `tree_error` are never both set
(`test_error_and_tree_error_are_never_both_set`). Truncation is the deliberate
exception: GitHub *did* resolve the ref, the answer is merely partial, so
`resolved_ref` stays populated
(`test_truncated_tree_still_reports_resolved_ref`).

### I-4 — Every partial view says it is partial, where a person reads

A partial result states its own partiality **in the sentence a reader actually
reads** — not only in a field they would have to know to look for.

**Why:** twice, a technically-complete disclosure sat in a field or a count while the
headline sentence said something else. Both were found by walking the system, not by
the suite.

**How it gets violated:** an `if/elif` over conditions that are not mutually
exclusive; a banner keyed on worst-severity rather than on all true conditions; a
count shown without its denominator.

**How it is detected:** scope lines name both numbers under every filter
(`Showing 1–7 of 7 matching entries (of 37,393 in this run)`); the diagnostics banner
states every true condition, not the first match. Combined-condition tests are
mandatory — see N-4 below.

### I-5 — Grounded is not enough; a sample must be representative

Any capped, budgeted or top-N selection is **ranked**, never a prefix of whatever
order the source returned.

**Why:** the `psf/requests` finding. Capped at 20 files taken alphabetically, every
individual claim was true and the conclusion — "heavily structured around GitHub
infrastructure and automation" — was materially wrong about an HTTP library. Per-claim
verification cannot catch this.

**How it gets violated:** a new cap added without ranking; the supported file set
widened without re-checking that ranking still produces a representative sample; a
chunk budget applied in path order.

**How it is detected:** the pre-ranking behaviour is pinned as a regression test.
Representativeness is checked by asking whether the output describes what the project
*is*, not whether each sentence is true. **Re-check whenever the sampled set
changes.**

### I-6 — No secret is stored, logged, rendered, or returned

Credentials come from the environment only. Never a request field, never a database
column, never an error message, never a template, never a log line.

**Why:** a per-request secret flows into persistence, diagnostics and logs by
default, and every future layer must remember to scrub it.

**How it gets violated:** a new column, a new log line, a debug echo of a request, an
error message that includes an upstream response body verbatim.

**How it is detected:** value scans, not name checks — every stored value and every
rendered page is scanned for the key **and for any 8-character fragment of it**, so a
partial reveal also fails. Raw upstream response bodies are never passed to callers.

### I-7 — A run is never lost because it failed

Every attempt that reached GitHub leaves a stored trace: metadata failures, bad refs,
rate limits, network errors. Partial failure never ends a run.

**Why:** a tool whose pitch is that it tells you what went wrong must not discard the
runs that went wrong.

**Exception, deliberate:** URL-validation failures store nothing. Nothing reached
GitHub, so there is no run to record.

**How it is detected:** failed and degraded runs are stored and readable via
`GET /api/runs/{id}`; a malformed URL stores nothing.

---

## Pinned conventions

Stated choices, not discussions. Anything that could reasonably go two ways.

| Convention | Pinned to |
|---|---|
| Timestamps | UTC, ISO 8601, `YYYY-MM-DD HH:MM UTC` in UI |
| Run IDs | UUID4, string |
| API field naming | `snake_case` |
| Error envelope | `{"error": {"code", "message", "details"}}`, one shape everywhere |
| Pagination | `total`, `unfiltered_total`, `limit`, `offset`, `filters`, `items` |
| List key | `items` — never `events`, `files`, or a domain-specific name |
| Filtered counts | always accompanied by the unfiltered total |
| Null vs absent | null means "known to be absent"; a missing key is a bug |
| Extensions | lowercased before matching |
| Config filenames | lowercased before matching |
| Excluded directories | **case-sensitive** — `Build/` ≠ `build/` on Linux, and folding could over-exclude. Deliberate asymmetry with the two rows above. |
| Secrets | environment variables only, `REPOBRIDGE_*` prefix |
| Schema version | integer in `PRAGMA user_version`; currently **4** |
| Token estimate | `chars // 4`, a heuristic and not a tokenizer |

## Exact constants

Agents recompute these slightly differently otherwise.

| Constant | Local | Shared deployment |
|---|---|---|
| Read cap (files/run) | 200 | 100 |
| Max repo entries accepted | unlimited | 5,000 |
| Analyses/hour, instance | unlimited | 20 |
| Analyses/hour, per client | unlimited | 5 |
| Content read concurrency | 8 | 8 |
| Max file size read | 1 MB | 1 MB |
| Tree preview cap | 50 | 50 |
| Classification sample cap | 100 | 100 |

**The quota arithmetic — do not break this sum:**

```
per analysis     2 + 100          = 102 GitHub calls, 1 provider request
saturated hour   20 × 102         = 2,040 GitHub    → 41% of 5,000/hour
saturated day    20 × 24          =   480 provider  → inside ~500/day
```

The instance limit is set by the **provider's daily quota, not GitHub's hourly one** —
an hourly limit cannot otherwise bound a daily one. `test_the_shared_defaults_fit_both_quotas`
recomputes this from the shipped values and fails naming the quota exceeded. **If you
change any of these four numbers, rebalance. Do not loosen the test.**

## Never do this

Each carries its reason. An unexplained prohibition gets rationalised away.

- **Never present a filtered or capped count without its denominator.** A reader who
  sees `7` must not be able to mistake it for the size of the repository.
- **Never delete or weaken a test to make a change pass.** The honesty tests pin
  exact wording; a failure means the wording moved, which is the guardrail working.
  All 611 pre-existing tests passed unchanged through a full visual restyle for
  exactly this reason.
- **Never trust a metered service's own accounting endpoint.** GitHub's
  `/rate_limit` was measured 17 calls behind reality. Use per-response headers.
- **Never sleep an advertised retry delay without checking it against the quota
  window it names.** A daily-quota 429 advertises ~58 seconds when the real reset is
  at the day boundary.
- **Never read a private repository while the summarisation provider's terms permit
  training on submitted content.** Recorded in `spec.md` as a blocking prerequisite.
  This gate is not negotiable and must not be worked around.
- **Never round a PARTIAL up to a PASS to close a milestone.** The milestones held
  open on thin evidence produced this project's most valuable findings.
- **Never let a milestone's criteria be deleted to make it closable.** Criteria move
  intact, as a dated amendment. Redefining done is not achieving it.

## If you are about to violate one of these

Stop and raise it. A contract item that turns out to be wrong is amended
deliberately, with a dated entry in `specs/decisions.md`. It is not worked around.
