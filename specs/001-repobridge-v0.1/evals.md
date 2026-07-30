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
- Rate-limit conditions are visible in diagnostics.
- Retrieval completes for normal public repos.

### Failure signals
- Silent tree truncation.
- Wrong branch/ref handling.
- Generic “something went wrong” errors with no detail.

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

## Milestone 4 – Extraction and normalization evals

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

## Milestone 5 – Summary generation evals

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

## Milestone 6 – Diagnostics evals

### What to verify
- The diagnostics view shows each major stage.
- Skipped files and failure reasons are visible.
- Partial success is explicitly represented.
- Error cases are understandable without reading logs.

### Success criteria
- Every meaningful failure has a trace.
- Diagnostics help explain what happened.
- The system does not hide limitations.

### Failure signals
- Missing stage events.
- Empty or vague diagnostics.
- Runs that appear successful despite major failures.

---

## Milestone 7 – API evals

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

## Milestone 8 – UI evals

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

## Milestone 9 – Hardening evals

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