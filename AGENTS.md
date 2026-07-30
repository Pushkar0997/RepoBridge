# RepoBridge Development Constitution (AGENTS.md)

## Purpose

RepoBridge is a lightweight local-first tool that turns public GitHub repositories into grounded, structured context for LLM workflows.

This document defines how humans and AI assistants should work on this repo. It exists to keep the project disciplined, spec-driven, and production-minded from the start.

---

## Core Principles

- **Spec-first** – Specs in `specs/` define what to build. Code should follow the spec, not lead it.
- **Small, local, focused** – v0.1 is a small local tool, not a platform or cloud service.
- **Grounded behavior** – Summaries and outputs must be grounded in retrieved content, with clear limits.
- **Explainability** – Diagnostics must show what was accessed, skipped, or failed. No black-box behavior.
- **No silent failures** – Errors are surfaced and logged; degraded runs are explicit.
- **Incremental work** – Build in small milestones with clear acceptance criteria and evals.

---

## v0.1 Boundaries

In scope for v0.1:

- Public GitHub repositories.
- Local FastAPI server and SQLite storage.
- Small web UI (server-rendered).
- Repo tree, file selection, extraction, summary, diagnostics.
- Local REST API for external tools or scripts.

Explicitly out of scope for v0.1:

- Arbitrary website crawling.
- Browser automation or headless browsers.
- Auth, accounts, and permissions.
- Billing and payments.
- Cloud sync or hosted multi-user deployment.
- Private repository support.
- Multi-agent orchestration.
- Vector databases and advanced code intelligence.
- MCP server implementation (only a future consideration).

---

## Engineering Standards

- **Modular architecture** – Separate `core`, `infra`, `api`, and `ui` modules under `src/repobridge`.
- **Typed models where reasonable** – Use Pydantic / type hints for clarity.
- **Consistent error handling** – Shared error patterns and responses.
- **Structured logging** – Logs should be helpful for debugging, not noisy.
- **Tests from the beginning** – At least basic tests for core modules and API.
- **Config, not hardcoded** – Use config/environment values instead of scattering constants.
- **Readable code** – Aim for clarity; this project should be understandable by a single developer.

---

## AI‑Assisted Development Rules

When using an AI assistant (like this one) to work on RepoBridge:

- Always start from the current spec (`specs/001-repobridge-v0.1/spec.md`) before coding.
- Do not add features outside the approved scope without updating the spec first.
- For each change:
  - restate the goal,
  - identify files to edit,
  - restate acceptance criteria.
- Prefer small, reviewable changes over big rewrites.
- Ask clarifying questions instead of assuming requirements.
- Explain tradeoffs when making architectural decisions.
- Keep prompts and responses focused; avoid “random” coding.

---

## Quality Gate

A task is considered **done** only when:

- Implementation matches the spec.
- Acceptance criteria for that task are satisfied.
- Relevant tests and eval checks pass.
- Errors are handled or explicitly deferred with TODOs.
- The code and behavior are understandable and explainable to a human reviewer.

Running code alone does **not** mean success.

---

## Product Philosophy

RepoBridge should feel like a trustworthy tool, not a magic trick.

Users should always be able to see:

- what was accessed,
- what was skipped,
- what failed,
- and how summaries and outputs were produced.

The goal is to make repo context inspection reliable, grounded, and pleasant to work with, without turning RepoBridge into a heavy, overcomplicated system.