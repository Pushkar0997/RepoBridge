# Correctness Contract

**Every agent reads this before every task.** These are not preferences. They are the
properties that make RepoBridge worth using, and they are never traded for velocity.

Precedence: `CONTRACT.md` > `AGENTS.md` > `specs/001-repobridge-v0.1/spec.md` >
`specs/001-repobridge-v0.1/selection.md` > `specs/001-repobridge-v0.1/plan.md` >
`specs/001-repobridge-v0.1/tasks.md`. If this file conflicts with any of them, this
file wins and the other is stale.

The active version's own files (`specs/002-repobridge-v0.2/`) take the same rank as
their v0.1 counterparts for behaviour that version defines, and no rank at all for
behaviour it has not shipped. `specs/001-repobridge-v0.1/capabilities.md` is
descriptive — it records what does not exist and where each absence was decided; it
never creates or reverses a decision.

There is no `architecture.md` or `product.md`; an earlier draft of this list named
both, along with a `spec/` directory that has never existed.

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

**How it is detected:** both identities are recomputed **from stored rows** — never
read from the denormalised count columns, which could drift and then certify
themselves. `ClassificationResult.accounts_for_every_entry` and
`ExtractionResult.accounts_for_every_selected_file` are the in-memory checks; they
certify the object that was just built, which is necessary and not sufficient.

The stored-row checks are the load-bearing ones:

| Identity | Live field | Test |
|---|---|---|
| `total_entries == directories + selected + skipped + failed` | `stored_rows.stored_identity_holds` | `test_identity_is_reconstructible_from_stored_rows_alone`, `test_stored_counts_match_the_denormalised_run_columns` |
| `selected == read + failed + not_fetched` | `stored_rows.stored_extraction_identity_holds` | `test_the_extraction_identity_is_reconstructible_from_stored_rows_alone`, `test_the_stored_extraction_identity_notices_a_row_the_counts_do_not` |

Both fields are `null`, never `false`, for a run that classified nothing: a degraded
run stored no entry rows, so the identity is vacuous rather than violated.

Verified live at 37,393 entries on `kubernetes/kubernetes`.

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
(`Showing 1–7 of 7 matching entries (of 37393 in this run)` — the run total is rendered
as a bare integer, no thousands separator); the diagnostics banner states every true
condition, not the first match. `test_the_tree_scope_line_survives_unchanged` covers
the scope line under a filter.

**Combined-condition tests are mandatory.** Both of this project's I-4 failures were a
run that was two things at once being announced as one, and in both cases every
single-condition test passed. A test per condition does not compose into a test of the
combination. Pinned by
`test_the_banner_states_both_conditions_when_a_run_is_partial_and_degraded`,
`test_a_failed_run_that_is_also_partial_says_both`, and
`test_the_diagnostics_banner_survives_unchanged`.

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

**How it is detected:** the pre-ranking behaviour is pinned as a regression test —
`test_path_order_would_have_failed_that_same_check` asserts that tree order *still*
reads zero files of `src/requests/`, beside
`test_the_run_8_regression_a_capped_run_reads_the_library_not_just_ci` asserting that
ranking does not. A guard that only checks the fix passes trivially once the fix is
reverted; keeping the old behaviour executable is what makes it a regression test.

Representativeness itself is checked by asking whether the output describes what the
project *is*, not whether each sentence is true. No test can do that. **Re-check
whenever the sampled set changes** — v0.2 M1 changes it.

### I-6 — No secret is stored, logged, rendered, or returned

Credentials come from the environment only. Never a request field, never a database
column, never an error message, never a template, never a log line.

**Why:** a per-request secret flows into persistence, diagnostics and logs by
default, and every future layer must remember to scrub it.

**How it gets violated:** a new column, a new log line, a debug echo of a request, an
error message that includes an upstream response body verbatim.

**How it is detected:** value scans, not name checks. A value can come to rest in three
places, and all three are scanned for **both keys and for any 8-character fragment of
either**, so a partial reveal also fails:

| Where | Test |
|---|---|
| Stored rows | `test_no_key_value_is_written_anywhere`, plus the name checks `test_schema_has_no_credential_column` and `test_only_token_named_columns_are_counts` |
| Rendered pages | `test_no_key_value_can_reach_a_template`, `test_the_key_status_context_carries_booleans_not_values` |
| Log lines | `test_a_clean_run_puts_no_secret_in_a_log_line`, `test_an_upstream_body_echoing_the_token_is_redacted_before_it_is_logged`, `test_a_token_split_by_truncation_still_does_not_leak_a_fragment`, `test_an_unhandled_traceback_is_redacted_before_it_reaches_the_log`, `test_a_provider_failure_puts_no_secret_in_a_log_line` |

Raw upstream response bodies are never passed to callers
(`test_500_body_is_not_echoed_in_message`), and where one is *logged* for debugging it
goes through `core/diagnostics.redact` **before** being truncated. That order is
load-bearing and is pinned: truncating first can cut a token in half and leave a
fragment `redact` no longer recognises.

The unhandled-exception traceback is rendered by `api/errors.py` rather than handed to
`logger.exception`, for the same reason — `exception()` defers formatting to the
handler, which is past the last point this application controls.

### I-7 — A run is never lost because it failed

Every attempt that reached GitHub leaves a stored trace: metadata failures, bad refs,
rate limits, network errors. Partial failure never ends a run.

**Why:** a tool whose pitch is that it tells you what went wrong must not discard the
runs that went wrong.

**The boundary is "reached GitHub", not "did useful work."** A call was spent and
something was learned; both are worth recording. Every refusal that got that far stores
a run and returns its `run_id` in `details`, so a caller can open the run that was
refused — a metadata failure, a bad ref, and an instance size refusal alike.

**Exception, deliberate, and the only one:** URL-validation failures store nothing.
Nothing reached GitHub, so there is no run to record. The per-visitor and per-instance
rate limits fall under the same exception for the same reason — they refuse before the
first call.

**How it is detected:** failed and degraded runs are stored and readable via
`GET /api/runs/{id}` (`test_error_and_tree_error_are_never_both_set`,
`test_degraded_run_is_stored_with_its_error`,
`test_failed_run_uses_error_not_tree_error`); a malformed URL stores nothing
(`test_invalid_url_stores_nothing`); a size refusal stores a failed run carrying the
`resolved_ref` and entry count GitHub did confirm
(`test_the_size_refusal_is_recorded_in_diagnostics`,
`test_the_refused_run_keeps_what_github_actually_confirmed`,
`test_a_refused_repository_is_listed_like_any_other_failed_run`).

---

## Pinned conventions

Stated choices, not discussions. Anything that could reasonably go two ways.

| Convention | Pinned to |
|---|---|
| Timestamps | UTC, ISO 8601, `YYYY-MM-DD HH:MM UTC` in UI |
| Run IDs | UUID4, string |
| API field naming | `snake_case` |
| Error envelope | `{"error": {"status", "code", "message", "details"}}`, one shape everywhere. **Four keys** — `status` repeats the HTTP status in the body so a logged body is self-describing. `details` is always present and always an object, possibly empty. |
| Pagination | `total`, `unfiltered_total`, `limit`, `offset`, `filters`, `items` |
| List key | `items` — never `events`, `files`, or a domain-specific name |
| Filtered counts | always accompanied by the unfiltered total |
| Null vs absent | For a **response field**: null means "known to be absent"; a missing key is a bug. **Two deliberate exceptions, both in `details` maps:** `api_error` and `Recorder.record` each drop `None`-valued entries, so an optional detail is absent rather than present-and-null. Those maps are open sets of structured extras, not a fixed schema, and a wall of nulls is noise rather than information. |
| Extensions | lowercased before matching |
| Config filenames | lowercased before matching |
| Query-filter values | `owner` is matched case-insensitively; `REPOBRIDGE_DEPLOYMENT` and `REPOBRIDGE_STORAGE` values are lowercased |
| Excluded directories | **case-sensitive** — `Build/` ≠ `build/` on Linux, and folding could over-exclude. Deliberate asymmetry with the two rows above. |
| Secrets | environment variables only, `REPOBRIDGE_*` prefix |
| Schema version | integer in `PRAGMA user_version`; currently **4** |
| Token estimate | `chars // 4`, a heuristic and not a tokenizer |

The envelope and pagination rows are enforced across the whole surface rather than
sampled: `test_every_list_endpoint_returns_the_same_pagination_fields` and
`test_every_run_scoped_endpoint_404s_with_the_same_envelope` iterate every endpoint, so
a new one that invents its own shape fails several tests at once rather than none.
`test_no_endpoint_has_acquired_a_version_prefix` holds the unversioned decision.

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
| Tree preview cap (`TREE_PREVIEW_LIMIT`) | 50 | 50 |
| Classification sample cap (`CLASSIFICATION_SAMPLE_LIMIT`) | 50 | 50 |
| Chunk preview, run detail page | 20 | 20 |

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

**The GitHub ceiling in that test is 60% of the quota, not 100%.** 2,040 of 5,000 is
41%, and the headroom is deliberate on two counts: the operator must still be able to
use their own token while the demo runs, and concurrency provokes GitHub's *secondary*
limits well before the primary one. A rebalance that satisfies the arithmetic above and
exceeds 3,000 calls an hour still fails, correctly.

## Never do this

Each carries its reason. An unexplained prohibition gets rationalised away.

- **Never present a filtered or capped count without its denominator.** A reader who
  sees `7` must not be able to mistake it for the size of the repository.
- **Never delete or weaken a test to make a change pass.** The honesty tests pin
  exact wording; a failure means the wording moved, which is the guardrail working.
  The Milestone 10 visual restyle changed every stylesheet and template and broke
  nothing: the suite stood at 611 at the time it was judged, and the honesty
  assertions passed unchanged. (611 was the total *including* the 76 UI tests written
  for that slice, not a pre-existing count. The suite is 710 now.)
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
