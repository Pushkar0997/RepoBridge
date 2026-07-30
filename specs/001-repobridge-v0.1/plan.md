# RepoBridge v0.1 Plan

This plan breaks RepoBridge v0.1 into small milestones with clear deliverables, validation checkpoints, and expected behavior after each stage.

The goal is to build the project in a production-minded way while keeping the scope small enough for a local-first MVP.

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
Fetch repository metadata and tree structure using official GitHub APIs.

### Deliverables
- GitHub client module.
- Repo metadata retrieval.
- Tree retrieval for a valid ref/branch.
- Rate-limit and not-found error handling.

### Expected behavior
- Public repos can be retrieved.
- Tree structure is accurate and nested correctly.
- Errors are surfaced clearly.
- Analysis continues safely when possible.

### Validation
- Use a small set of sample public repos for smoke tests.
- Verify tree completeness.
- Verify error messages for nonexistent repos.
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

---

## Milestone 4 — Extraction and normalization

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

## Milestone 5 — Grounded summary generation

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

## Milestone 6 — Diagnostics and observability

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

## Milestone 7 — Local API surface

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

## Milestone 8 — Small UI completion

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

## Milestone 9 — Release hardening

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