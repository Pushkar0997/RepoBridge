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

## Milestone 5 — open item: which 200 files a capped run reads — **RESOLVED 2026-08-18**

**Recorded 2026-08-18. Not a defect in Milestone 5; a ranking question for Milestone 6.**
**Resolved the same day, by measurement rather than by argument — see the resolution at
the end of this section.**

The read cap (`ExtractionConfig.max_files_per_run`, default 200) takes the *first* N
selected files. Selection order is classification order, which is GitHub's tree order,
which is roughly alphabetical by path. So a capped run reads the alphabetically-first 200
files, not the most useful 200.

For `github/docs` (11,215 selected) that means content is drawn from whatever sorts early
— likely `.github/`, `api/`, `assets/` — while the repository's actual documentation may
sort later and never be read. The run reports this honestly (`read 200 of 11,215`), so
nothing is hidden, but the *sample* is arbitrary rather than representative.

This matters at Milestone 6, not before: a summary grounded in an alphabetical slice of a
large repository would be grounded in the wrong 2%. Options to weigh then:

- rank by path depth and name (`README.md`, top-level docs, package entry points first);
- rank by directory importance (`src/`, `docs/` ahead of `.github/`, `examples/`);
- rank by file size, on the theory that substantial files carry more signal;
- sample across directories rather than taking a prefix, so coverage is spread.

Whatever is chosen, the honesty rule stands: the run must keep saying how many of how many
it read, and unread files must keep their `not_fetched` status.

### Resolution — 2026-08-18

**This was not decided on the reasoning above. It was decided by a live run that showed the
predicted failure actually happening**, which is worth more than the four options were.

`smoke.md` Run 8 capped `psf/requests` at 20 files. Tree order gave it **18 `.github/`
files** plus `.coveragerc` and `.git-blame-ignore-revs`; `README.md` and every module of
`src/requests/` were `not_fetched`. The summary generated from that slice disclosed its
coverage accurately and then described the project as *"heavily structured around GitHub
infrastructure and automation"* — grounded in every particular, and wrong about the
repository. The prediction in this section, that a capped run would be "grounded in the
wrong 2%", is confirmed.

**What was implemented:** `core/ranking.py:rank_files`, applied in
`core/extraction.py:fetch_and_extract` before the cap splits. It reuses the ranking signals
already defended for chunk selection — README and orienting documents first, shallower
paths, `docs/` above `.github/` and `tests/`, prose before code — which now live in
`core/ranking.py` and are shared by both stages so they cannot drift apart.

**The four options weighed above, resolved:** options 1 and 2 (rank by depth/name and by
directory importance) are what the shared signals do. Option 3 (rank by file size) was
rejected for the same reason `rank_chunks` rejects it: a large file is not a more
explanatory one. **Option 4 (sample across directories) turned out to be necessary, not
optional**, and is the one thing file ranking needs that chunk ranking does not:

> Ranking by signals alone still read README plus the whole of `docs/` and **zero** files of
> `src/requests/` at a cap of 20 — a different concentration, not a fixed one. `rank_chunks`
> orders content already read, so every area is in the pool and a pure sort only decides
> what comes first; `rank_files` decides what is read at all, and an area the cap never
> reaches is absent from the summary's evidence entirely. So `rank_files` round-robins
> across top-level areas after ranking.

**The honesty rule is untouched, and now tested as such.** Ranking is a permutation:
`selected == read + failed + not_fetched` holds over a different partition of the same set,
a run under the cap reads everything regardless of order, and every unread file still
carries `not_fetched` with its reason (`tests/test_ranking.py`).

**Measured effect**, `psf/requests` at a cap of 20:

| Ordering | README | `src/requests/` files | `.github/` files |
|---|---|---|---|
| Tree order (shipped until now) | not read | 0 | 18 of 20 |
| Signals only | read | 0 | 1 |
| Signals + area spread (implemented) | read, first | 3 | 4 |

Verified live in `smoke.md` Run 9.

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

### Deferred design item — logging hooks inside core modules

**Not a Milestone 7 criterion. Recorded so the gap is a known decision, not an oversight.**

`tasks.md` lists "add logging hooks in core modules to keep logs and diagnostics aligned"
under Milestone 7. What was built satisfies the *alignment* half completely and the
*coverage* half only for recorded events, and the difference is a design question rather
than a missing edit — which is why it is here rather than holding the milestone open.

**What exists.** Every diagnostic event is logged at the moment it is recorded, in
`core/diagnostics.py:Recorder.record`, with severity derived from the event's level. Logs
and the timeline therefore cannot disagree about anything the pipeline records: there is
one call site, not two parallel sets of statements that drift.

**What does not.** `core/selection.py`, `core/extraction.py` and `core/github_client.py`
emit no logging of their own. Anything those modules do that the API layer does not turn
into an event appears in neither the log nor the timeline — a retry inside the content
reader, say, or the reasoning behind a specific classification.

**Why this is a design question and not a mechanical addition.** Adding logging to those
modules means deciding what they should say *independently of the timeline*, and the two
plausible answers pull in opposite directions:

- **Log only what is not an event.** Keeps the log a debugging surface for the mechanics
  diagnostics deliberately aggregates away — per-request retries, per-file decisions,
  timing. Risk: two surfaces with different content, and a reader has to know which to
  consult for what.
- **Log everything, and let events be the filtered subset.** One narrative, and the
  timeline is a view over it. Risk: `kubernetes/kubernetes` classifies 37,393 entries, and
  a log line per entry is exactly the volume the event model was designed to refuse. The
  "no silent failures" principle in `AGENTS.md` does not require narrating every success.

There is also a scope question underneath: structured logging is listed under Engineering
Standards for the project as a whole, not as a diagnostics feature, so the right home for
this may be Milestone 10 (release hardening, "review logs for noise and missing context")
rather than Milestone 7.

**Deliberately unresolved here.** Decide it when logs are reviewed as a whole, at Milestone
10. Whatever is chosen, the property already established must survive it: a recorded event
and its log line come from one call site and cannot drift apart.

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

---

## Milestone 10.5 — Shared demo instance (interim posture)

**Numbered 10.5, not 11, because it is not the next step toward the product.** It is a
sideways move to get one instance in front of a handful of testers for a feedback round,
and it should be recognisable as such later.

### What this posture is

One instance. **The operator's** GitHub token and Gemini key. **One database, visible to
everyone who has the URL.** No accounts, no login, no per-visitor keys, no session
isolation, no privacy between visitors. Intended for a small feedback round with people
who have been told what it is; **not intended for public release**.

Every analysis a visitor runs appears in every other visitor's runs list, along with the
repository they chose. The landing page says so in the first thing on the page, because a
tester who has not been told that will assume otherwise.

### What is deliberately not built, and why

**Auth, per-user keys and session isolation are a later milestone.** Building them now
would be building the wrong thing, for three reasons worth writing down:

1. **The feedback round does not need them.** A handful of known testers looking at public
   repositories do not need to be hidden from each other. What they need is for the
   instance to still be working when the fourth of them arrives.
2. **They would be built against guesses.** Whether RepoBridge ends up multi-user at all,
   and whether users bring their own keys or share the operator's, is exactly the sort of
   question this feedback round exists to answer. Building the mechanism first would
   fix the answer before the question was asked.
3. **They are not what breaks first.** What breaks first is the quota: one visitor pasting
   `kubernetes/kubernetes` can spend the read budget for the whole demo. That is the
   problem this milestone solves and the only one it solves.

Also not built: any attempt to make the rate limits survive a restart or work across
processes. Both would mean Redis or a schema, for a demo that runs one worker.

### What was built

- **Spend control** (`core/limits.py`): three limits, all off by default, all switched on
  by `REPOBRIDGE_DEPLOYMENT=shared`, all individually overridable — analyses per hour for
  the instance, analyses per hour per visitor, and a maximum repository size checked after
  two GitHub calls and before up to two hundred content reads. Refusals name the limit,
  what is used, and when it lifts, like every other limit in the project.
- **Platform configuration**: `python -m repobridge` reads `HOST`/`PORT` from the
  environment and binds `0.0.0.0`; a `Dockerfile` as a fallback; the database path already
  came from the environment and was verified to.
- **An ephemeral-storage posture** (`REPOBRIDGE_STORAGE=ephemeral`): declared rather than
  detected, because a wiped database and a new one are indistinguishable. Its one hard
  requirement is that **a wiped database is never presented as though nothing was ever
  analysed**.
- **First-contact copy**: what this is, what to paste, how long it takes, that it is a
  shared demo, and what the limits are. The configuration panel no longer tells visitors
  to set keys that are not theirs.

### The boundary this posture must not be allowed to blur

**Nothing here is a security control.** Per-visitor identity is an IP address from a
header the client controls. The limits are fairness between honest testers and a ceiling
on the operator's bill — nothing more. If this instance is ever exposed beyond a known
group, the correct move is to take it down, not to tighten these numbers.

### When to leave this posture

Whichever comes first:

- the feedback round ends — take the instance down;
- someone wants to use RepoBridge on repositories they would not post publicly — that is
  the requirement that forces real isolation, and it should be built as its own milestone
  with the question it answers written down first;
- the instance needs more than one worker — at which point the limits silently double, and
  the shared-state problem has to be solved properly rather than deferred again.

### Recorded consequence, not resolved

The API remains unauthenticated and unversioned, so anyone with the URL can call
`POST /api/analyze` directly and bypass the UI entirely. The rate limits apply to the
endpoint, not to the page, so they still hold — but there is no other barrier, and the
`v0.1 API is unstable` statement in the README now has a second reading: it is also
unprotected. Acceptable for a known group behind a shared link; not acceptable for a URL
that gets posted anywhere.

## Global acceptance rule

A milestone is complete only when:
- code matches the spec,
- tests pass,
- expected behavior is visible,
- failures are handled,
- and the result is understandable to a human reviewer.

Running code alone is not enough.