# RepoBridge v0.3 — Hosted workspaces plan (DISCOVERY DRAFT)

**Status:** proposed sequence only. **Blocked on v0.2 M0.** No implementation begins
until M0 closes, the owner approves the security/cost direction, and the free-storage
gate is resolved. `CONTRACT.md` remains authoritative.

## M0 — Close the existing feedback gate

Complete the v0.2 M0 criteria unchanged. Record feedback verbatim, answer the
coverage-disclosure question, amend v0.2, and make its go/re-scope decision. This
future platform proposal does not substitute for any of those deliverables.

**Exit:** every v0.2 M0 criterion has its existing evidence and verdict.

## M1 — Zero-cost, privacy, and security feasibility

No code. Decide whether this product can meet its stated boundaries before choosing
frameworks, schema, or a hosting provider.

**Work**

- Verify the active operator GitHub/Gemini limits from primary provider sources and
  the account/project dashboards. Design global RPM, RPD, concurrency, and headroom
  caps from those live facts; do not spend live analysis quota to probe them.
- Compare Neon Free and Cloudflare D1 as initial $0 candidates for retention lifecycle,
  backup/restore, deletion/export, data location, terms, limits, billing-stop behavior,
  and practical integration; keep Render Free Postgres disqualified for durable
  workspaces because it expires after 30 days and has no backups. Neon is the leading
  migration candidate because the app already uses SQLAlchemy ORM/session patterns,
  but the current project has only the aiosqlite driver and SQLite-specific PRAGMA
  startup/version handling. Plan for a Postgres driver, database-layer changes, and
  migrations; verify free limits, recovery, and no-charge exhaustion behavior.
  Cloudflare D1 requires a binding-compatible storage path and an execution design for
  the current maximum of 102 GitHub calls, versus 50 subrequests per Free Worker
  invocation and a 10 ms CPU limit. Do not select either without a measured proof.
- Confirm the operator host has a no-charge failure mode for included-hours,
  bandwidth, and build limits. Set no-card/spend-stop conditions before deployment.
- Write a threat model for Google identity, session cookies, BYOK transport, XSS/CSRF,
  logs/traces, tenant IDOR, user deletion, and anonymous abuse.
- Propose the narrow I-6 amendment and its value/fragment leak checks. Do not loosen
  I-6 by implication.
- Confirm D3 remains satisfied by public-repository-only behavior under every
  supported user key and provider tier.

**Exit criteria**

- [ ] A dated decision names a viable durable $0 datastore, or explicitly stops the
      durable-workspace direction and asks the owner whether temporary/exportable
      workspaces are acceptable.
- [ ] The Neon proof covers multi-tenant query isolation, connection pooling, cold
      starts, the 100 CU-hour/1 GB project limits and listed network allowance,
      recovery/export, and exhaustion behavior. The D1 alternative is either rejected
      with evidence or has a working design that respects Worker execution/subrequest
      limits and D1 query/storage quotas.
- [ ] No operator payment method or paid-overage path is required to keep the service
      from charging; exhaustion behavior is demonstrated from provider settings.
- [ ] Current provider project/model limits and conservative application caps are
      recorded with dated primary-source/dashboard evidence.
- [ ] Threat model identifies credential transit/storage/log boundaries and the
      session-lifetime decision; each high-risk threat has a control and verification
      criterion.
- [ ] The owner has reviewed the proposed I-6 amendment before credential code is
      authorized.
- [ ] Public-only and free-tier data-use notices remain explicit; private-repository
      support remains blocked.

## M2 — Identity and workspace ownership

Only after M1. Add Google sign-in as identity-only, verified server-side, and create a
first-party session. Introduce account-owned workspaces and short-lived guest-session
scopes in the shared datastore; neither mode may read another scope. Establish
migration strategy before storing account data.

**Exit criteria**

- [ ] Authentication tests reject invalid signature, issuer, audience, expiry, nonce,
      and missing stable subject.
- [ ] Session cookie, CSRF protection, logout, expiration, and session rotation are
      documented and tested.
- [ ] Every run-owned row has an enforceable workspace relationship; no endpoint
      trusts a client-supplied workspace ID.
- [ ] Adversarial tests cover cross-tenant access on every run-scoped route and return
      the same not-found behavior for nonexistent and unauthorized run IDs.
- [ ] Guest runs have short-lived per-session scopes; signed-in runs have per-account
      scopes. Neither mode can list or read another scope.
- [ ] Existing v0.1 accounting and provenance checks pass unchanged; migrations retain
      or intentionally discard data only under a documented decision.

## M3 — Bring-your-own-key session flow

Only after the I-6 amendment is approved. Build the key-entry guide and the shortest
safe-lived browser flow. Begin with public-repository-only requests. No platform
account stores user keys.

**Exit criteria**

- [ ] The user can add, replace, and clear GitHub/Gemini credentials for the supported
      browser session, with refresh/restart behavior stated before entry.
- [ ] Credentials travel only over HTTPS for the operation that needs them; they are
      absent from URLs, analytics, app/proxy logs, diagnostics, HTML, persistent data,
      and responses.
- [ ] Whole-secret and 8-character-fragment scans cover stored rows, rendered pages,
      app logs, proxy-visible logs where configurable, and errors.
- [ ] A missing/invalid user key cannot silently fall back to the operator's key.
- [ ] Mocked provider tests prove per-user routing and error handling without spending
      live GitHub/Gemini quotas.
- [ ] The guide explains GitHub permissions, Gemini project-level quota sharing,
      free-tier data use, rate limits, and user responsibility for provider billing.

## M4 — Fair quotas and operator cost containment

Keep provider quotas separate from app resource limits. Anonymous users consume only
the shared pool and its operator-controlled ceilings. Authenticated users spend their
own provider quotas but remain subject to per-account and global host-compute limits.

**Exit criteria**

- [ ] Shared-mode RPM and daily budgets, concurrency, per-IP limit, and owner reserve
      are configurable and enforced by a shared limiter that survives process restart
      and multi-instance deployment.
- [ ] BYOK requests use the correct user's provider keys; per-user app limits cannot
      be bypassed by calling REST endpoints directly.
- [ ] Users can set personal analysis-per-minute and per-day ceilings below the
      platform's global compute caps; the UI labels these as app limits, separate from
      live provider quotas.
- [ ] Anonymous-pool candidate caps (1 analysis/minute, 20/hour, and at most 80% of
      verified shared Gemini RPD) are reviewed against live project limits and the
      current GitHub calls/run arithmetic; record the approved values with headroom.
- [ ] GitHub primary/secondary and Gemini RPM/TPM/RPD errors are distinguished where
      the response proves the category; provider limits are never inferred from the
      number of keys.
- [ ] Rate exhaustion stops work before additional provider requests and says whose
      app or provider limit was reached and when it may recover.
- [ ] Host bandwidth, CPU, memory, request size, and run retention are bounded so
      anonymous abuse cannot create unbounded operator cost.

## M5 — Durable data, export, and deletion

Only if M1 selected a durable $0 store. Otherwise return to the owner before
implementing persistence; an ephemeral alternative needs its own approved scope.

**Exit criteria**

- [ ] Retention policy is explicit and automatically enforced.
- [ ] A user can export all workspace-owned run data in a documented format.
- [ ] A user can delete their workspace and credentials/session references without
      affecting other workspaces or anonymous data.
- [ ] Restart, redeploy, backup/restore, database expiry, and quota exhaustion behavior
      match the selected provider's actual free-tier terms.
- [ ] Workspace deletion and migration behavior are tested against stored-row
      accounting and ownership invariants.

## M6 — User guide, external review, and controlled release

Deploy behind a reversible feature flag. Keep the anonymous pool disabled or tightly
budgeted until the full cost and abuse gate is proven. Have someone other than the
owner complete onboarding from the guide.

**Exit criteria**

- [ ] A second person can sign in, create an isolated workspace, supply their own
      free/public-only provider keys, run a repository, and explain who can see the
      data and which quotas/costs apply.
- [ ] No paid account feature, automatic paid upgrade, or operator-funded provider
      fallback is present.
- [ ] Live quota verification is performed once at the end, under the provider budget
      rules in `AGENTS.md`.
- [ ] Rollback disables new multi-user access without exposing one tenant's data to
      another; migration and user notification decisions are recorded.

## Sequencing rules and no-go conditions

- M0 blocks every v0.2 implementation milestone. This plan does not bypass it.
- M1 blocks all code in this plan. Security, free cost, and data retention are design
  gates, not deployment chores.
- No durable workspace release on Render Free Postgres alone. Neon Free is only a
  candidate until M1 demonstrates acceptable persistence, recovery, cost, and limits.
- If no durable $0 store exists, do not imply account data is permanent. Ask whether a
  separate temporary/exportable product is acceptable; otherwise mark the direction
  no-go under the user's cost requirement.
- Never convert a free provider error into an automatic paid fallback.
- Private repositories remain gated by D3, regardless of which user supplies the
  provider key.
