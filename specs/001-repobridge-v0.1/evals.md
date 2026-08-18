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
| Supported file extension list | plan D2 | PASS | `config.py:SelectionConfig`, from `selection.md` as amended 2026-08-17 |
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
| `.css` | 1 | deliberately unsupported per `selection.md` |
| `.html` | 1 | deliberately unsupported per `selection.md` |
| `.bat` | 1 | **Borderline**: a shell script equivalent; `.sh` is supported, `.bat` is not |
| `.typed` | 1 | PEP 561 marker; its *existence* is the signal, its content is empty |

**This was judged PARTIAL on 23.** Nineteen were correctly skipped or deliberately out of
scope, but `.cnf`, `.bat` and `py.typed` were excluded by omission rather than decision.

#### Second pass — 2026-08-17: both PARTIALs closed

**"No important readable files accidentally excluded" — now PASS.** The second `selection.md`
amendment added `.cnf` (key=value config, structurally identical to the already-supported
`.ini`/`.cfg`), `.bat` (the Windows counterpart of the already-supported `.sh` — asymmetry,
not judgement), and `py.typed` / `.nojekyll` by filename (zero-byte markers whose existence
is the signal; supporting them was chosen over skipping them under a code that would have
called them "unsupported" when they are merely empty).

Re-measured live, `smoke.md` Run 3: `psf/requests` moved from 100 selected / 23 unsupported
to **107 selected / 16 unsupported**. The remaining 16 are each traceable to a written
decision — 14 credential-shaped TLS fixtures (`.key` ×4, `.csr` ×3, `.pem` ×3, `ca` ×2,
`.crt`, `.srl`) deferred to the `CREDENTIAL_LIKE` proposal in `plan.md`, plus `.css` and
`.html`, listed in `selection.md` as deliberately unsupported. The criterion is *accidentally*
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

### Recorded verdict — 2026-08-18

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **223 passing**. Live results are
`smoke.md` Run 5.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| SQLite persistence in `infra/schemas.py` and `infra/db.py` | plan D1 | PASS | `infra/schemas.py` (2 tables), `infra/db.py` (engine/session), `infra/storage.py` (reads/writes) |
| A run record is created when `/api/analyze` runs | plan D2 | PASS | `routes_runs.py`; `test_analyze_returns_a_run_id_and_stores_the_run`; live 3/3 repos in Run 5 |
| A tree view in the UI, reading from the database | plan D3 | PASS | `templates/tree.html`, route in `main.py`; `test_tree_page_states_what_fraction_it_shows`; live on all three repos |
| A run survives a restart and can be reopened | plan E1 | PASS | `test_run_survives_a_restart` (file DB, engine disposed and reopened) **and** a two-process live restart recorded in `smoke.md` Run 5: run written by pid 19172, reopened intact by pid 17868 |
| Recent runs can be listed | plan E2 | PASS | `GET /api/runs` and the home page table; `test_runs_list_is_newest_first`, `test_index_renders_and_lists_recent_runs`; live after restart |
| Tree view reflects what was retrieved, including truncation | plan E3 | PASS | `test_tree_page_of_a_truncated_run_warns`, `test_truncated_run_detail_page_says_it_is_incomplete`. **Mock-only** — see caveat below |
| No secrets written to the database | plan E4 | PASS | `test_schema_has_no_token_column`, `test_no_token_value_is_written_anywhere` (sets a real-shaped token and scans every stored value) |
| Create a run, restart, confirm still listed and readable | plan V1 | PASS | two-process live restart, `smoke.md` Run 5 |
| Stored metadata matches what the API returned | plan V2 | PASS | `test_analyze_returns_a_run_id_and_stores_the_run`; live: stored counts equal the analyze response for all three repos |
| Tree view renders a real retrieved tree; truncation warning shown | plan V3 | PASS (render) / **mock-only** (truncation) | live render on 40, 153 and 37,393-entry repos; the truncation banner has never been exercised against a genuinely truncated repo |
| A run is written to SQLite and survives an app restart | evals | PASS | as plan E1 |
| Recent runs can be listed and reopened | evals | PASS | as plan E2 |
| The tree view shows the retrieved tree for a stored run | evals | PASS | as plan D3 |
| A truncated tree is displayed as incomplete, not as a full listing | evals | PASS | as plan E3, mock-only |
| No token is written to the database | evals | PASS | as plan E4 |
| Stored run metadata matches the API response | evals | PASS | as plan V2 |
| Restarting the app loses nothing | evals | PASS | two-process restart: 153 rows, identity true, home and tree pages both render |
| The truncation state survives persistence | evals | PASS | `test_truncated_run_persists_the_flag`, `test_truncated_tree_is_stored_and_does_not_read_back_as_complete` |

#### Scale honesty — judged against `kubernetes/kubernetes`

Not a plan.md criterion; added as a slice requirement because a 37,393-entry repository
cannot render at once and a page that hides that fact would repeat the `tree_truncated`
defect at the presentation layer.

Live, `kubernetes/kubernetes`, 37,393 stored entries:

| View | Scope line |
|---|---|
| unfiltered, page 1 | `Showing 1–100 of 37393 entries.` |
| unfiltered, last page | `Showing 37301–37393 of 37393 entries.` |
| `path=staging/src/k8s.io/api/core/v1/types.go` | `Showing 1–1 of 1 matching entries (of 37393 in this run).` |
| `path=vendor/golang.org` | `Showing 1–100 of 1007 matching entries (of 37393 in this run).` |
| `path=vendor/` + `status=skipped` | `Showing 1–100 of 5574 matching entries (of 37393 in this run).` |
| no matches | `Showing 0 of 37393 entries in this run.` |

**PASS.** The line is unconditional — rendered even when the list fits — so a reader never
infers completeness from its absence. With any filter active it names *both* the match count
and the run total, so `1` cannot be read as the size of the repository. The zero-match case
still states the run total rather than an unqualified "0 entries".

The path filter is what makes this usable rather than merely honest: 37,393 entries is 374
pages of prev/next, so "was `staging/src/k8s.io/api/core/v1/types.go` skipped, and why" was
previously answerable only through the API. It now returns one row, `skipped /
unsupported_extension`, with its message.

#### Milestone 4 status — CLOSED, 2026-08-18

**Every criterion is PASS. Milestone 4 is recorded as closed.**

Caveats carried forward, recorded as notes rather than blockers:
- **The truncation banner is mock-only.** No repository retrieved so far has been truncated
  by GitHub — the largest is 37,393 entries against a threshold near 100k. The stored flag,
  the persistence of it, and both UI warnings are covered by tests, but the end-to-end path
  from a genuinely truncated GitHub response to the rendered banner has never run. This is
  the same caveat carried since Milestone 2.
- **No migrations.** `create_all()` never alters an existing table, so a database predating
  a schema change fails with `OperationalError` on first query rather than degrading. Deleting
  the file is currently the fix. Acceptable only while no database holds real history.
- **Deep offsets degrade.** Page 374 of kubernetes is measurably heavier than page 1, because
  SQLite walks the offset. The path filter removes most of the need to page deeply, but does
  not fix the mechanism.

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

### Recorded verdict — 2026-08-18

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **293 passing**. Live results are
`smoke.md` Run 6.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| Markdown/text extractor | plan D1 | PASS | `core/extraction.py:extract_file`; `test_markdown_becomes_a_markdown_chunk`, `test_plain_text_and_rst_become_text_chunks`; live `01_bell_state/README.md` byte-identical to source |
| Code file extractor | plan D2 | PASS | `test_python_preserves_code_structure` asserts text equals source verbatim including indentation; `test_code_formats_are_code_chunks` for `.js`/`.ts`/`.sh`/`.bat` |
| Notebook parser | plan D3 | PASS | `core/extraction.py:extract_notebook`; 11 notebook tests; live cell-by-cell comparison below |
| Chunk model and persistence | plan D4 | PASS | `AnalysisChunk` in `infra/schemas.py`, `storage.persist_extraction`; `test_chunks_endpoint_returns_traceable_chunks`; live 127 chunks stored and read back |
| Notebook markdown and code cells preserved distinctly | plan E1 | PASS | `test_notebook_markdown_and_code_cells_stay_distinct`; live: 6/6 cells matched type exactly |
| Extracted content readable and linked to source paths | plan E2 | PASS | `source_path` and `chunk_index` are NOT NULL in the schema; `test_every_chunk_carries_its_source_path_and_position`; live preview shows both |
| Malformed files fail gracefully | plan E3 | PASS | `test_malformed_notebooks_raise_a_specific_error` (4 shapes); `test_a_malformed_notebook_does_not_end_the_run` — the run stays `completed` |
| Compare extracted output with source files | plan V1 | PASS | Live byte-for-byte: README.md 868 chars in, 868 out, identical after CRLF normalisation; notebook cells compared individually against the raw `.ipynb` JSON — index, type and text all match |
| Test malformed notebook handling | plan V2 | PASS | four malformed shapes plus a malformed *cell* inside a valid notebook |
| Verify chunk counts and source links | plan V3 | PASS | `test_chunks_from_all_files_are_collected_and_traceable`; live 127 chunks across 30 files, every one carrying its path |
| Markdown and text readable after normalisation | evals | PASS | as plan D1; CRLF normalised (`test_crlf_is_normalised`) |
| Code files preserve code structure | evals | PASS | as plan D2 |
| Notebook cells separated correctly | evals | PASS | as plan E1 |
| Malformed files fail gracefully | evals | PASS | as plan E3 |
| Extracted chunks tied back to source paths | evals | PASS | as plan E2 |
| Notebook extraction preserves cell boundaries | evals | PASS | live: 7 source cells, 1 empty, 6 chunks, `cell_index` values `[0,1,2,3,4,5]` matching the source positions |
| Malformed inputs do not crash the run | evals | PASS | as plan E3; also non-UTF-8 content (`test_non_utf8_content_is_a_per_file_failure`) |

#### The three named failure signals

**"Broken notebook parsing" — eliminated.** Verified live against a real notebook rather
than a fixture: `01_bell_state/basic_qiskit_implementation.ipynb` has 7 cells, one empty.
Extraction produced 6 chunks, and every one matched the source cell exactly on **index,
type and text**:

```
cell 0  code      src  133 chars | chunk 0  notebook_code      133 chars | text equal: True
cell 1  markdown  src  638 chars | chunk 1  notebook_markdown  638 chars | text equal: True
cell 2  code      src  299 chars | chunk 2  notebook_code      299 chars | text equal: True
...
```

**"Chunks with no file traceability" — eliminated structurally.** `source_path` and
`chunk_index` are `NOT NULL` columns, so an untraceable chunk cannot be stored; notebook
chunks additionally carry `cell_index`. The run detail page surfaces all three.

**"Empty extraction output for readable files" — not observed, with one deliberate
exception.** `py.typed` and `.nojekyll` are selected and produce zero chunks, which is
correct: they are zero-byte marker files whose existence is the signal (see
`selection.md`). No file with actual content produced empty output in any run.

#### Milestone 5 status — CLOSED, 2026-08-18

**Every criterion is PASS. Milestone 5 is recorded as closed.**

Caveats carried forward, recorded as notes rather than blockers:
- **A capped run reads the alphabetically-first N files, not the most useful N.** Recorded
  as an open item in `plan.md` under Milestone 5; it is a ranking question for Milestone 6,
  and the run reports the cap honestly in the meantime.
- **No size-based chunk splitting.** One chunk per file except notebooks, because no token
  budget exists to split against until summarisation. `chunk_index` is already recorded, so
  adding splitting later does not change the model.
- **The token estimate is `chars // 4`**, a heuristic and not a tokenizer.
- **The read cap has never been hit live.** Both smoke repos are under 200 selected files;
  the cap path is covered by tests only.

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

### Recorded verdict — 2026-08-18

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **414 passing**. The live result is
`smoke.md` Run 7 — **one** summary, on `Pushkar0997/quantum-toybox`, on
`gemini-3.5-flash-lite`.

**Read the evidence column carefully.** A test can prove what the *inventory* and the
*prompt* contain, because those are computed before the model is called and are mocked
end to end. A test cannot prove what the *model wrote*, because in every test the model is
a stub. Criteria about the prose therefore rest on live results, and there is one.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| Summarization service | plan D1 | PASS | `core/summarization.py:summarise`; 100+ tests across four files; live Run 7 returned `status: ok` |
| Summary prompt/template | plan D2 | PASS | `SYSTEM_INSTRUCTIONS` + `build_prompt`; `test_prompt_states_what_was_read_and_what_was_not`, `test_prompt_includes_chunk_provenance_headers`, `test_prompt_says_nothing_was_missed_when_nothing_was` |
| Summary result persistence | plan D3 | PASS | `summary_*` columns in `infra/schemas.py`, `storage.persist_summary`; `test_summary_is_persisted_and_readable_via_the_endpoint`; live: stored text, model and provenance all read back identical |
| Summary describes repo purpose and major structure | plan E1 | PASS | Live: named the repository's purpose ("notebook-first Qiskit playground"), all ten numbered directories by their scheme, and the per-folder README/notebook layout. Checked against the stored inventory: exactly 10 directories, `01_bell_state` … `10_error_correction`, one `README.md` in each |
| Summary does not invent unseen details | plan E2 | PASS | Live, checked claim by claim against `analysis_chunks` — see the grounding audit below. Zero unsupported claims. Structurally: `build_provenance` is computed from the inventory before the call and cannot be altered by the model |
| Summary mentions limitations when coverage is sparse | plan E3 | **PARTIAL** | The **mechanism** is fully tested — the shortfall reaches both provenance and prompt for the cap, truncation, budget and read-failure cases (`test_capped_run_discloses_the_cap_in_the_summary`, `test_truncated_tree_is_disclosed_in_the_summary`, `test_token_budget_shortfall_is_disclosed`, `test_read_failures_are_disclosed`). But **no live summary has been generated for a partially-covered run**: Run 7 had `is_partial: false`, `limitations: []`. What the model actually writes when coverage *is* sparse has never been observed |
| Run summary on known repos | plan V1 | **PARTIAL** | One repository, not "repos". `quantum-toybox` only |
| Review whether claims are supported by extracted content | plan V2 | PASS | Done mechanically rather than by eye — the grounding audit below queries the stored chunks for every term the summary used |
| Verify limitation handling | plan V3 | **PARTIAL** | As E3: verified in the inventory and the prompt, not in a live summary |
| Summary explains the repo purpose | evals | PASS | as plan E1 |
| Summary mentions major modules or directories when present | evals | PASS | as plan E1; all ten directories accounted for |
| Summary does not invent unsupported details | evals | PASS | as plan E2 |
| Summary acknowledges limited coverage when sparse or partially unreadable | evals | **PARTIAL** | as plan E3 |
| No hallucinated components | evals success | PASS | grounding audit below: every named component exists in the stored content |
| No summary claims about unseen files | evals success | PASS | The one live summary named nothing outside what was read; nothing was skipped or unread on that run, which also makes it the *weakest possible test* of this criterion — there were no unseen files to claim about |
| Limitations are clearly stated when needed | evals success | **PARTIAL** | as plan E3. "When needed" has not yet arisen live |
| Rubric scored across several repos with different structures | evals | **PARTIAL** | Scored for one summary below; the evaluation set asks for several |

#### The grounding audit

Rather than reading the summary and judging it plausible, every substantive claim was
checked against `analysis_chunks` and `analysis_files` for that run:

| Claim in the summary | Checked against the stored inventory | Result |
|---|---|---|
| "ten numbered folders" | `select count(*) … status='directory'` | **10** exactly |
| "`01_bell_state` and `02_superposition_explorer` through to `10_error_correction`" | stored directory paths | all three exist, and the ten are contiguously numbered |
| teleportation, Deutsch, Bernstein-Vazirani, Grover, QFT and inverse QFT, QPE with a T-gate, VQE optimizers, bit-flip and phase-flip correction | substring search of stored chunk text | every term present, 2–10 chunks each |
| "a markdown README" in each folder | `README.md` per directory | **10 of 10** folders have exactly one |
| "self-contained executable Jupyter notebooks" | chunk types | 115 of 127 chunks are `notebook_code`/`notebook_markdown` |
| "depend on qiskit, qiskit-aer, and matplotlib as specified in requirements.txt" | stored text of `requirements.txt` | exactly `qiskit`, `qiskit-aer`, `matplotlib` — three named, three present, none invented |

**No unsupported claim was found.** The summary also named *exactly* the three
dependencies rather than padding with plausible ones, which is the failure mode this
criterion is really about.

#### Rubric, the one summary scored

| Dimension | Score | Why |
|---|---|---|
| Grounding | 5 | Every claim traced to stored content; nothing invented |
| Coverage | 5 | Purpose, all ten directories, the per-folder structure, and the dependencies |
| Clarity | 5 | Three paragraphs, plain prose, no headings or padding, as the prompt asks |
| Honesty | 4 | It opened by stating coverage was complete — accurate, and it did not manufacture a caveat it did not have. Not 5: the case that would earn a 5 is *sparse* coverage stated plainly, and that case has not been run |
| Usefulness | 5 | A reader deciding whether to open this repository learns what it is, how it is arranged, and what it needs |

**One summary at 4.8/5 is a good result and a small sample.** It is the easiest input in the
smoke suite: 40 entries, nothing skipped, nothing capped, nothing truncated, complete
coverage. The rubric exists to be run on harder shapes.

#### What is proven, and what is only mechanised

Worth stating plainly, because the distinction is the whole basis of the PARTIALs above.

**Proven and model-independent.** Provenance is computed from the run's inventory *before*
the provider is called, travels with the prose, and is stored beside it. Its accuracy does
not depend on the model behaving, and it is what a reader checks the prose against. Runs
with no content never reach the provider at all
(`test_a_run_with_no_chunks_never_calls_the_provider`), so a summary cannot be invented
from metadata. Both hold regardless of which model is configured or which attempt
succeeded.

**Mechanised but not observed.** That the *prompt* states the shortfall is tested. That the
*model writes it down* is not — and cannot be, in a suite where the provider is a stub. One
live summary exists and it had nothing to disclose.

#### Milestone 6 status — **NOT CLOSED**, 2026-08-18

**Four criteria are PARTIAL and they are the same gap seen four ways: exactly one live
summary exists, and it was generated for a run with complete coverage.** Every criterion
about the machinery passes. The criteria about what the model actually writes rest on a
sample of one, taken on the easiest input available.

This is not rounded up to closed. The specification's own strongest claim — that a summary
"must acknowledge limitations when coverage is sparse" — has never been observed happening.
The honest reading is that grounding is *enforced* (provenance, refusal to summarise
nothing) and *demonstrated once*, on a run with no limitations to acknowledge.

**What closes it**, and it is now cheap — the 2026-08-18 provider amendment moved the
default to a 500-requests/day model, so this costs 4 requests out of 500 rather than 4 out
of 20:

1. **A live summary of a capped run.** Set `REPOBRIDGE_MAX_FILES_PER_RUN` low against
   `psf/requests` (107 selected) and check whether the prose says how much it did not read.
   This also exercises the read cap live for the first time — a caveat carried since
   Milestone 5.
2. **A live summary of a large partially-read repository.** `github/docs` (11,215 selected,
   200 read) is the real shape of the problem, and the one where an ungrounded summary
   would be most damaging.
3. **A live summary of a sparse repository.** `octocat/Hello-World` selects one file; the
   criterion "say plainly that the content is too sparse to characterise" is otherwise
   untested against a model.
4. **A live summary of a code-shaped repository.** Everything so far is notebooks and
   prose; `psf/requests` at full coverage would score the rubric on a different structure.

Record each in `smoke.md` with the rubric scored, then revise this verdict in a second
pass — the pattern Milestone 3 used when its two PARTIALs were closed.

**Caveats that would carry forward even once it closes:**
- **Summary quality is a single-model observation.** Nothing compares `gemini-3.5-flash-lite`
  against `gemini-3.7-flash`, and the model is now configurable, so a reader may be running
  a model this verdict never saw.
- **Truncation disclosure remains mock-only end to end**, as it has since Milestone 2: no
  repository retrieved so far has been truncated by GitHub.
- **The token estimate is `chars//4`**, so `tokens_estimated` in any provenance is
  approximate and is labelled as such in the record itself.

#### Second pass — 2026-08-18: four PARTIALs closed, one criterion downgraded

The four runs the first pass asked for were made — `smoke.md` Run 8, four summaries, four
provider requests, one per case. Test suite at time of this pass: **414 passing**.

**Every coverage PARTIAL closes.** All four rested on the same gap: one live summary, on a
run with complete coverage and nothing to disclose. There are now five live summaries
across four repositories, three of them partially covered.

| Criterion | Was | Now | Why |
|---|---|---|---|
| Summary mentions limitations when coverage is sparse (plan E3) | PARTIAL | **PASS** | Three of the four runs had limitations; all three stated them in the first sentence with figures from the provenance. `psf/requests` capped: "out of 153 repository entries and 107 selected readable files, exactly 20 files were read". `github/docs`: "11,017 selected files were not read due to a read limit of 200 files, and 82 extracted chunks exceeded the token budget" |
| Run summary on known repos (plan V1) | PARTIAL | **PASS** | Five summaries, four repositories, four different shapes: notebooks, a capped code repo, a 14,903-entry docs site read at 1.8%, and a one-file repo |
| Verify limitation handling (plan V3) | PARTIAL | **PASS** | The read cap and the token budget both fired live for the first time — cap on two runs, budget on two — and both were disclosed in provenance and in prose |
| Summary acknowledges limited coverage when sparse or partially unreadable (evals) | PARTIAL | **PASS** | The `octocat/Hello-World` case is the decisive one: `is_partial: false` and `limitations: []`, so there was no mechanical limitation to lean on, and the model still wrote "it is not possible to further characterise the repository or its organisation" rather than padding. That is `SYSTEM_INSTRUCTIONS` rule 5 obeyed with nothing forcing it |
| Limitations are clearly stated when needed (evals success) | PARTIAL | **PASS** | as above |
| Rubric scored across several repos (evals) | PARTIAL | **PASS** | Five summaries scored; four in Run 8 at 3.2, 4.8, 4.8, 4.8 |
| **No summary claims about unseen files (evals success)** | **PASS** | **PARTIAL** | **Downgraded. See the finding below.** |

#### The finding that downgrades a criterion

**A capped summary generalised from an unrepresentative sample.** Full detail in `smoke.md`
Run 8; the essentials:

`psf/requests` capped at 20 files read **18 `.github/` files** plus `.coveragerc` and
`.git-blame-ignore-revs`, because the cap takes the alphabetically-first N selected files.
`README.md` and every module of `src/requests/` were `not_fetched`. The summary disclosed
that accurately — exact figures, first sentence — and then wrote:

> "The project organisation is heavily structured around GitHub infrastructure and
> automation."

**Every individual fact in that summary is grounded; the characterisation is not.** It
describes the organisation of a project 81% of whose readable files were never opened, and
it is materially wrong about `psf/requests`, whose organisation is `src/requests/`, `docs/`
and `tests/`. The mechanical audit found no invented file, no invented module and no named
file that was not read — the failure is not hallucination, it is **overgeneralisation from
a sample the run itself knew was partial**.

Judged against the criterion "no summary claims about unseen files", this is a claim whose
subject is the whole repository while its evidence covers a fifth of it. It does not
violate the letter of `SYSTEM_INSTRUCTIONS` — no unread file is named or speculated about —
which is exactly why it is recorded rather than dismissed: **the rules as written permit a
summary that misleads.**

**The cause is not the summariser.** The control case proves it: `github/docs` read **1.8%**
and characterised the repository correctly, because a docs site is docs-shaped throughout,
so an alphabetical slice is representative. `psf/requests` is not, and its alphabetical
slice is the CI shell. The variable is **which files the cap chose**, which is the open item
already recorded in `plan.md` under "Milestone 5 — open item: which 200 files a capped run
reads", predicting a summary "grounded in the wrong 2%". Run 8 is that prediction confirmed
live on a real repository.

#### Milestone 6 status — **NOT CLOSED**, 2026-08-18 (second pass)

**Every Milestone 6 criterion now passes except one, and the one that does not is the
finding above.** Stated plainly: the summarisation machinery is correct and, on four of five
live summaries, genuinely good. Grounding enforcement is model-independent and holds. The
sparse case — the one most likely to produce a confident fabrication — produced a refusal to
characterise instead, which is the best result available. Zero hallucinations across five
summaries and 48 mechanically checked claims.

It does not close because a summary this project generated **would mislead a reader about
what `psf/requests` is**, and shipping a milestone whose stated purpose is grounded,
trustworthy summaries while holding that result would be recording the wrong thing. The
finding is worth more than the milestone: it is a real defect, found by evaluation rather
than reasoning, on the exact case that was predicted and had never been run.

**What closes it — one change, then one re-run:**

1. **Rank files for reading the way chunks are ranked for the prompt.**
   `core/summarization.py:rank_chunks` already implements the ranking — README and orienting
   documents first, shallow before deep, `docs/` ahead of `.github/` and `tests/`. Nothing
   equivalent orders the *files* the cap selects; `core/extraction.py` takes a prefix of
   classification order. Applying the same ranking there is the fix, and it closes the
   Milestone 5 open item at the same time.
2. **Re-run the capped `psf/requests` case** and confirm the summary describes an HTTP
   library rather than a CI configuration. One provider request.

Until then the honest statement of where this stands: **RepoBridge's summaries are grounded
and honest about how much they read; a capped summary is not yet reliably representative of
what it read from.** Those are different properties and only the first is currently earned.

**Caveats carried forward regardless:**
- **One model.** All five live summaries are `gemini-3.5-flash-lite`.
- **Truncation disclosure remains mock-only**; `github/docs` at 14,903 entries was still not
  truncated by GitHub.
- **The token estimate is `chars//4`**, labelled as a heuristic in every provenance record.
- **The retry path is now live-verified**, incidentally: the fourth run took a transient 429,
  waited 16.0 s and succeeded. A daily-quota 429 would have failed fast instead, which is the
  discrimination that matters.

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