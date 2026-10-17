# RepoBridge v0.3 — Hosted workspaces (DISCOVERY DRAFT)

**Status:** proposal only, dated 2026-10-17. Blocked on v0.2 M0, security review,
and a zero-cost storage/hosting feasibility decision. This file does not authorize
implementation and does not supersede `CONTRACT.md` or shipped v0.1 behavior.

## 1. Purpose

Scope the owner's requested next product shape: keep an anonymous shared demo for
casual visitors, and offer Google-authenticated users isolated workspaces where they
bring their own GitHub and Gemini credentials. The operator's cost target is **$0**.
If that target cannot be met without unreliable or non-durable storage, the platform
must be re-scoped before it is built.

The core RepoBridge guarantee remains unchanged: outputs say what was accessed,
skipped, or failed, and never claim to have read content that was not read.

## 2. Proposed product modes

### 2.1 Anonymous shared demo

- No account is required.
- Requests use the operator's configured provider credentials, if present.
- A clearly visible notice says provider capacity is shared and guest data is
  temporary. The mode accepts public GitHub repositories only. Each guest browser
  session receives a short-lived logical data scope in the shared database; guests
  cannot list or open another visitor's runs. Shared quota must not imply shared data
  visibility. A public run gallery would require a separate explicit opt-in design.
- One instance-wide budget controls provider requests per minute, provider requests
  per day, concurrent analyses, and total analysis starts. Per-IP and per-visitor
  limits are additional abuse controls, not a substitute for the global budget.
- When any global budget is exhausted or unknown, refuse new work with the reset or
  recovery condition. Never silently switch to a paid provider tier or to a user's
  personal key.

### 2.2 Google-authenticated workspace

- Google sign-in establishes identity only. It does not grant access to Google Drive
  or other Google APIs. The server validates Google's signed ID token and uses its
  stable `sub` claim as the account identity; do not trust a client-supplied email or
  user ID as proof of identity.
- Each account has a **logically isolated workspace** for its runs, repository
  inventory, chunks, diagnostics, and preferences. A user can list or open only their
  own workspace data. Anonymous demo data remains in its separate shared scope.
- Users provide their own GitHub token and Gemini API key for analysis. The app never
  falls back to operator credentials for a signed-in user's run. The setup guide
  explains least privilege, model/project quotas, provider terms, and how to replace
  or revoke keys.
- Provider keys are scoped to the active browser session and are not saved in the
  account, database, cookies, local storage, logs, diagnostics, templates, or
  responses. The initial security proposal is to hold keys in browser memory and send
  them in dedicated request headers over HTTPS only for the analysis that needs them;
  request bodies and URLs never carry them. A full reload requires re-entry. The exact
  request transport, server/proxy redaction, and threat model must be reviewed before
  implementation.
- The server necessarily receives a user's keys in process memory to call providers.
  The UI and privacy notice must say this plainly: keys are used transiently, but the
  service operator controls the application runtime. Do not claim keys are hidden from
  the operator or storage provider at the infrastructure level.
- An app-level per-account limit protects the host. It does not claim to be the
  provider's actual remaining quota. Usage and provider refusals are attributed to the
  correct provider account/project when the available response data proves that.
- Users can set a personal app-side ceiling for analyses per minute and per day,
  below the platform's global compute ceilings. This is a self-imposed limit, not a
  claim that the app can read or control the provider's full account quota.

## 3. Data isolation and storage

"Each user gets their own database" means a private logical workspace, not a physical
database instance per user. One relational database with a mandatory `workspace_id`
on every run and tenant-owned child row is the proposed free-hosting design. Every
run-scoped read, write, re-summary, and delete must be scoped through authenticated
workspace context; a UUID is not authorization. Use foreign keys and composite
constraints where they can enforce parent/workspace ownership. No public or admin
endpoint may expose signed-in user content across workspace boundaries.

This application-level isolation prevents other RepoBridge users from reading a
workspace; it is not cryptographic isolation from the service operator or database
provider. The privacy notice must distinguish those properties.

Each signed-in user must be able to export and delete their own workspace data.
Retention is explicit and visible. Guest data has a separate, short retention period
and cannot be used as shared history. Migrations are required before data that cannot
be regenerated is stored.

**Storage is an open release gate.** The current Render Free service has no persistent
disk. Render's free Postgres expires after 30 days, is limited to 1 GB, and has no
backups; it is not a suitable promise of durable user workspaces. Neon Free is the
leading first candidate for a migration proof because it offers managed Postgres and
the app already uses SQLAlchemy ORM/session patterns. It is not drop-in compatible:
the current project has only the `aiosqlite` driver and its database startup/version
code uses SQLite `PRAGMA` statements. A Postgres driver, database-layer changes, and
a migration strategy would be required. Neon's published free allowance includes
100 CU-hours and 1 GB per project; the current plan also lists a 5 GB monthly network
transfer allowance per project. Compute suspends when included limits are exhausted,
and storage-cap behavior, recovery guarantees, regional availability, and billing
controls must be verified before relying on it. Its limited restore/snapshot options
may not meet the required recovery promise. Treat this as a candidate, not a selection
or guarantee; provider terms and limits can change.

Cloudflare D1 is an alternate $0 candidate but does not fit the current runtime without
a storage and execution redesign. The current run can make up to 102 GitHub calls,
while a Free Worker invocation is limited to 50 subrequests and 10 ms CPU; the current
SQLAlchemy/aiosqlite storage path is not assumed to work through D1's binding API.
Cloudflare's Python Workers ASGI support is also a compatibility question, not proof
that this workload fits its limits. Any D1 proposal must show how analyses are split
across invocations and how database access is adapted, while preserving accounting and
provenance invariants.

Before implementing accounts, compare the candidates on lifecycle, backups/restore,
quotas, terms, data location, fail-closed billing, integration effort, and exit/export
path. Do not create one database per account. If no durable $0 option passes, stop and
ask whether an explicitly temporary workspace with user export is acceptable; do not
describe it as permanent storage.

## 4. Provider quotas are independent of app quotas

- GitHub's standard authenticated REST API primary limit is **5,000 requests per
  hour per user**, not 5,000 per minute or per day. Secondary limits still apply.
  Read the headers on actual responses and do not infer the user's remaining budget
  from a generic constant.
- Gemini limits vary by model and tier and are applied **per Google project, not per
  API key**. Several keys created in the same project therefore do not create several
  independent quota pools. The active project/model limits in AI Studio are the
  source of truth; no universal `5 RPM` or `100 RPD` value is assumed.
- A one-request-per-minute policy alone does not bound daily consumption. Any shared
  operator key needs both RPM and RPD limits, concurrency control, a daily budget with
  headroom, and a fail-closed path. Count every provider call attempt, including
  retries and re-summarization. Each account using BYOK needs separate app-level limits;
  sharing the same provider account/project can still share its provider quota.
- The owner's proposed initial shared-pool ceilings are one analysis start per minute
  across anonymous visitors and the current 20 starts per hour. Separately gate Gemini
  provider call attempts (including retry attempts and re-summarization) at no more
  than one per minute and a daily cap no higher than 80% of the active project's
  verified RPD; the remaining 20% is an owner/uncertainty reserve. These are
  conservative application caps, not provider guarantees. Recompute them before
  release from the live project quota and GitHub calls per analysis. At current hosted
  limits, a full run can make up to 102 GitHub calls and a summary invocation starts
  with one Gemini call; retries and re-summarization add calls to the same budget.
- A provider 429 is surfaced with its structured reset/recovery information when
  available. Daily quota exhaustion is not retried as if it were a short per-minute
  wait. The app stops at its own configured limits even if the provider would allow
  more.

Vendor references reviewed 2026-10-17:

- [GitHub REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Google AI Studio and Gemini API terms](https://ai.google.dev/gemini-api/terms)

## 5. Privacy, credentials, and private repositories

The current `CONTRACT.md` I-6 forbids request-supplied credentials. This draft does
not override it. Before BYOK implementation, propose and approve a narrow I-6
amendment covering authenticated, transient user credentials and specify its tests:
no credential in URLs, persistent storage, logs, traces, errors, rendered pages, or
responses; value and fragment scans at each boundary; TLS; CSRF/XSS protections; and
safe handling by the app server and any proxy. Never put a provider key in Google
OAuth scopes, a cookie, or a URL. The UI must disclose that the backend receives the
key transiently and is operated by the owner; diagnostics never expose it.

Google sign-in is authentication, not provider-key authorization. Use only the
identity scopes needed for sign-in, validate the ID token server-side, and establish
a first-party session with secure cookie and CSRF protections. Follow Google's
[backend authentication guidance](https://developers.google.com/identity/sign-in/web/backend-auth).

Private repositories remain out of scope. A user's own key does not remove the
Gemini unpaid-service terms: Google says content submitted under unpaid Gemini API
quota can be used to improve products and may be reviewed by humans. Keep the app
public-repository-only until the data-use gate in D3 is independently cleared. Tell
users not to submit sensitive, confidential, or personal material to the free tier.

## 6. Zero-cost operating requirements

- No subscriptions, billing integration, paid deployment plan, paid database, or
  automatic upgrade is part of this product direction.
- Distinguish the operator's cost from each user's provider-account cost. BYOK avoids
  spending the operator's provider quota; it does not guarantee that a user's
  provider project is free. The guide must tell users to check billing and free-tier
  status before using a key. Never silently route a user's run to another account.
- The operator's host must be configured so exhausting a free allowance stops or
  suspends service instead of incurring a charge. Track included bandwidth/build
  budgets and impose application request/body/concurrency limits. A free label is not
  evidence of a $0 guarantee.
- Render's current free-service details include 750 instance hours per workspace,
  spin-down after inactivity, and no persistent disk on a Free web service. A missing
  payment method avoids some overage charges by suspending services, but creates
  availability and build constraints. Confirm workspace billing controls before
  release; no spec assumes a provider's free terms stay unchanged.

References reviewed 2026-10-17:

- [Render: Deploy for Free](https://render.com/docs/free)
- [Render: Outbound bandwidth](https://render.com/docs/outbound-bandwidth)
- [Neon: Free plan](https://neon.com/docs/introduction/plans)
- [Neon: Free plan update](https://neon.com/blog/neon-free-plan-1-gb-per-project)
- [Cloudflare D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)
- [Cloudflare D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Cloudflare Python Workers FastAPI support](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/)

## 7. Non-goals

- A physical database or Render service per user.
- Private GitHub repositories until D3's provider-data gate is cleared.
- Storing user provider keys server-side or making them reusable across sessions.
- Platform billing, subscriptions, paid quotas, or operator-funded unlimited use.
- Teams, sharing between signed-in workspaces, or operator browsing of user runs.
- Guaranteeing durable workspaces before a free persistent storage provider passes
  the feasibility gate.

## 8. Acceptance criteria for a future implementation

These are draft criteria and are not active until M0 closes and the owner approves the
scope and security amendment.

- Google authentication is verified server-side; invalid, expired, wrong-audience,
  and replayed login credentials cannot establish another user's session.
- Adversarial cross-workspace checks cover every run-scoped surface: list, detail,
  files, chunks, summary, diagnostics, re-summary, export, and delete. A guessed UUID
  from another workspace reveals no existence or content.
- Anonymous provider quota is unmistakably disclosed as shared; guest sessions cannot
  list or open one another's runs, and signed-in runs never appear in anonymous lists
  or another account's workspace.
- Keys never reach persistent rows, URLs, rendered HTML, logs, diagnostics, error
  messages, traces, or responses. Tests scan whole values and fragments. Credentials
  clear from the supported browser session on logout/close, with documented behavior
  for refresh.
- Provider keys never cross users or fall back to the operator key. Mocked tests prove
  the exact credentials used for each mode without spending live quotas.
- Shared and per-user RPM, daily request, concurrency, and application resource caps
  are enforced across service restarts/instances using the selected shared state
  mechanism. Exhaustion produces an actionable refusal and no automatic retry that
  spends more provider quota.
- Every workspace query is tenant-scoped; stored-row accounting invariants I-1 and
  provenance invariants I-2 through I-7 remain true within each workspace.
- Export and delete operate only on the signed-in user's data, with retention and
  deletion behavior documented and verified.
- The selected hosting and storage setup demonstrates an operator bill of $0 under
  its published free limits, and stops before paid overages. The UI does not claim
  that users' own provider accounts cannot incur charges.
- A second person follows the setup guide and successfully creates a Google identity,
  adds least-privilege/public-only provider credentials, reaches their own workspace,
  and understands the free-tier privacy and quota limits.

## 9. Open decisions before implementation

1. Does the owner accept temporary/exportable workspaces if durable storage cannot be
   delivered for $0? If not, the platform is a no-go until a durable free provider is
   found.
2. What minimum provider-key lifetime is acceptable: memory-only for one browser tab,
   or a longer client-side session with an explicitly accepted XSS risk? Server-side
   persistence is excluded by this draft.
3. Which free durable datastore, if any, meets the actual retention, backup, privacy,
   and cost requirements?
4. Does the owner approve the proposed initial shared-pool caps (1 analysis/minute,
   20/hour, and daily Gemini requests capped at 80% of verified RPD), after checking
   the current project quota and GitHub call arithmetic?
5. What user-facing terms, privacy notice, retention window, and support boundary are
   required before exposing Google sign-in to the public?
