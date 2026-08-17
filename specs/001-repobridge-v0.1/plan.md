# RepoBridge v0.1 Plan

This plan breaks RepoBridge v0.1 into small milestones with clear deliverables, validation checkpoints, and expected behavior after each stage.

The goal is to build the project in a production-minded way while keeping the scope small enough for a local-first MVP.

---

## Amendment — 2026-08-17: Milestone 2 scope split

**Trigger.** An audit of the claim "Milestone 2 is complete" found the milestone unclosable
as written. M2 bundled three separable things — GitHub retrieval, SQLite persistence, and a
tree view in the UI — so retrieval could be finished while the milestone as a whole stayed
open indefinitely. It had been half-finished for exactly that reason.

**What moved.** SQLite persistence (`infra/db.py`, `infra/schemas.py`, saving analysis run
records) and the UI tree view move out of Milestone 2 into a new **Milestone 4 — Persistence
and tree view**, placed after file selection so there is a real classification result to
persist and display. Nothing was dropped: the moved criteria reappear intact under
Milestone 4.

**Where the bundling actually lived.** This plan's Milestone 2 deliverables were already
retrieval-only; the persistence and UI tasks were in `tasks.md`. The split is therefore a
removal in `tasks.md` and an addition here.

**What Milestone 2 is now.** Retrieval works, errors are honest, tests prove it.

**Renumbering.** Former Milestones 4–9 shift to 5–10 across `plan.md`, `tasks.md`, and
`evals.md`. No other document referenced milestones by number.

**Known consequence, recorded not resolved.** Milestone 3 (file selection) still carries a
task to extend database schemas, which now sits before the persistence milestone. That
ordering is left as written rather than quietly rewritten; resolve it when Milestone 3 is
planned.

### Second pass — same date: diagnostics criterion

A closing review of Milestone 2 found one more criterion that could not be satisfied inside
its own milestone. `evals.md` listed **"Rate-limit conditions are visible in diagnostics"**
under Milestone 2 success criteria, but Milestone 2 builds no diagnostics subsystem —
`core/diagnostics.py` is empty until Milestone 7. The criterion was structurally
unsatisfiable where it sat: retrieval could be complete and correct, and the milestone would
still not close.

**What moved.** That criterion moves intact into **Milestone 7 — Diagnostics and
observability**, whose job it actually is. Nothing is weakened: rate-limit visibility is
still required, and it is still required to be visible in diagnostics. It is now required of
the milestone that builds them.

**What Milestone 2 keeps.** Rate limits must still be detected and surfaced clearly at the
point of failure, which they are, in the API response.

**Note on the pattern.** Both passes of this amendment fix the same mistake: a milestone that
asserted criteria depending on machinery a later milestone builds. Worth checking for when
planning the remaining milestones.

---

## Milestone 0 — Project skeleton

### Goal
Create a runnable FastAPI application skeleton with a minimal local UI, logging, and SQLite wiring.

### Deliverables
- App entrypoint exists.
- `/health` endpoint works.
- Root UI route exists.
- Basic configuration and logging modules exist.
- SQLite connection layer exists, even if minimal.
- Project can start locally with one command.

### Expected behavior
- App boots without crashing.
- `/health` returns healthy JSON.
- Root page renders.
- No secrets are hardcoded.

### Validation
- Server starts successfully.
- Health endpoint responds.
- Root page loads in browser.
- Basic smoke test passes.

---

## Milestone 1 — Repo URL intake and validation

### Goal
Accept a GitHub repo URL and normalize it into structured owner/repo information.

### Deliverables
- URL parser/validator module.
- Error handling for malformed or unsupported URLs.
- Unit tests for valid and invalid inputs.

### Expected behavior
- Valid GitHub repo URLs are accepted.
- Invalid URLs are rejected with clear messages.
- No GitHub API call happens before validation succeeds.

### Validation
- Test valid URL parsing.
- Test malformed URL rejection.
- Test non-GitHub URL rejection.
- Confirm normalized owner/repo output is correct.

---

## Milestone 2 — GitHub repository retrieval

### Goal
Fetch repository metadata and tree structure using official GitHub APIs, and report
failures honestly. Retrieval only — see the 2026-08-17 amendment above.

### Deliverables
- GitHub client module.
- Repo metadata retrieval.
- Tree retrieval for a valid ref/branch.
- Rate-limit and not-found error handling.
- Tests covering success, not-found, rate-limit, and network-failure paths, with GitHub
  responses mocked rather than live.

### Expected behavior
- Public repos can be retrieved.
- Tree paths are accurate for the resolved ref.
- Errors are surfaced clearly, with the status code this API returns reflecting what
  actually went wrong rather than echoing GitHub's.
- Analysis continues safely when possible: a tree failure degrades the run rather than
  failing it, while a ref the caller explicitly named and that does not exist is an error.
- Incomplete results are labelled as incomplete.

### Not in this milestone
- SQLite persistence of run records — moved to Milestone 4.
- UI tree view — moved to Milestone 4.

### Validation
- Use a small set of sample public repos for smoke tests.
- Verify tree completeness, including that GitHub-side truncation is reported.
- Verify error messages for nonexistent repos and nonexistent refs.
- Verify rate-limit handling is explicit.

---

## Milestone 3 — File selection and classification

### Goal
Classify files into selected, skipped, or failed with reasons.

### Deliverables
- File classification rules.
- Supported file extension list.
- Skip reason schema.
- Tests for common repo layouts.

### Expected behavior
- Markdown, code, notebooks, text, and JSON are recognized.
- Obvious binaries and junk are skipped.
- Every skipped file has a reason.

### Validation
- Test mixed repos.
- Test notebook-heavy repos.
- Test binary-heavy repos.
- Confirm no silent file drops.

### Candidate for a later milestone — `CREDENTIAL_LIKE` skip reason

**Not in scope for Milestone 3. Recorded so the gap is a known decision, not an oversight.**

Observed while smoke-testing the classifier: `psf/requests` carries `.pem`, `.key`, `.csr`,
`.crt` and `.srl` files, and they are currently skipped as `unsupported_extension` — the
blandest reason available. In that repository they are TLS test fixtures and harmless. In a
repository that had committed a real private key, RepoBridge would skip it with the same
shrug.

**The proposal.** A `CREDENTIAL_LIKE` skip reason covering credential-shaped files —
`.pem`, `.key`, `.crt`, `.cer`, `.p12`, `.pfx`, `.jks`, `.keystore`, `id_rsa`-style names,
and `.env` files carrying real values rather than the `.env.example` templates Milestone 3
already selects. The file is still skipped; what changes is that it is skipped *for a named
reason a human would want to see*, and can be counted separately in diagnostics.

**Why it plausibly belongs in the product.** RepoBridge exists to tell a user what is in a
repository and what happened to it. "This repo contains 4 credential-shaped files" is exactly
the kind of thing the diagnostics view should surface. Silently filing them under
"unrecognised extension" is the weaker behaviour.

**Open question — false positives.** The overwhelming majority of `.pem`/`.key` files in
public repositories are test fixtures, example certificates, or expired demo material.
Flagging them all as credential-shaped risks crying wolf, which trains users to ignore the
signal. The distinction cannot be made from a path alone; it needs file content, which means
this cannot land before content retrieval exists (Milestone 5). Options to weigh then:

- flag on path shape only, and word the message as "credential-shaped, not verified";
- inspect content for PEM headers (`-----BEGIN ... PRIVATE KEY-----`) before flagging;
- flag on shape but suppress inside directories named `test`, `tests`, `fixtures`.

**Deliberately unresolved here.** Decide it when the milestone that can see file content is
planned. Whatever is chosen, the reason code must not imply a security verdict RepoBridge
has not actually made.

### Recorded decision — directory matching is case-sensitive, filenames are not

**This asymmetry is deliberate. Do not "fix" it without reading this.**

In `config.py:SelectionConfig`, filename matching folds case (`Dockerfile` and `dockerfile`
both select; `Cargo.lock` and `cargo.lock` are both lockfiles) but `excluded_directories`
does **not** (`build/` is excluded, `Build/` is not).

**Why the difference.** Folding a filename widens *case*, and the set of names it can newly
match is tiny and known — there is no meaningful file called `dockerfile` that we would want
to treat differently from `Dockerfile`. Folding a directory name widens what gets *silently
dropped from the analysis entirely*, and the risk is not symmetric: on case-sensitive
filesystems `Build/` and `build/` are genuinely different directories, and a project may well
have a hand-written `Build/` of real source alongside a generated `build/`. Excluding a
directory removes every file beneath it, so a false positive there is far more costly than a
false negative on a filename.

The failure modes are asymmetric, so the rules are too:
- filename fold, false positive: one extra file read. Cheap.
- directory fold, false positive: an entire subtree of real source vanishes from the
  analysis, reported only as `excluded_directory`. Expensive, and exactly the kind of silent
  loss this product exists to prevent.

**Revisit if** a real repository is observed whose vendored directory is capitalised
(`Node_Modules/`, `Vendor/`). At that point prefer adding the specific capitalisation to the
set over folding the whole comparison.

---

## Milestone 4 — Persistence and tree view

Scope moved out of Milestone 2 by the 2026-08-17 amendment. Placed here because a stored
run is only worth displaying once files have been classified.

### Goal
Persist analysis runs in SQLite and show the retrieved tree in the UI.

### Deliverables
- SQLite persistence for analysis runs in `infra/schemas.py` and `infra/db.py`, saving
  repo metadata and run status.
- An analysis run record created when `/api/analyze` runs.
- A simple tree view in the UI, showing the path list or nested structure for a completed
  run, reading from the database.

### Expected behavior
- A run survives a restart and can be reopened.
- Recent runs can be listed.
- The tree view reflects what was actually retrieved, including whether the listing was
  truncated by GitHub.
- No secrets (tokens) are written to the database.

### Validation
- Create a run, restart the app, confirm the run is still listed and readable.
- Confirm stored metadata matches what the API returned.
- Confirm the tree view renders a real retrieved tree, and shows the truncation warning
  when the stored run was truncated.

---

## Milestone 5 — Extraction and normalization

### Goal
Convert selected files into normalized text chunks.

### Deliverables
- Markdown/text extractor.
- Code file extractor.
- Notebook parser.
- Chunk model and persistence.

### Expected behavior
- Notebook markdown cells and code cells are preserved distinctly.
- Extracted content is readable and linked to source paths.
- Malformed files fail gracefully.

### Validation
- Compare extracted output with source files.
- Test malformed notebook handling.
- Verify chunk counts and source links.

---

## Milestone 6 — Grounded summary generation

### Goal
Generate a summary that is grounded in retrieved content.

### Deliverables
- Summarization service.
- Summary prompt/template.
- Summary result persistence.

### Expected behavior
- Summary describes repo purpose and major structure.
- Summary does not invent unseen details.
- Summary mentions limitations when coverage is sparse.

### Validation
- Run summary on known repos.
- Review whether claims are supported by extracted content.
- Verify limitation handling.

---

## Milestone 7 — Diagnostics and observability

### Goal
Show what happened during the analysis in a clear, inspectable way.

### Deliverables
- Diagnostics event model.
- Diagnostics API endpoint.
- Diagnostics UI view.
- Logging for key stages.

### Expected behavior
- User can see what was accessed, skipped, failed, and why.
- Partial success is clearly visible.
- Errors are not hidden.

### Validation
- Trigger failure cases intentionally.
- Confirm diagnostics capture the failure.
- Confirm UI displays the run state clearly.

---

## Milestone 8 — Local API surface

### Goal
Expose results through a stable local REST API.

### Deliverables
- Endpoints for runs, tree, files, chunks, diagnostics.
- Consistent JSON response schema.
- API tests.

### Expected behavior
- External scripts can consume analysis results.
- Missing or invalid resources return clear errors.
- API responses remain consistent.

### Validation
- Run endpoint smoke tests.
- Confirm response structure.
- Confirm error formatting consistency.

---

## Milestone 9 — Small UI completion

### Goal
Make the local UI usable end to end.

### Deliverables
- Input form.
- Recent runs list.
- Run detail page.
- Tree page.
- Diagnostics page.

### Expected behavior
- A user can complete the flow without touching the API.
- Empty, loading, and error states are readable.
- UI remains lightweight and responsive.

### Validation
- Manual walkthrough on local machine.
- Check main journey from URL input to summary/diagnostics.
- Confirm no broken navigation.

---

## Milestone 10 — Release hardening

### Goal
Make v0.1 stable enough to keep iterating on.

### Deliverables
- README finalized.
- Basic tests passing.
- Clean logs.
- Reliable setup steps.
- Smoke test suite.

### Expected behavior
- Fresh clone can be set up quickly.
- Common failure cases are handled.
- Project feels coherent and maintainable.

### Validation
- Fresh install test.
- Full test suite.
- Smoke suite across multiple repos.
- Manual review of logs and UI.

---

## Global acceptance rule

A milestone is complete only when:
- code matches the spec,
- tests pass,
- expected behavior is visible,
- failures are handled,
- and the result is understandable to a human reviewer.

Running code alone is not enough.