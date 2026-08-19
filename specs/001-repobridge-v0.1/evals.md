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

#### Third pass — 2026-08-18: the finding fixed, and Milestone 6 closes

The second pass named one change and one re-run. Both were done. Test suite: **439 passing**
(+25, all of them for the ranking and the identity under it). The re-run is `smoke.md` Run 9.

**The change.** `core/ranking.py:rank_files`, applied in `core/extraction.py` before the cap
splits. It reuses the signals already defended for chunk ranking — README and orienting
documents first, shallower paths, `docs/` above `.github/` and `tests/`, prose before code —
which now live in one module shared by both stages so they cannot drift apart. It adds one
signal file ranking needs and chunk ranking does not: **spread across top-level areas**.
That was not a guess; ranking by the signals alone was measured first and still read zero
files of `src/requests/` at a cap of 20, having concentrated on `docs/` instead of
`.github/`. Chunk ranking orders content already read, so nothing can be missing from its
pool; file ranking decides what is read at all.

**The re-run**, same repository, same cap of 20, only the ordering changed:

| | Run 8 (tree order) | Run 9 (rank-ordered) |
|---|---|---|
| `README.md` | not read | read, first |
| `src/requests/` files read | 0 | 3 |
| `.github/` files read | 18 of 20 | 4 of 20 |
| Characterisation | "heavily structured around GitHub infrastructure and automation" | "a simple and elegant HTTP library for Python built for human beings" |
| Claims traced | 15 of 15 | 17 of 17 |
| Provenance figures stated in prose | 3 of 4 | **4 of 4** |
| Rubric mean | 3.2 | **4.6** |

| Criterion | Was | Now | Why |
|---|---|---|---|
| **No summary claims about unseen files (evals success)** | **PARTIAL** | **PASS** | The capped summary now describes the repository correctly from 19% of its files, and describes `src/requests/` as "a core source directory containing the main Python modules" **without naming a module it did not read** — having seen three of twelve. Restraint under partial coverage, which is exactly the criterion. "Heavily structured around GitHub infrastructure" appears nowhere; neither does "automation" |

**Every Milestone 6 criterion is now PASS.**

#### Milestone 6 status — **CLOSED**, 2026-08-18

Six live summaries across five repositories and four repository shapes: notebooks, a capped
code repository, the same repository at full coverage, a 14,903-entry docs site read at
1.8%, a one-file repository, and the capped case again after the fix. **Sixty-five claims
checked mechanically against the text the model actually saw. Zero hallucinated files, zero
hallucinated modules, zero named files that were not read.** Every partially-covered run
disclosed its coverage with figures from its own provenance.

The two results that carry the most weight, because they are the ones that could not be
faked by machinery:

- **`octocat/Hello-World`** had no mechanical limitation to lean on — `is_partial: false`,
  `limitations: []` — and the model still wrote "it is not possible to further characterise
  the repository or its organisation" rather than padding.
- **`psf/requests` capped at 20** now describes an HTTP library, and it does so from a
  sample chosen to be representative rather than alphabetical.

Grounding is enforced structurally — provenance computed from the inventory before the
provider is called, no summary from a run with no content — and demonstrated live across
six summaries. **Both properties the second pass separated are now earned: the summaries are
honest about how much they read, and a capped summary is representative of what it read
from.**

**What closing does not claim.** These are recorded as notes, not blockers, and each is
measured rather than suspected:

- **One model.** All six live summaries are `gemini-3.5-flash-lite`. Nothing compares
  against `gemini-3.7-flash`, and the model is configurable.
- **The coverage paragraph moved to the end in Run 9**, where `SYSTEM_INSTRUCTIONS` rule 3
  asks for it near the start. Complete and exact, but a reader who stops early misses it.
  The single thing most worth watching.
- **Within an area, file order is still the path.** `src/requests/__init__.py` is read
  before `api.py` because of the underscore. It is a good pick for a Python package by luck,
  not because entry points are recognised.
- **Equal round-robin over-weights small peripheral areas** — 4 of 20 slots to `.github/`
  on `psf/requests`, 36 of 200 on `github/docs`. Equal shares were chosen because there is
  no measurement to justify a weighting.
- **`github/docs` was not re-summarised after the ranking change.** Its new file selection
  was measured offline against the stored list and spreads across `content`, `src`, `data`
  and root; spending a request to re-confirm a case that already passed was not justified.
- **Truncation disclosure remains mock-only**, as since Milestone 2.
- **The token estimate is `chars//4`**, labelled as a heuristic in every provenance record.

This also closes the Milestone 5 open item "which 200 files a capped run reads", which is
marked resolved in `plan.md` with the measurement that decided it.

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

### Recorded verdict — 2026-08-19

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **487 passing**, of which **48** are
`tests/test_diagnostics.py`. The live result is `smoke.md` Run 10 — four intentionally
induced failure cases, read off the diagnostics **page** rather than the API payload, with
**zero** summarisation-provider requests.

**Read the evidence column for which kind of proof backs each row.** Tests here are strong
evidence: unlike Milestone 6, nothing in diagnostics depends on what a model wrote, so a
mocked run exercises the real code path end to end. What tests cannot supply is confirmation
that a *real* GitHub failure produces the event we think it does — which is what Run 10 is
for, and where it did not reach, the row says so.

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| Diagnostics event model | plan D1 | PASS | `core/diagnostics.py` — `Stage` (8 members, one per pipeline step), `Level` (4), `DiagnosticEvent`, `Recorder`; `infra/schemas.py:AnalysisEvent` at `SCHEMA_VERSION = 4`, guarded by the existing version check in `infra/db.py` |
| Diagnostics API endpoint | plan D2 | PASS | `GET /api/runs/{run_id}/diagnostics` in `api/routes_diagnostics.py`; verdict, per-level counts, per-stage roll-up, filters, ordered events; `test_the_endpoint_404s_on_an_unknown_run`, plus every payload assertion in the file. Live in all four Run 10 cases |
| Diagnostics UI view | plan D3 | PASS | `ui/templates/diagnostics.html` — banner, count cards, stage strip, filter chips, timeline; `test_the_page_renders_a_timeline`, `test_the_page_makes_a_failed_stage_obvious`, `test_the_page_says_so_when_a_run_is_complete`. Run 10 records the rendered page for all four cases |
| Logging for key stages | plan D4 | PASS | Every event is logged at the moment it is recorded (`Recorder.record`, severity derived from level), from a single call site — so a log line and its timeline row cannot drift apart. Every stage is therefore logged, live in Run 10. `tasks.md`'s broader "logging hooks in core modules" is a separate question about what those modules should say *independently* of the timeline; it is recorded as a **deferred design item** under Milestone 7 in `plan.md`, with its options written down |
| User can see what was accessed, skipped, failed, and why | plan E1 | PASS | Run 10 Case 4 live: entries classified, per-reason skip breakdown (`non_text_asset: 7`, `unsupported_extension: 16`), `read 20 of 107`, `87 not_fetched`. Per-file failures carry their own row keyed by path (`test_a_per_file_failure_is_findable_by_path`) |
| Partial success is clearly visible | plan E2 | PASS | A dedicated `PARTIAL` level, count cards, the stage strip, and events that must carry numbers (`test_a_partial_event_always_carries_numbers`). Live in Run 10 Case 4. **The banner shortfall found by Run 10 is fixed**: failure and partiality are independent conditions and the banner now states both, so a run that is partial *and* degraded is no longer announced solely as "completed with failures". Tested as a combination — `test_the_banner_states_both_conditions_when_a_run_is_partial_and_degraded`, `test_a_failed_run_that_is_also_partial_says_both` — because neither single-condition test caught it, plus two tests that the clause stays additive rather than always-on |
| Errors are not hidden | plan E3 | PASS | `test_a_run_with_failures_never_reports_itself_clean`, `test_filtering_narrows_events_but_never_the_totals`. Live: Run 10 Cases 3 and 4 both report `has_failures: true` while `run_status` is `completed`, so a completed run does not read as clean |
| Trigger failure cases intentionally | plan V1 | PASS | `smoke.md` Run 10: nonexistent repo, nonexistent branch, withheld provider key — three induced failures against live GitHub, plus a deliberately capped run |
| Confirm diagnostics capture the failure | plan V2 | PASS | Run 10, all four cases; every failure appears with a named reason (`not_found`, `ref_not_found`, `not_configured`) |
| Confirm UI displays the run state clearly | plan V3 | PASS | Run 10 records the rendered page for each case. Cases 1 and 2 lead with "This run failed"; Cases 3 and 4 with "This run completed with failures". The state is stated in words, not left to row colour. See E2 for what the banner omits |
| The diagnostics view shows each major stage | evals | PASS | All eight stages emit, asserted by `test_every_stage_of_a_complete_run_is_recorded` and observed live in Run 10 Case 3. A stage that never ran is absent rather than shown healthy (`test_a_stage_that_never_ran_is_absent_rather_than_shown_as_healthy`; live in Case 1, where `tree` and `classification` are absent) |
| Skipped files and failure reasons are visible | evals | PASS | `test_skipped_files_are_visible_with_their_reasons`; live per-reason counts in Case 4. Per-entry detail is delegated to the file listing by design, not omitted — `test_a_large_run_does_not_write_a_row_per_entry` holds a 2,000-entry run under 30 events while keeping the aggregate exact |
| Partial success is explicitly represented | evals | PASS | as plan E2 |
| Error cases are understandable without reading logs | evals | PASS | Every error carries a named `reason` and its status code as fields. **The one path where this was false is now closed**: a named ref that does not exist used to record an ERROR, call `flush_suppressed()`, and discard the entire timeline unpersisted. It now stores a failed run and its events — `test_a_bad_ref_is_an_error_naming_the_ref`, `test_a_bad_ref_leaves_a_readable_run_page`, and live in Run 10 Case 2 |
| Every meaningful failure has a trace | evals success | PASS, one documented exception | Metadata failures, ref failures, tree failures, per-file read failures, per-file parse failures and provider failures all persist. **The exception is URL validation**: a malformed URL is rejected before GitHub is contacted, so there is no repository and no run to attach events to, and its event is deliberately not persisted. That is stated in `routes_runs.py` and in `storage.create_failed_run`, and it is the only unpersisted failure left |
| Diagnostics help explain what happened | evals success | PASS | Run 10 Case 2 is the demonstration: `metadata[info]` beside `tree[error]` tells a reader the repository is real and the ref is not, which no single status code conveys |
| The system does not hide limitations | evals success | PASS | Filters never narrow the totals (`test_filtering_narrows_events_but_never_the_totals`); the cap, the token budget, tree truncation and unread files are all quantified events. The banner shortfall under E2 is a matter of what is *led with*, not of anything being absent |
| **Rate-limit conditions are visible in diagnostics** *(moved from Milestone 2)* | evals success | PASS on tests; **no live confirmation** | Five tests: `test_a_metadata_rate_limit_is_visible_in_diagnostics`, `test_the_rate_limit_event_says_which_quota_and_when_it_resets`, `test_a_tree_rate_limit_degrades_the_run_and_is_visible`, `test_a_secondary_rate_limit_is_distinguished_from_a_primary_one`, and the secret-scan over stored events. The event carries resource, limit, remaining, used, reset epoch, a human-readable reset time, primary-vs-secondary, and whether the request was authenticated — enough to decide between waiting and authenticating. **Source is the failing response's own headers**, not `/rate_limit`, which Run 1 measured as stale. Run 10 did not reproduce a live rate limit: doing so means deliberately exhausting a real quota, and the criterion as written asks for visibility, which the tests establish |

#### The three named failure signals

**"Missing stage events" — eliminated.** `Stage` has exactly one member per step of
`analyze_repo`, so the claim is checkable rather than aspirational, and
`test_every_stage_of_a_complete_run_is_recorded` checks it. Run 10 Case 3 shows all eight
live.

**"Empty or vague diagnostics" — eliminated.** The level set has no `WARNING`, deliberately:
every candidate for it is really either a bounded-but-complete stage (`PARTIAL`) or a stage
that did not complete (`DEGRADED`), and offering both a precise and a vague option guarantees
the vague one gets used. The rule that `PARTIAL` must carry numbers is enforced by
`test_a_partial_event_always_carries_numbers` and visible live in Case 4's `{not_fetched: 87,
read_cap: 20}`.

**"Runs that appear successful despite major failures" — eliminated.** Tested directly, and
Run 10 Cases 3 and 4 are live instances: `run_status: completed` alongside `has_failures:
true` and a `degraded` summarisation row.

#### The four defects found in the pre-milestone audit, and their state

| Defect | State | Backed by |
|---|---|---|
| Re-summarising restarted the sequence at 0, so its events sorted into the middle of the run — "Re-summarising from stored content" displaying before the tree was retrieved | **Fixed.** `storage.persist_events` stamps the run's current maximum via `next_event_sequence`; `list_run_events` orders on `(sequence, id)` so a tie cannot reorder either. Stamped at write time rather than at record time, so a recorder cannot be constructed wrongly | `test_re_summarising_appends_to_the_timeline_rather_than_reordering_it` and `test_re_summarising_twice_keeps_extending_the_same_timeline`, both asserting **order** rather than message content. Live: Run 10 Case 3b, `[0…7]` then `[0…9]` |
| A named ref that does not exist discarded its whole timeline: no run row was created, so `flush_suppressed()` was dead and `persist_events` was never called | **Fixed.** Stores a failed run, consistent with the metadata-404 path, and carries the metadata that *did* succeed so the run distinguishes a wrong ref from a wrong repository. `run_id` travels with the 404 | Three tests; live in Run 10 Case 2 |
| `test_a_bad_ref_is_an_error_naming_the_ref` asserted on a `Recorder` it built itself — true regardless of what the pipeline did | **Replaced.** Now asserts the stored run and its stored timeline: reason `ref_not_found`, the ref named in the message, `run_status: failed`, `resolved_ref: null`, and the rendered page | The test itself, plus two new companions |
| A malformed notebook was filed as `read_failed` at `Stage.CONTENT`; `Stage.EXTRACTION` could emit only INFO and could never report a failure | **Fixed.** `extraction.FailureKind` separates a file that never arrived from one that arrived and would not parse; parse failures are events at `Stage.EXTRACTION` with reason `extraction_failed`, and the two aggregates count only their own kind. Deliberately not a new `ContentStatus` and not a stored column — `content_status` answers "did the content make it into the run", where both answer no, and a column would be a fifth schema version for something the event already carries | Four tests, including one run containing one of each kind. **Not exercised live**: no repository in the sample list contains a malformed file |

#### What is proven live, and what rests on tests

Worth separating, because Run 10 was constrained to zero provider requests and that
constraint cost specific coverage.

**Proven live (Run 10).** All eight stages emitting; a stage that never ran being absent;
metadata-404 and ref-404 both storing a run and a timeline; the append-only sequence;
per-reason skip counts; the read cap quantified; the rendered page for four different run
states.

**Rests on tests alone.** Rate-limit events (would require exhausting a real quota);
extraction-failure attribution (no malformed file in the sample repos); per-file failure
capping at 50 with the remainder counted; secret redaction; **and the "This run is partial"
banner**, which Run 10 could not display at all — withholding the provider key gives every
run a `degraded` summarisation event, and the banner's partial-only branch is therefore
unreachable in that configuration. That is a direct cost of the zero-request rule, recorded
rather than worked around.

#### The rate-limit criterion, judged explicitly

**PASS on tests. Never live-confirmed, and that is a limitation rather than a gap.**

This is the criterion moved here from Milestone 2 by the 2026-08-17 amendment (second
pass), on the grounds that Milestone 2 detects rate limits but builds no diagnostics to
show them in. It is satisfied, by five tests, and the event carries what a reader needs to
act: which quota (`X-RateLimit-Resource`), the limit, remaining and used counts, the reset
epoch and a human-readable reset time, whether the limit is primary or secondary, and
whether the request was authenticated — which is the difference between "wait four minutes"
and "set a token".

The source is the failing response's own headers, not the `/rate_limit` endpoint, which
`smoke.md` Run 1 measured as stale (`remaining: 4995` while a real request's own header read
`4978`) and every run since has seen stale.

**Run 10 did not reproduce one live, and no future run reasonably will.** Reproducing a
primary rate limit means deliberately exhausting a real quota — 5,000 authenticated requests
an hour, or dropping to the unauthenticated 60 and burning it — which costs the quota this
project runs on and proves something the mocked responses already prove exactly. The mock
carries the same headers a real 403 carries; there is no behaviour the live call would
exercise that the test does not. This is recorded as an honest limitation of the evidence,
not as work left undone, and it does not hold the milestone open.

#### Milestone 7 is closed

Every deliverable exists and is exercised. All eight pipeline stages emit, live. The
endpoint and the page are real, and `smoke.md` Run 10 records the rendered page for four
intentionally induced failure cases against live GitHub. All three named failure signals are
eliminated. The moved Milestone 2 rate-limit criterion is satisfied, with its evidence
boundary stated above.

**The five defects found in the closing audit are fixed and tested:**

1. Re-summarising restarted the event sequence at zero, interleaving its events into the
   middle of the run. Sequences now continue from the stored maximum; ordering is
   `(sequence, id)` so a tie cannot reorder either. Two tests assert **order**, not message
   content — the test that existed before asserted content and passed throughout the bug.
   Live in Run 10 Case 3b.
2. A named ref that does not exist discarded its entire timeline, because no run row was
   created and `persist_events` was never reached. It now stores a failed run carrying the
   metadata that *did* succeed, so the run distinguishes a wrong branch from a wrong
   repository. Live in Run 10 Case 2.
3. `test_a_bad_ref_is_an_error_naming_the_ref` asserted against a `Recorder` it constructed
   itself, and was true regardless of pipeline behaviour. Replaced with three tests against
   the stored run, its stored timeline, and the rendered page.
4. A malformed notebook was filed as `read_failed` at `Stage.CONTENT`, and `Stage.EXTRACTION`
   could emit only INFO. `FailureKind` separates a file that never arrived from one that
   arrived and would not parse; parse failures are now extraction events with reason
   `extraction_failed`, and each aggregate counts only its own kind.
5. The verdict banner reported only the worst level, so a run that was both partial and
   degraded was announced solely as "completed with failures" — `smoke.md` Run 10 Case 4,
   where 87 of 107 selected files went unread and the banner did not say so. Failure and
   partiality are independent conditions and the banner now states both. Found by the smoke
   run, not by the test suite: neither single-condition test covered the combination, which
   is why the fix ships with a test for the combination specifically.

**What is deferred rather than open.** `tasks.md`'s "add logging hooks in core modules" is
recorded as a **deferred design item** under Milestone 7 in `plan.md`. The plan deliverable
it belongs to — "Logging for key stages" — is met: every recorded event is logged from one
call site, so logs and the timeline cannot drift. What remains is the separate question of
what `core/selection.py`, `core/extraction.py` and `core/github_client.py` should log
*independently* of the timeline, which has two defensible answers pulling opposite ways and
plausibly belongs to Milestone 10's log review rather than here. It is a design decision
with its options written down, not an unfinished edit, and it does not hold this milestone
open.

**Caveats carried forward, recorded as notes rather than blockers:**

- Rate-limit visibility is test-backed only, for the reason argued above.
- Extraction-failure attribution is test-backed only: no repository in the sample list
  contains a malformed file.
- Per-file failure capping, secret redaction, and the standalone "This run is partial"
  banner are test-backed only. The last of those could not be displayed in Run 10 at all,
  because withholding the provider key gives every run a `degraded` summarisation event and
  makes the partial-only branch unreachable — a direct cost of the zero-request rule.
- URL validation failures remain the one failure that leaves no stored trace. Deliberate,
  documented in two places, and structurally sound: nothing reached GitHub, so there is no
  repository and no run to attach events to.
- Run 10 covered one completed and one capped repository, not the full sample list. The
  others' classification figures are unchanged by this milestone.

**Milestone 7 is recorded as closed.**

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

### Recorded verdict — 2026-08-19

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **535 passing, 0 skipped**, of which
**48** are the new `tests/test_api_contract.py`.

**No live calls were spent on this milestone, and none were needed.** Milestone 8 changed
response and error shapes, not pipeline behaviour: every claim below is about what the
application returns, which mocked transports exercise exactly. The live evidence this
verdict leans on is `smoke.md` Run 10, unchanged — the honesty fields it recorded are
asserted to still exist and still mean the same thing by
`test_the_honesty_fields_are_all_still_present_and_still_mean_what_they_meant`.

#### The spec's endpoint list is out of date, and was not followed blindly

`spec.md` section 9 predates Milestones 5, 6 and 7 and disagrees with what was built in
three places. Recorded rather than silently reconciled:

| `spec.md` §9 says | Reality | Resolution |
|---|---|---|
| "viewing tree" | No `GET /api/runs/{run_id}/tree` exists. The tree is stored as classified entries and served by `/files` | **Not built, deliberately.** A second endpoint returning the same rows in a different shape would be two contracts for one fact. Recorded in the README under "Web UI pages" so the absence is a stated decision, not a hole |
| — (absent) | `GET /api/runs/{run_id}/summary` exists | Built in Milestone 6. §9 was written before summaries existed |
| — (absent) | `POST /api/runs/{run_id}/summarize` exists | Added by `spec.md`'s own Decision 4 amendment, which §9 was never updated to match |
| — (absent) | `GET /health` exists | Milestone 0 |

`evals.md`'s "Suggested checks" list has the same gap: it names
`GET /api/runs/{run_id}/tree`, which has never existed. Both documents are left as written
rather than edited to match the code, because amending a spec to describe what was built
is how a spec stops being a spec. The disagreement is recorded here and in the README.

#### Criteria

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| Endpoints for runs, tree, files, chunks, diagnostics | plan D1 | PASS, with the tree exception above | Nine endpoints, all answering: `test_every_documented_endpoint_answers` parametrises over the app's own OpenAPI schema and asserts a 200 and a JSON content type for each |
| Consistent JSON response schema | plan D2 | PASS | One pagination envelope — `total`, `unfiltered_total`, `limit`, `offset`, `items`, `filters` — asserted for all four list endpoints by `test_every_list_endpoint_returns_the_same_pagination_fields`, with paging behaviour asserted identically by `test_limit_and_offset_behave_identically_everywhere` |
| API tests | plan D3 | PASS | `tests/test_api_contract.py`, 48 tests, written to sweep every endpoint rather than sample one — the defect being fixed was cross-endpoint drift, which a representative test cannot see |
| External scripts can consume analysis results | plan E1 | PASS | One error shape means one parser: `test_a_schema_violation_uses_the_same_envelope_as_everything_else` pins the case that made this false before, where `detail` held an object for our errors and a list for FastAPI's |
| Missing or invalid resources return clear errors | plan E2 | PASS | `test_every_run_scoped_endpoint_404s_with_the_same_envelope` over all six run-scoped endpoints; `test_a_rejected_filter_value_uses_the_envelope_and_lists_what_is_valid` checks the accepted set travels in `details.valid` as data rather than only inside an English sentence |
| API responses remain consistent | plan E3 | PASS | `test_the_404_message_is_identical_across_every_endpoint` — six endpoints previously carried six copies of one f-string; there is now one copy, in `api/errors.py:run_not_found` |
| Run endpoint smoke tests | plan V1 | PASS | The parametrised answer test above is exactly this, run on every endpoint on every suite run rather than by hand once |
| Confirm response structure | plan V2 | PASS | as D2 |
| Confirm error formatting consistency | plan V3 | PASS | `_assert_envelope` asserts the key set exactly — `{status, code, message, details}`, `details` always an object — and is applied to 404, 400, 405, 422 and 500 paths, including Starlette's own unrouted-path 404 and wrong-method 405, which never pass through our helpers |
| Endpoints return correct JSON | evals | PASS | as D1/D2 |
| Endpoints are stable and predictable | evals | PASS | as E3. Enforced by construction: handlers are installed on the app, so an endpoint cannot opt out and a new endpoint cannot forget to opt in |
| Missing resources return clean errors | evals | PASS | as E2 |
| API can be used programmatically without guessing response shape | evals | PASS | The envelope documents a stable `code` field and says to match on it rather than on prose. `test_the_readme_documents_the_error_codes_the_api_actually_raises` keeps the documented code list complete |
| All documented endpoints behave as expected | evals success | PASS | Documentation is now executable in both directions: `test_the_readme_documents_every_endpoint_that_exists` and `test_the_readme_documents_no_endpoint_that_does_not_exist`, read from `app.openapi()` |
| Error formats are consistent | evals success | PASS | as V3 |
| API contracts do not change silently | evals success | PASS | This is the strongest of the three, because it is the one with a mechanism rather than a promise: adding an endpoint without documenting it fails a test, documenting one that does not exist fails a test, adding an env var without documenting it fails a test, and adding a list endpoint without the shared envelope fails four |

#### The consistency work, endpoint by endpoint

**One error envelope.** Every non-2xx response is now
`{"error": {"status", "code", "message", "details"}}`. Chosen over keeping FastAPI's
`detail` because `detail` is meaningless to a consumer and, worse, keeping the name would
keep the association with the list-shaped form being abandoned — a client written against
the old `detail` would keep working for 404s and break silently on 422s. Renaming makes the
break visible at the one moment before v0.1 ships where an API break is free.

**Successes are not wrapped.** `tasks.md` suggests "consistent `data` and `error` fields or
similar pattern". Wrapping every success in `data` would re-path every field in every
consumer, template and test — including every honesty field whose exact location `smoke.md`
cites — to convey nothing the status code does not already convey. The errors genuinely had
two shapes; the successes did not.

**Two endpoints solved pagination differently; diagnostics lost.** It returned its whole
list under `events` with `total_events`, on the reasoning that the volume rules in
`core/diagnostics.py` hold a run to tens of events. That reasoning covers one *analysis*,
not one *run*: `POST /runs/{id}/summarize` appends to the same timeline every time it is
called and nothing caps how often. So diagnostics takes `limit`/`offset` like the others,
its list is `items` and its count is `total`. `test_diagnostics_paginates_like_the_others`
re-summarises three times and asserts the timeline grew, which is the argument as a test.

**Status codes name the faulting party.** The rule `_status_for` already applied to GitHub
failures now covers everything: 4xx the caller, 429/502 GitHub, 500 RepoBridge. Two codes
survive on the caller side on purpose — 422 for "could not parse your request", 400 for
"parsed it and it is not acceptable" — and that line is tested
(`test_a_well_formed_url_pointing_at_the_wrong_host_is_a_400_not_a_422`). Both carry a
`code`, so a consumer that cares reads the code, not the status.

**A 500 that says 500.** There was no unhandled-exception handler; a bug in this
application produced whatever Starlette's default was. It now returns the envelope with
`code: internal_error`, and deliberately **does not** include the exception text — an
unhandled exception is the error path nobody wrote on purpose, so it is the least likely to
have been checked for a token in its message. Asserted by
`test_an_internal_failure_blames_this_application_and_leaks_nothing`, which raises an
exception carrying a token-shaped string and asserts it is absent from the response.

**`POST /runs/{id}/summarize` returns 200 even when the provider failed, deliberately.**
The request did what it said: it attempted a re-summarisation and recorded the outcome,
including diagnostics events. A 502 would imply nothing happened, when stored state
changed. This blames nobody and matches `POST /api/analyze`, which has always returned 200
with `summary.status` carrying the provider outcome. Documented in the README as "check
`status`, not the HTTP code".

#### The honesty fields survived, and are pinned

`smoke.md` records a specific live failure behind each of these. Every one was checked
after the reshape, and **none was renamed, moved or repurposed**:

| Field | What it exists for | State |
|---|---|---|
| `tree_truncated`, `tree_error` | GitHub-side truncation must never be discoverable only by noticing a boolean (M2) | unchanged |
| `accounts_for_every_entry` | the classification identity at 37,393 entries (M3, Run 4) | unchanged |
| `read_cap`, `cap_applied`, `files_not_fetched`, `read_of_selected`, `accounts_for_every_selected_file` | the read cap, and the Run 8 finding that a capped run was grounded in the wrong 2% (M5, Runs 8–9) | unchanged |
| `provenance.is_partial`, `limitations`, `chunks_excluded`, `token_budget` | a summary must disclose sparse coverage (M6, Run 8) | unchanged |
| `run_entry_count`, `run_chunk_count`, `run_files_read`, `run_selected_count` | a filtered count must never be read as a whole one (M4/M5) | unchanged |
| `counts_by_level`, `outcome`, per-stage roll-up | filters must never narrow the totals (M7, Run 10) | unchanged; only the list key beside them was renamed |

The one rename in the whole milestone is diagnostics' `events` → `items` and
`total_events` → `total`. Neither names a count, a cap, a truncation or a shortfall: they
name *the list* and *its length*. The counts that carry meaning — `counts_by_level`,
`outcome`, `stages` — are untouched and still computed over the whole run rather than the
page, which `test_filtering_narrows_events_but_never_the_totals` still asserts.

**`unfiltered_total` is additive, not a replacement.** It was tempting to fold
`run_entry_count` into it. They are different numbers: `run_entry_count` is what the *tree*
said the run contained, `unfiltered_total` is how many rows were actually stored, and the
gap between them is exactly what `stored_identity_holds` exists to report. Both are kept,
and `test_filtered_totals_on_files_and_chunks_never_read_as_whole_ones` pins both.

#### Filtering on `/api/runs`

`status`, `owner` (case-insensitive, because GitHub owner names are), `since` and `until`
(ISO 8601, a bare date meaning midnight UTC, naive input stamped UTC rather than compared
against a local clock the caller never mentioned). Substring search is deliberately not
offered: an exact owner is answerable from an index, and "everything matching a fragment"
is what the path filter one level down is for.

The honesty rule holds by construction — `storage.list_runs` returns the matching total
*and* the unfiltered total in one call, so an endpoint cannot report the first without the
second. `test_date_filters_bound_the_result` asserts the sharp case: a filter matching
nothing returns `total: 0` beside `unfiltered_total: 3`, never a zero that reads as an
empty database.

#### The README

Rewritten. It had claimed extraction, summaries and diagnostics were "not built yet" for
two milestones after they shipped, and documented none of `/chunks`, `/summary`,
`/summarize` or `/diagnostics`. It now carries every endpoint with its request and response
shape, the error envelope with its code table, all six environment variables with their
defaults, and a Limitations section stating public-repos-only, the read cap with a real
figure (`github/docs` selects 11,217 files; a default run reads 200), the provider's
free-tier quota and the daily-quota retry decision, no migrations, and tree truncation.

**Four tests make it executable**, which is the part that matters: documentation drift is
what produced the defect, and prose cannot be trusted not to drift again. Adding an
endpoint without documenting it fails; documenting one that does not exist fails; adding an
environment variable to `config.py` without documenting it fails; and the specific
regression — the "not built yet" claim — is asserted absent.

#### Milestone 8 is closed

Every plan deliverable exists, every expected behaviour is asserted across the whole
surface rather than sampled, and all three `evals.md` success criteria are met with
mechanisms rather than promises.

**Caveats carried forward, recorded as notes rather than blockers:**

- **`GET /api/runs/{run_id}/tree` is not built**, and `spec.md` §9 and `evals.md`'s
  suggested-checks list both still name it. The decision and its reasoning are in the
  README; the spec is left as written.
- **The API surface has no versioning.** Paths are unprefixed (`/api/...`, not `/api/v1/`),
  so the "contracts do not change silently" guarantee is enforced by tests within this
  repository, not by anything a external consumer could pin. Acceptable for a local-first
  single-user tool; it would not be for a published API.
- **The error envelope is a breaking change** for anything written against the old
  `{"detail": ...}` shape. Nothing has shipped, so nothing external breaks; the in-repo
  consumer (`ui/static/js/main.js`) was updated in the same change.
- **No live verification.** None was needed — see the head of this verdict — but it means
  the envelope has only ever been produced against mocked transports and the local UI.
- **The UI templates still use their own context names** (`total_events` in
  `diagnostics.html`). The template context is not the API contract and renaming it buys
  nothing; noted so the inconsistency is a decision rather than an oversight.

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

### Recorded verdict — 2026-08-19

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **611 passing, 0 skipped**, of which
**76** are the new `tests/test_ui.py`. The live result is `smoke.md` Run 11 — every page
walked against the four runs Run 10 stored, 134 internal links followed, **zero API calls
of either kind**.

#### The spec's UI list contradicts the spec

`spec.md` section 10 asks for an "input form for repo URL (and optional branch/token)".
**There is no token field, deliberately** — `spec.md` section 5 and the Milestone 2
decision it records rule one out: v0.1 is local-first and single-user, so a per-request
secret would buy nothing while flowing into persistence, diagnostics and logs. Section 10
was written before that decision and never updated, so the document contradicts itself.

Recorded, not reconciled, for the same reason as the Milestone 8 divergence: amending a
spec to describe what was built is how a spec stops being a spec. The form has two fields —
repository URL and optional branch or ref — and that is correct behaviour, not a missing
deliverable.

Section 10 also asks for a "tree and file list view" as one item, which is one page
(`/runs/{id}/tree`). No divergence; noting it so the count of five bullets against four
pages is not read as a gap.

#### Criteria

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| Input form | plan D1 | PASS | `/` renders it; every control has a `<label for=…>` (`test_every_form_control_has_a_label`); walked in Run 11 |
| Recent runs list | plan D2 | PASS | Now with status/owner/date filters, a Read column and per-row links to all three views. `test_recent_runs_link_to_more_than_the_detail_page` |
| Run detail page | plan D3 | PASS | Walked in Run 11 for a partial, a clean and both kinds of failed run |
| Tree page | plan D4 | PASS | Walked filtered and unfiltered; `test_every_page_renders_for_every_run_shape` covers all five shapes |
| Diagnostics page | plan D5 | PASS | Walked; the combined banner verified live for the second time |
| A user can complete the flow without touching the API | plan E1 | PASS | Run 11: home → run → file listing → diagnostics, and back, entirely by links. 134 links followed, 0 broken |
| Empty, loading, and error states are readable | plan E2 | PASS | **Empty**: no runs (`test_the_home_page_renders_with_no_runs_at_all`), empty filter result, empty file listing — all walked. **Error**: both failure kinds, walked. **Loading**: elapsed counter plus staged messages, asserted structurally; see the caveat below |
| UI remains lightweight and responsive | plan E3 | PASS | Still Jinja2, hand-written CSS and one JS file. No framework, no build step, no dependency added in nine milestones. A `@media (max-width: 700px)` block was added; **not verified in a browser** |
| Manual walkthrough on local machine | plan V1 | PASS | `smoke.md` Run 11 |
| Check main journey from URL input to summary/diagnostics | plan V2 | PASS | Run 11 walks it end to end and quotes each page |
| Confirm no broken navigation | plan V3 | PASS | 134 links followed across 13 pages, every one 200 |
| A user can complete the whole flow from the browser | evals | PASS | as E1 |
| The UI makes the current run status obvious | evals | PASS | Status stated in words on every page (`test_the_run_status_is_stated_in_words_not_only_in_colour`), plus state flags for what status alone cannot say |
| The summary, tree, files, and diagnostics are easy to find | evals | PASS | One navigation strip on all three run pages, reaching all four destinations; the runs list reaches all three views per row |
| Empty, loading, and error states are clear | evals | PASS | as E2 |
| A first-time user can use the app without reading code | evals success | PASS | Run 11 reads each page as prose; every number on screen is labelled and every filter is a visible control |
| Navigation is simple and consistent | evals success | PASS | One partial, `_run_nav.html`, included by all three run pages — the inconsistency it replaces is recorded below |
| The UI feels like a tool, not a prototype shell | evals success | PASS, and this is the softest row | Backed by what changed rather than by taste: a state column that distinguishes runs, filters wired to real query parameters, one navigation strip, focus states, and a failure notice that no longer contradicts the table beneath it. Not backed by any browser or user session |

#### The four named failure signals

**"Hidden controls" — eliminated.** The Milestone 8 filters existed only as query
parameters; nothing in the UI exposed them. They are now a visible form on the home page,
and the tree page's filters were already chips.

**"Broken navigation" — eliminated, by following rather than by inspection.** Run 11 walks
134 links; `test_every_navigation_link_on_every_page_resolves` re-walks them for all five
run shapes on every suite run.

**"States that are visually indistinguishable" — this is where most of the work went.**
Three cases were genuinely indistinguishable before:

| Case | Before | Now |
|---|---|---|
| A run that read 20 of 107 files vs. one that read 30 of 30 | identical green `completed` badge | `CAPPED` flag plus a Read column |
| A run whose listing GitHub truncated | visible only on the run's own page | `TRUNCATED` flag wherever the run appears |
| An analysis working vs. stuck | one static sentence for the entire wait | elapsed counter, and messages at 0 s, 8 s, 25 s, 60 s |

**"Confusing or cluttered layouts" — one instance found and fixed.** The navigation strip
printed the repository name on the detail page, whose `<h2>` is the repository name and
whose document title is too. Suppressed there, kept on the sibling pages whose headings are
"Files" and "Diagnostics".

#### What the walkthrough found that the tests did not

**A failed run was told something untrue.** The bad-ref case rendered *"The repository
never resolved, so nothing was retrieved or classified"* and then printed
`Default branch: master` four rows below — the repository had resolved; the ref had not.
Milestone 7 introduced this when it made a bad ref store a failed run *carrying the
metadata that did succeed*, a genuine improvement that left the notice describing only the
older failure mode. Every test asserted on `status`, and both kinds are `failed`, so
nothing caught it.

This is the second milestone running where the live pass found what the suite could not,
and both were the same shape: **a case that is two things at once, tested one at a time**
(Milestone 7's banner was partial *and* degraded; this run is failed *and* resolved). Worth
watching for in the remaining milestone.

The wording change is quoted before and after in Run 11 and pinned by
`test_a_failed_run_says_which_kind_of_failure_it_was`.

#### The honesty elements were not redesigned

Each of these exists because a specific failure was found live. All are asserted present
**by their words**, the way `test_api_contract.py` pinned the API's honesty fields:

| Element | Recorded in | State |
|---|---|---|
| Tree scope line — "Showing 1–23 of 23 matching entries (of 153 in this run)" | Run 5 | unchanged |
| Tree truncation warning | Run 5 | unchanged |
| Accounting identity, shown as a visible sum | Run 4 | unchanged |
| Summary provenance block and "Claims in the prose should be checkable…" | Runs 7–8 | unchanged |
| Partial-coverage notice | Run 8 | unchanged |
| Extraction scope line and the read-cap sentence | Runs 8–9 | unchanged |
| Diagnostics verdict banner, all four branches | Run 10 | unchanged |
| Chunk sample naming itself a sample | Run 6 | unchanged |

**Two changes touched this territory and both are recorded.** The failure notice above is
one — a correction of a false statement, quoted before and after. The other is a *variable*
rename in `diagnostics.html`: `total_events` → `total`, to match the API's pagination
envelope. The rendered sentence is identical character for character, and
`test_the_diagnostics_event_count_line_survives_the_variable_rename` asserts the sentence
rather than the variable.

#### Accessibility

The Milestone 4 debt is closed and the pass went wider than it:

| Item | State |
|---|---|
| Home page shipping pre-written error prose on every render | **Closed.** The container ships empty with `role="alert"`; the script fills it. Two tests: the prose is absent from the served HTML, and the region is live and focusable — so a failure is now *announced*, which it never was even while hidden |
| Labels on form controls | Every control labelled, asserted by parsing the served HTML rather than by inspection |
| Focus states | One `:focus-visible` treatment covering links, buttons, inputs, selects, chips, count cards and the pager. Previously the app relied on browser defaults, easiest to lose on the links styled `text-decoration: none` |
| Colour as the only carrier of meaning | Status badges always carried their word. The two places colour stood alone are fixed: the active nav item now carries `aria-current="page"`, and the new state flags carry words (`CAPPED`, `TRUNCATED`) rather than a coloured dot |
| Progress announcements | The staged messages are a polite live region; the per-second clock is `aria-hidden`, because a clock read aloud every second is noise |
| Landmarks | Skip link, `<main id="main">`, `<nav aria-label>`, `<caption class="sr-only">` on the runs table, and per-row link labels disambiguated for a screen reader reading a column of identical "files" links |

**Not verified with an assistive technology.** Every claim above is structural — the right
attributes are in the served HTML, asserted by tests. Whether a screen reader announces
them usefully has not been observed, and no browser was opened.

#### Milestone 9 is closed

Every deliverable exists, every expected behaviour is asserted across all five run shapes
rather than the one each page was built against, all four named failure signals are
eliminated, and the walkthrough is recorded with the pages quoted.

**Caveats carried forward, recorded as notes rather than blockers:**

- **The loading state has not been watched live.** Its markup and its staged messages are
  asserted by tests, and the thresholds come from Run 10's measured timings (~8 s for
  `psf/requests`, minutes for `github/docs`), but nobody has sat through a long analysis
  and watched the counter tick. This is the one Milestone 9 behaviour that only exists in
  time, and the walkthrough — which reads stored runs — structurally cannot exercise it.
- **No browser and no screen reader.** Focus rings, the 700 px breakpoint, and colour
  contrast are unverified by eye; the accessibility work is verified as markup only.
- **Degraded and truncated runs were not walked live.** A degraded run needs a real tree
  call to fail; a truncated one needs a repository GitHub actually truncates, and the
  largest tried live (37,393 entries) was not truncated. Both are covered by tests across
  all three pages.
- **There is no UI for chunks beyond the 20-row sample** on the run detail page.
  `GET /api/runs/{id}/chunks` is paginated and filterable; nothing in the UI reaches it.
  Not a Milestone 9 deliverable — `plan.md` lists five pages and this would be a sixth —
  but a person who wants chunk 300 of 400 must use the API.
- **`spec.md` section 10 still asks for a token field** that section 5 of the same document
  rules out. Left as written.

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

### Recorded verdict — 2026-08-19

Judged against the code as it stands. A criterion is PASS only where a test or a recorded
live result backs it. Test suite at time of judging: **646 passing, 0 skipped** — 636 in
the developer checkout plus the ten new end-to-end tests; **620 of them also run green in a
clean virtualenv built from scratch**, which is the number that matters for this milestone.
The live result is `smoke.md` Run 12.

#### The Milestone 10 criteria hold up, with one item an agent must not do

Unlike `spec.md` §9 (Milestone 8) and §10 (Milestone 9), nothing in the Milestone 10
criteria contradicts what was built. One task is not an agent's to perform:

> `tasks.md`: "Tag v0.1 in Git, or at least create a clear commit marking 'RepoBridge v0.1
> baseline'."

This session operates under an explicit no-commit constraint, and tagging a release is the
owner's act regardless. **Recorded as the one Milestone 10 deliverable left outstanding**,
and it is deliberately not marked PASS below.

#### Criteria

| Criterion | Source | Verdict | Evidence |
|---|---|---|---|
| README finalized | plan D1 | PASS | Rewritten at Milestone 8, extended here with "API stability" and "Upgrading". Four tests make it executable: an undocumented endpoint fails the build, a documented-but-missing one fails, an undocumented environment variable fails, and the Python floor must match `pyproject.toml` |
| Basic tests passing | plan D2 | PASS | 646 in the checkout; **620 in a clean virtualenv**, which is the stronger claim — Run 12 |
| Clean logs | plan D3 | PASS | See the log decision below. Startup states configuration once; every diagnostic event is logged from one call site at a severity derived from its level; nothing else logs |
| Reliable setup steps | plan D4 | PASS | Run 12 executed README flow 1 verbatim from an empty directory: four steps, all worked first time. Flow 3 (`uv sync`) is labelled aspirational and was not run |
| Smoke test suite | plan D5 | PASS | `smoke.md`, twelve recorded runs across seven repositories and four induced-failure classes |
| Fresh clone can be set up quickly | plan E1 | PASS | Run 12: venv to serving in four commands; server up 2 s after boot |
| Common failure cases are handled | plan E2 | PASS | Bad URL, wrong host, missing repo, missing ref, rate limit, tree failure, unreadable file, malformed notebook, absent provider key, stale database — each with a named code and a message that says what to do |
| Project feels coherent and maintainable | plan E3 | PASS, and the softest row | Backed by structure rather than taste: `core`/`infra`/`api`/`ui` separation held for ten milestones with no framework and no build step; one error envelope; one pagination envelope; one navigation partial; one version constant. Not backed by any second developer's opinion |
| Fresh install test | plan V1 | PASS | Run 12 |
| Full test suite | plan V2 | PASS | 646 / 620 |
| Smoke suite across multiple repos | plan V3 | PASS | Seven repositories, 1 to 37,393 entries |
| Manual review of logs and UI | plan V4 | PASS | Logs reviewed below; the UI was walked page by page in Run 11 and re-rendered after the Milestone 10 visual pass |
| Fresh clone setup works | evals | PASS | Run 12 |
| Basic test suite passes | evals | PASS | in both environments |
| Smoke tests work on multiple sample repos | evals | PASS | Runs 1–12 |
| Logs are readable and not noisy | evals | PASS | Run 12 quotes a complete clean-machine boot and a complete analysis: 12 lines for a full run, one per stage, no repetition, no stack traces |
| The app can be restarted and still function normally | evals | PASS | Run 12 restarted the process against the same file and read the run back; `test_everything_is_readable_again_after_the_app_restarts` asserts the same across every surface |
| Setup instructions match reality | evals success | PASS | Executed, not reviewed — Run 12 |
| Project is stable enough for continued development | evals success | PASS | Ten closed milestones, 646 tests, every honesty element pinned by wording |
| v0.1 can be shown confidently as a working baseline | evals success | PASS, with the caveats listed at the end | A first-time user with neither key gets a completed, fully accounted run and a page explaining what it could not do |
| Tag v0.1 in Git | tasks | **NOT DONE** | The owner's action; this session cannot commit or tag |

#### What Run 12 found, by doing it

Four real defects, none of which any test or reading had caught:

1. **A stale database dumped a forty-line traceback** whose last line was the only useful
   one — and it named a connection URL rather than a file path. This is the *first* error
   a user meets after their first upgrade. Now logged as a framed block before the
   traceback, naming the resolved absolute path.
2. **A rate-limit error never mentioned that a token exists.** The unauthenticated user on
   60 requests an hour is precisely the person who hits it and precisely the person who
   does not know the fix. Now names the variable and the 5,000/hour ceiling — and only
   when there is no token, because telling an authenticated user to authenticate is noise.
3. **`tests/test_end_to_end.py` was empty.** Zero tests, named in `tasks.md` under
   Milestone 6 *and* Milestone 10: a filename that read as coverage for five milestones.
   Now ten tests, and deliberately not more per-stage assertions — they cross-check the
   surfaces against *each other*, which is the failure mode a stage-shaped test cannot
   see. One of them found that `provenance.limitations` correctly reports skipped entries
   on a run whose `is_partial` is false; the assertion was wrong, not the code.
4. **`PRAGMA foreign_keys` was never set**, so every `ondelete="CASCADE"` was decoration.
   Nothing deletes a run today, which is why it went unnoticed and exactly why it should
   be right before something does.

#### Decision — no database migrations, and no Alembic

**Deferred four times; decided now.** v0.1 ships with no migrations. A schema change means
deleting `repobridge.db`. Recorded in the README under "Upgrading", pinned by
`test_the_readme_records_the_no_migrations_decision`.

**The argument.** Migrations exist to preserve data that cannot be reconstructed. Every row
RepoBridge stores derives from a public GitHub repository and can be regenerated by
re-running the analysis; the true cost of a reset is GitHub requests, plus provider quota
if summaries are re-made. Against that, Alembic is a dependency, a migration directory and
a per-change authoring step, for a schema that moved in six of ten milestones, in a project
whose stated scope is a small local tool.

**What was hardened instead** — because the decision is only defensible if the failure is
good: the refusal names the exact file, explains the policy, points at the README section
that argues it, and states the cost. It is a two-line instruction rather than a puzzle.

**The cost, recorded rather than buried:** upgrading loses stored runs; re-making summaries
spends provider quota; and there is no warning *before* upgrading, only a refusal after.
**Revisit when** someone other than the author is running against repositories they cannot
cheaply re-analyse, or when a schema change is additive enough that a migration is three
lines.

#### Decision — the API stays unversioned, and says so

**No `/v1/` prefix. The README states plainly that the v0.1 API is unstable.** Pinned by
`test_the_readme_records_the_api_stability_decision` and by
`test_no_endpoint_has_acquired_a_version_prefix`, which fails if a prefix appears without
the README changing with it.

**The argument.** A version prefix is a promise, and v0.1 cannot keep one: the schema has
moved four times, and Milestone 8 changed every error body from `{"detail": …}` to
`{"error": …}`. Shipping `/api/v1/` and then breaking it is worse than shipping no prefix,
because the prefix is a claim a consumer is entitled to rely on. Unprefixed paths make the
situation legible — there is no version to pin because nothing is frozen.

**What consumers get instead:** pin a commit. Contracts are enforced in-repo by
`test_api_contract.py`, which is a real guarantee inside this repository and none at all
outside it. **A prefix arrives with the first external consumer**, together with a
commitment not to break it.

#### Decision — logs, and the Milestone 7 design item resolved

The logging-hooks item deferred from Milestone 7 and parked here is **resolved as: do not
add per-module logging hooks.**

**What the logs are for, given diagnostics exist.** Diagnostics explain one *run*, per run,
in the UI and the API, structured and queryable. The log's job is the part that
structurally cannot: facts about the **process**, which exist before any run does and
belong to none of them. That is now one line at startup — version, database path, whether
each key is set, model, read cap, concurrency — which turns "it isn't summarising" into an
answerable question. Booleans only for the keys; a scan of the log confirmed neither value
appears.

**Why not per-module hooks.** Adding logging inside `core/selection.py`,
`core/extraction.py` and `core/github_client.py` means deciding what they say
*independently* of the timeline, which creates a second narrative of the same run that will
drift from the first. Drift between two accounts of the same events is precisely the
failure diagnostics was built to prevent, and `kubernetes/kubernetes` at 37,393 entries is
the scale at which "log every decision" becomes unusable. The property already established
— a recorded event and its log line come from one call site and cannot disagree — is worth
more than coverage of the gaps.

**Measured noise:** a complete analysis of a one-file repository logs 12 lines, one per
stage plus the HTTP requests. A clean boot logs 3. No stack traces on any handled path.

#### License and visibility — options only, no change made

**Nothing was changed, and nothing should be by an agent.** `LICENSE.md` remains All Rights
Reserved and `README.md` still says "private and proprietary, not yet ready for public
use". That posture was chosen five milestones ago when the product direction was unsettled;
it is worth a deliberate decision now, by the owner.

| Option | What it enables | What it costs |
|---|---|---|
| **Keep All Rights Reserved** | Every future option stays open, including commercial licensing | Nobody can legally use, fork or contribute. "Local-first tool for LLM workflows" is a category people adopt by cloning; this forbids exactly that. A public repository with this licence collects stars and no users |
| **MIT / BSD-2** | Maximum adoption; the default expectation for a developer tool | Anyone may fold it into a commercial product without returning anything. Irrevocable for released versions |
| **Apache-2.0** | Same adoption as MIT, plus an explicit patent grant and a NOTICE requirement — the safer choice for anything a company might adopt | Slightly longer, marginally less familiar to individuals |
| **AGPL-3.0** | Prevents a hosted closed fork; strong for a tool that could plausibly become a service | Many companies forbid AGPL dependencies outright, which removes a large part of the audience |
| **Dual: AGPL + commercial** | Open adoption plus a revenue path | Requires a CLA from contributors and real administration; heavy for a solo v0.1 |

**Consequences worth weighing beyond the licence text.** The README's own status line
("private and proprietary, not yet ready for public use") does more to deter use than the
licence does, and the two should agree. `AGENTS.md` scopes v0.1 as a local single-user tool
with no auth, no accounts and no multi-user story — which is a fine thing to open-source
and a poor thing to sell as-is. Note also that the dependency set (FastAPI, SQLAlchemy,
Uvicorn, httpx, Jinja2) is permissively licensed and constrains nothing.

**A recommendation, since one was asked for:** if the goal is that people actually use
this, **Apache-2.0** is the fit — the adoption profile of MIT with a patent grant that
makes it safe for a company to adopt, and it matches what a tool of this shape is expected
to carry. But this is the owner's call and the licence file is unchanged.

#### Milestone 10 is closed, with one deliverable outstanding

Every plan deliverable exists and is verified by execution rather than by review. The three
decisions deferred across earlier milestones — migrations, API versioning, logging hooks —
are decided and recorded, each with its argument and its cost. The two questions this
milestone exists to answer are answered by Run 12: the setup works from nothing, and a
first-time user with neither key gets a working tool that explains its own limits.

**Outstanding:** tagging v0.1. The owner's action.

**Caveats carried forward, recorded as notes rather than blockers:**

- **One OS, one Python version.** Windows 10, CPython 3.13.7. `pyproject.toml` declares a
  floor of 3.10 that has never been exercised, and no Linux or macOS run exists.
- **Not a true `git clone`.** Run 12 copied the working tree with a clone's exclusions,
  because the code is uncommitted. `.gitattributes` line-ending normalisation is untested.
- **No second person has run this.** Every "would a newcomer get stuck" judgement in Run 12
  is the author's simulation of a newcomer, which is the weakest part of this milestone.
- **The licence question is open by design**, and until it is answered the project cannot
  be used by anyone else regardless of how good the setup instructions are. That is the
  largest remaining obstacle to "works for someone who is not the person who built it",
  and it is not a technical one.
- **`uv sync` (README flow 3) is unverified** and would not install the `dev` extra, so
  `pytest` would be absent. The flow is labelled conceptual.
- **No CI.** Every test run in this project has been manual. The contract tests that keep
  the README honest only fire when someone remembers to run them.

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