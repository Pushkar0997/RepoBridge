# RepoBridge v0.1 Evals

This file defines how RepoBridge v0.1 should be evaluated at each milestone.

The goal is not only to check whether the app runs, but whether it behaves like a trustworthy, grounded, production-minded local tool.

---

## Eval philosophy

RepoBridge should be evaluated on:

- correctness,
- grounding,
- reliability,
- diagnostics quality,
- user clarity,
- and local performance.

A milestone is not “done” just because code executes. A milestone is done when the observed behavior matches the spec, the failure modes are visible, and the results are understandable to a human reviewer.

---

## Global scoring dimensions

Use these dimensions across milestones where applicable:

- **Correctness** – does the feature return the right output for the right input?
- **Grounding** – does the summary or analysis stay faithful to retrieved source content?
- **Coverage** – did the system process the expected files or data?
- **Reliability** – does the system survive invalid inputs, missing repos, malformed files, and partial failures?
- **Explainability** – are skipped items, failures, and limitations clearly shown?
- **Performance** – is the app responsive enough for local use?
- **Usability** – can a human understand and use the output without reading the code?

Suggested severity labels:

- **PASS** – behavior matches expectations.
- **PASS WITH NOTES** – behavior works, but there are minor limitations.
- **FAIL** – behavior does not meet the milestone requirement.

---

## Milestone 0 – Project skeleton evals

### What to verify
- The app starts locally without crashing.
- `/health` returns a healthy response.
- The root UI route renders.
- Configuration and logging modules are loadable.
- SQLite can be initialized.

### Success criteria
- App boots successfully.
- Health endpoint returns `{"status": "ok"}` or equivalent healthy JSON.
- Root page loads.
- No fatal startup errors.

### Failure signals
- Import errors.
- Missing dependencies.
- Broken template rendering.
- Database initialization failures.

---

## Milestone 1 – Repo URL intake and validation evals

### Test set
Use a small set of URLs:
- valid GitHub repo URLs,
- invalid URLs,
- non-GitHub URLs,
- malformed inputs,
- trailing slash variants.

### What to verify
- Valid GitHub repo URLs are normalized correctly.
- Invalid URLs are rejected with clear reasons.
- No GitHub retrieval happens before validation succeeds.

### Success criteria
- Owner and repo are parsed correctly.
- Error messages are clear and specific.
- No false positives for unsupported URLs.

### Suggested score
- 5/5 if valid inputs parse correctly and invalid inputs fail clearly.
- 3/5 if parsing works but edge cases are inconsistent.
- 1/5 if input validation is unreliable or ambiguous.

---

## Milestone 2 – GitHub retrieval evals

### Test set
Use a handful of public repos with different shapes:
- small repo,
- repo with nested directories,
- notebook-heavy repo,
- docs-heavy repo,
- repo that does not exist.

### What to verify
- Repo metadata is retrieved correctly.
- Tree structure matches GitHub.
- Rate-limit and not-found conditions are handled explicitly.
- Partial failures do not crash the run.

### Success criteria
- Tree paths are accurate.
- Missing repo errors are surfaced clearly.
- Rate-limit conditions are detected and surfaced clearly at the point of failure.
- Retrieval completes for normal public repos.

> "Rate-limit conditions are visible in diagnostics" moved from here to Milestone 7 by the
> 2026-08-17 amendment in `plan.md` (second pass): this milestone builds no diagnostics, so
> the criterion was unsatisfiable where it sat. It is unchanged, only relocated.

### Failure signals
- Silent tree truncation.
- Wrong branch/ref handling.
- Generic “something went wrong” errors with no detail.

---

### Recorded verdict — 2026-08-17

Judged against the code as it stands, after the scope split recorded in `plan.md`.
A criterion is PASS only where a test or a recorded live result backs it.
Test suite at time of judging: **51 passing**.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| GitHub client module | plan D1 | PASS | `core/github_client.py` |
| Repo metadata retrieval | plan D2 | PASS | `github_client.py:136`; live 200 on `Pushkar0997/quantum-toybox` |
| Tree retrieval for a valid ref/branch | plan D3 | PASS | `github_client.py:159`, wired at `routes_runs.py:87`; `test_metadata_and_tree_both_succeed`; live 40 entries |
| Rate-limit and not-found error handling | plan D4 | PASS | `github_client.py:50,109`; `test_429_with_remaining_zero_is_rate_limit`, `test_403_with_remaining_zero_is_rate_limit`, `test_metadata_404`, `test_tree_404` |
| Tests covering success / not-found / rate-limit / network paths | plan D5 | PASS | `tests/test_github_client.py`, `tests/test_api.py`; 51 passing, all GitHub responses mocked |
| Public repos can be retrieved | plan E1 | PASS | live: metadata + 40 tree entries |
| Tree paths accurate for the resolved ref | plan E2 | PASS | `test_metadata_and_tree_both_succeed`; live preview matches repo layout |
| Errors surfaced clearly; our status reflects the real fault | plan E3 | PASS | `_status_for` at `routes_runs.py:20`; `test_upstream_500_maps_to_502`, `test_primary_rate_limit_maps_to_429_not_403`, `test_genuine_403_stays_403`, `test_401_stays_401`, `test_404_stays_404`; live 429 during a real rate limit |
| Analysis continues safely when possible | plan E4 | PASS | `routes_runs.py:100`; `test_network_error_on_tree_degrades_to_200`, `test_429_rate_limit_on_tree_degrades_to_200`, `test_secondary_rate_limit_on_tree_still_degrades_to_200` |
| Incomplete results labelled incomplete | plan E5 | PASS | `routes_runs.py:107,117`; `test_truncated_tree_sets_flag_and_warns_in_tree_error` |
| Smoke tests across a set of sample repos | plan V1 | PASS | `smoke.md` Run 1, 2026-08-17: six repos (tiny, medium, notebook-heavy, docs-heavy, deeply nested, nonexistent) plus three error cases, all recorded with real outcomes |
| Verify tree completeness / truncation reported | plan V2 | PASS | `test_truncated_tree_sets_flag_and_warns_in_tree_error`. Note: mock-only; no repo large enough to truncate has been retrieved. |
| Error messages for nonexistent repos and refs | plan V3 | PASS | live 404 both cases; `test_explicit_bad_ref_returns_404_naming_the_ref` |
| Rate-limit handling is explicit | plan V4 | PASS | `test_rate_limit_message_includes_reset_time`; live message carried the correct reset time |
| Repo metadata retrieved correctly | evals | PASS | as plan D2 |
| Tree structure matches GitHub | evals | PASS | as plan E2 |
| Rate-limit and not-found handled explicitly | evals | PASS | as plan D4; primary and secondary limits both detected (`github_client.py:50`) |
| Partial failures do not crash the run | evals | PASS | as plan E4 |
| Rate limits detected and surfaced at point of failure | evals | PASS | `github_client.py:50`; live 429 and live degraded-run `tree_error`, both recorded in `smoke.md` |
| Retrieval completes for normal public repos | evals | PASS | `smoke.md` Run 1: 5/5 real repos, 1 to 37,393 entries |

> *"Rate-limit conditions are visible in diagnostics" was judged NOT STARTED in the first
> pass of this verdict. It has since moved to Milestone 7 by the 2026-08-17 amendment
> (second pass) in `plan.md`, because Milestone 2 builds no diagnostics. It is not waived.*

#### The two named failure signals

**“Silent tree truncation” — eliminated.** `truncated` is read from GitHub's response at
`routes_runs.py:107` and surfaced as `tree_truncated`, and `routes_runs.py:117` additionally
writes a human-readable warning into `tree_error`, so truncation is never discoverable only
by noticing a boolean. `tree_entry_count` is deliberately not named “total”. Backed by
`test_truncated_tree_sets_flag_and_warns_in_tree_error`. Caveat worth keeping: this path has
only ever run against mocked responses, because truncation requires a repo far larger than
any yet retrieved.

**“Wrong branch/ref handling” — eliminated.** *(Verdict revised in the third pass below; it
read “narrowed, not eliminated. PARTIAL” until the `resolved_ref` fix landed.)* An explicit
ref that GitHub cannot resolve returns 404 naming the ref (`routes_runs.py:89`,
`test_explicit_bad_ref_returns_404_naming_the_ref`, confirmed live), where it previously
returned 200 with the bad ref echoed back. The default-branch fallback is correct and
live-verified on two repos, including one whose default is `master` rather than `main`. And
`resolved_ref` is now null unless GitHub actually answered for that ref, so the response never
asserts a resolution that did not happen.

One nuance remains, recorded as an observation rather than an open gap: the 404-means-bad-ref
inference keys on status code alone, so a tree 404 arising from some other cause would still
be reported as the caller's ref being wrong. The message would remain literally true in the
case we can think of — an empty repository, which has no refs at all — so this is a
cause-attribution weakness, not mishandling of a ref. See the caveat in `smoke.md`; it is
reasoned from GitHub's documented behaviour and has not been observed.

#### Third pass — 2026-08-17: `resolved_ref` residual closed

**What the residual was.** The second pass left one item open. When the tree call failed for a
non-404 reason (rate limit, network error, upstream 5xx), `/api/analyze` returned 200 with
`resolved_ref` naming a ref that had never been confirmed to exist. It was not a silent
failure — `tree_error` was populated — but the field asserted a resolution that had not
happened, which is the same category of dishonesty as the truncation flag this milestone
already fixed.

**What changed.** `routes_runs.py` now separates the two ideas: `attempted_ref` is what gets
sent to GitHub, and `resolved_ref` starts as `None` and is assigned only after GitHub has
answered for that ref. On any tree failure it stays null.

**Why no replacement field.** The smaller honest shape was chosen over adding an
`attempted_ref` to the response. What would have been used is already derivable from fields
that survive a failure — `branch_or_ref` when the caller supplied one, else
`metadata.default_branch` — so a third field would duplicate derivable data while itself
asserting nothing verified.

**Tests backing it.** `test_resolved_ref_is_the_ref_used_when_tree_succeeds`,
`test_resolved_ref_is_default_branch_when_no_ref_supplied_and_tree_succeeds`,
`test_resolved_ref_is_null_on_tree_network_error`,
`test_resolved_ref_is_null_on_tree_rate_limit`,
`test_resolved_ref_is_null_on_tree_upstream_5xx`,
`test_resolved_ref_null_still_leaves_intent_derivable`,
`test_explicit_bad_ref_still_404_not_a_null_resolved_ref`, and
`test_truncated_tree_still_reports_resolved_ref` — the last guarding the inverse error, since
truncation is a partial answer for a ref GitHub *did* resolve and must keep `resolved_ref`
populated. Suite: **59 passing**, up from 51. Success path and fallback re-confirmed live on
the authenticated quota.

#### Milestone 2 status — CLOSED, 2026-08-17 (third pass)

**Every success criterion is PASS. Both named failure signals are eliminated. Milestone 2 is
recorded as closed.**

Resolved across the three passes:
- Scope split: persistence and the tree UI moved to Milestone 4 (first pass).
- Smoke coverage (plan V1): PASS — `smoke.md` Run 1, six repos plus three error cases.
- Diagnostics visibility: moved to Milestone 7, where it belongs — relocated, not waived
  (second pass).
- `resolved_ref` honesty: fixed and tested (third pass).

Caveats carried forward, recorded as notes rather than blockers:
- The truncation path has only ever run against mocked responses; the largest tree retrieved
  live was 37,393 entries and GitHub did not truncate it.
- Nesting depth cannot be demonstrated from the response, because only the first 50 entries
  are exposed.
- Tree-404 cause attribution is status-code-only; see the empty-repo caveat in `smoke.md`,
  which is reasoned and not observed.

Retrieval, error honesty, status mapping, test coverage and smoke coverage are all complete.

---

## Milestone 3 – File selection evals

### Test set
Use mixed repositories containing:
- markdown,
- notebooks,
- source code,
- JSON files,
- text files,
- binaries,
- vendor or dependency directories.

### What to verify
- Supported files are selected.
- Unsupported files are skipped.
- Skip reasons are present.
- No important readable files are accidentally excluded.

### Success criteria
- File classification is consistent.
- Every skipped file has a reason.
- There are no silent omissions.

### Suggested score
- PASS if selection is accurate and explainable.
- PASS WITH NOTES if a few borderline files need refinement.
- FAIL if classification is noisy or opaque.

---

### Recorded verdict — 2026-08-17

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **162 passing**. Live results are
`smoke.md` Run 2.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| File classification rules | plan D1 | PASS | `core/selection.py:classify_entry`, nine-step documented precedence |
| Supported file extension list | plan D2 | PASS | `config.py:SelectionConfig`, from spec.md 7.3 as amended 2026-08-17 |
| Skip reason schema | plan D3 | PASS | `selection.py:SkipReason`, closed enum of six; `test_every_skip_reason_in_the_enum_is_reachable` proves none is dead |
| Tests for common repo layouts | plan D4 | PASS | `tests/test_selection.py` (mixed, notebook, binary, vendored, oversized); `smoke.md` Run 2 on two live repos |
| Markdown, code, notebooks, text, JSON recognised | plan E1 | PASS | `test_supported_extensions_are_selected`; live 30/30 on the notebook-heavy repo |
| Obvious binaries and junk skipped | plan E2 | PASS | `test_each_skip_reason_fires`; live `non_text_asset: 7` on `psf/requests` |
| Every skipped file has a reason | plan E3 | PASS | `test_skipped_files_always_carry_a_code_and_a_message` asserts code **and** message on every skip, and that the message is not merely the code restated |
| Test mixed repos | plan V1 | PASS | `MIXED_TREE` covers 19 entries across every status; `smoke.md` Run 2 |
| Test notebook-heavy repos | plan V2 | PASS | live: `quantum-toybox`, 30 selected of 40 entries, 10 directories, 0 skipped |
| Test binary-heavy repos | plan V3 | PASS *(revised, see below)* | `smoke.md` Run 3: `twitter/twemoji`, 7,413 entries, `non_text_asset` 7,378 of 7,389 skips |
| Confirm no silent file drops | plan V4 | PASS | `accounts_for_every_entry()` (`selection.py`); `test_every_entry_lands_in_exactly_one_status`, `test_counts_sum_to_the_total_entry_count`; live `True` on both repos |
| Supported files are selected | evals | PASS | as plan E1 |
| Unsupported files are skipped | evals | PASS | as plan E2 |
| Skip reasons are present | evals | PASS | as plan E3 |
| **No important readable files accidentally excluded** | evals | PASS *(revised, see below)* | `smoke.md` Run 3: residue swept to 16, all decided |
| File classification is consistent | evals | PASS | precedence is fixed and tested in six cases (`test_position_beats_extension`, `test_lockfile_beats_supported_extension`, `test_size_is_checked_last_...`) |
| Every skipped file has a reason | evals | PASS | as plan E3 |
| There are no silent omissions | evals | PASS | as plan V4 |

#### "No important readable files accidentally excluded" — judged on `psf/requests`

Measured live: **153 entries, 23 directories, 100 selected, 30 skipped, 0 failed.** The 30
skips are 7 `non_text_asset` and 23 `unsupported_extension`. Before the 2026-08-17 spec
amendment the same repository produced 72 `unsupported_extension`; widening the list closed
49 of them.

The 23 that remain, by extension:

| Extension | Count | Is it "important readable"? |
|---|---|---|
| `.key` | 4 | TLS test fixtures — not prose, code or config |
| `.cnf` | 4 | OpenSSL fixture configs. **Borderline**: readable text config, arguably should be selected |
| *(extensionless)* | 3 | unrecognised names, correctly skipped by the closed-set rule |
| `.csr` | 3 | certificate requests — not readable content |
| `.pem` | 3 | certificates — not readable content |
| `.crt`, `.srl` | 2 | certificates — not readable content |
| `.css` | 1 | deliberately unsupported per spec.md 7.3 |
| `.html` | 1 | deliberately unsupported per spec.md 7.3 |
| `.bat` | 1 | **Borderline**: a shell script equivalent; `.sh` is supported, `.bat` is not |
| `.typed` | 1 | PEP 561 marker; its *existence* is the signal, its content is empty |

**This was judged PARTIAL on 23.** Nineteen were correctly skipped or deliberately out of
scope, but `.cnf`, `.bat` and `py.typed` were excluded by omission rather than decision.

#### Second pass — 2026-08-17: both PARTIALs closed

**"No important readable files accidentally excluded" — now PASS.** The second spec.md 7.3
amendment added `.cnf` (key=value config, structurally identical to the already-supported
`.ini`/`.cfg`), `.bat` (the Windows counterpart of the already-supported `.sh` — asymmetry,
not judgement), and `py.typed` / `.nojekyll` by filename (zero-byte markers whose existence
is the signal; supporting them was chosen over skipping them under a code that would have
called them "unsupported" when they are merely empty).

Re-measured live, `smoke.md` Run 3: `psf/requests` moved from 100 selected / 23 unsupported
to **107 selected / 16 unsupported**. The remaining 16 are each traceable to a written
decision — 14 credential-shaped TLS fixtures (`.key` ×4, `.csr` ×3, `.pem` ×3, `ca` ×2,
`.crt`, `.srl`) deferred to the `CREDENTIAL_LIKE` proposal in `plan.md`, plus `.css` and
`.html`, listed in spec.md 7.3 as deliberately unsupported. The criterion is *accidentally*
excluded; nothing in the residue is now accidental. Driving the count to zero was never the
target.

**"Test binary-heavy repos" — now PASS.** `twitter/twemoji` added to the smoke suite and run
live: 7,413 entries, `non_text_asset` dominant at 7,378 of 7,389 skips (99.9%), retrieved
untruncated in 2.4 s. The accounting identity held at that scale —
`7 + 17 + 7389 + 0 == 7413` — which was the property most at risk from a repository this
size.

#### Milestone 3 status — CLOSED, 2026-08-17

**Every criterion is PASS. Milestone 3 is recorded as closed.**

Caveats carried forward, recorded as notes rather than blockers:
- No live sample is a *balanced* mixed repository. `twemoji` skips almost everything,
  `quantum-toybox` skips nothing; `psf/requests` is the only live repo exercising several
  skip reasons at once.
- `CREDENTIAL_LIKE` is recorded, not built: the 14 credential-shaped files above are skipped
  correctly but under a blander reason than they deserve. Deferred with its false-positive
  question open — it cannot be settled before file content is retrievable (Milestone 5). See
  `plan.md`, Milestone 3, "Candidate for a later milestone".
- Directory matching is case-sensitive while filename matching folds. This is a deliberate
  asymmetry, recorded in `plan.md` under "Recorded decision", because the failure modes are
  not symmetric: a wrongly folded directory silently removes an entire subtree.

---

## Milestone 4 – Persistence and tree view evals

Scope moved out of Milestone 2 by the 2026-08-17 amendment in `plan.md`.

### What to verify
- A run is written to SQLite and survives an app restart.
- Recent runs can be listed and reopened.
- The tree view shows the retrieved tree for a stored run.
- A tree that GitHub truncated is displayed as incomplete, not as a full listing.
- No token is written to the database.

### Success criteria
- Stored run metadata matches what the API returned.
- Restarting the app loses nothing.
- The truncation state survives persistence.

### Failure signals
- Runs that vanish on restart.
- A stored truncated tree displayed as if complete.
- Secrets in the database.

---

## Milestone 5 – Extraction and normalization evals

### Test set
Use files like:
- `.md`,
- `.py`,
- `.json`,
- `.txt`,
- valid `.ipynb`,
- malformed `.ipynb`.

### What to verify
- Markdown and text are readable after normalization.
- Code files preserve code structure.
- Notebook markdown and code cells are separated correctly.
- Malformed files fail gracefully.

### Success criteria
- Extracted chunks are tied back to source paths.
- Notebook extraction preserves cell boundaries.
- Malformed inputs do not crash the run.

### Failure signals
- Broken notebook parsing.
- Chunks with no file traceability.
- Empty extraction output for readable files.

---

## Milestone 6 – Summary generation evals

### Evaluation set
Run summaries on several known repos with different structures.

### What to verify
- Summary explains the repo purpose.
- Summary mentions major modules or directories when present.
- Summary does not invent unsupported details.
- Summary acknowledges limited coverage when the repo is sparse or partially unreadable.

### Rubric
Score each summary from 1 to 5 on:

- **Grounding** – is it faithful to extracted content?
- **Coverage** – does it capture the main structure?
- **Clarity** – can a human read it easily?
- **Honesty** – does it avoid overclaiming?
- **Usefulness** – would the summary help someone explore the repo?

### Success criteria
- No hallucinated components.
- No summary claims about unseen files.
- Limitations are clearly stated when needed.

### Suggested score thresholds
- **5** – excellent, grounded, useful, and honest.
- **4** – strong overall, minor omissions.
- **3** – usable but incomplete or a bit generic.
- **2** – weak grounding or overconfident.
- **1** – unreliable or misleading.

---

## Milestone 7 – Diagnostics evals

### What to verify
- The diagnostics view shows each major stage.
- Skipped files and failure reasons are visible.
- Partial success is explicitly represented.
- Error cases are understandable without reading logs.

### Success criteria
- Every meaningful failure has a trace.
- Diagnostics help explain what happened.
- The system does not hide limitations.
- Rate-limit conditions are visible in diagnostics.
  *(Moved intact from Milestone 2 by the 2026-08-17 amendment in `plan.md`, second pass:
  Milestone 2 detects and surfaces rate limits, but builds no diagnostics to show them in.)*

### Failure signals
- Missing stage events.
- Empty or vague diagnostics.
- Runs that appear successful despite major failures.

---

## Milestone 8 – API evals

### What to verify
- Endpoints return correct JSON.
- Endpoints are stable and predictable.
- Missing resources return clean errors.
- API can be used programmatically without guessing response shape.

### Success criteria
- All documented endpoints behave as expected.
- Error formats are consistent.
- API contracts do not change silently.

### Suggested checks
- `POST /api/analyze`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/tree`
- `GET /api/runs/{run_id}/files`
- `GET /api/runs/{run_id}/chunks`
- `GET /api/runs/{run_id}/diagnostics`

---

## Milestone 9 – UI evals

### What to verify
- A user can complete the whole flow from the browser.
- The UI makes the current run status obvious.
- The summary, tree, files, and diagnostics are easy to find.
- Empty, loading, and error states are clear.

### Success criteria
- A first-time user can use the app without reading code.
- Navigation is simple and consistent.
- The UI feels like a tool, not a prototype shell.

### Failure signals
- Hidden controls.
- Broken navigation.
- States that are visually indistinguishable.
- Confusing or cluttered layouts.

---

## Milestone 10 – Hardening evals

### What to verify
- Fresh clone setup works.
- Basic test suite passes.
- Smoke tests work on multiple sample repos.
- Logs are readable and not noisy.
- The app can be restarted and still function normally.

### Success criteria
- Setup instructions match reality.
- Project is stable enough for continued development.
- v0.1 can be shown confidently as a working baseline.

---

## Recommended smoke test suite

Maintain a small repo list for repeatable smoke testing:
- a tiny repo,
- a medium repo,
- a notebook-heavy repo,
- a docs-heavy repo,
- a nested multi-directory repo,
- one intentionally bad/nonexistent repo.

For each smoke run, record:
- URL,
- outcome,
- file count,
- chunk count,
- summary quality notes,
- diagnostics issues,
- any manual observations.

---

## Release baseline rule

RepoBridge v0.1 should not be treated as ready until:

- the app starts reliably,
- GitHub validation and retrieval work,
- file selection and extraction are correct enough,
- summary generation is grounded,
- diagnostics are visible,
- the UI is usable,
- and the smoke suite passes with acceptable quality.

If a feature cannot be evaluated, it is not production-minded enough yet.