# Administrator Access and Moderation Audit

Date: 2026-11-24  
Audited revision: `7b01f6d70d7af53edc06216337e276fcd119ee91`  
Scope: source and migration review only. No live environment variables, database records, or production services were accessed.

## Controls verified

- Admin endpoints for diagnostics, report review/listing, and suspension management use the `require_admin` dependency.
- `require_admin` relies on the `StudioUser` produced by token verification; caller-supplied role values are not accepted by these routes.
- Supabase access tokens are verified against the project's JWKS, issuer, audience, expiry, and allowed signing algorithms.
- When `OWNER_USER_ID` is configured, administrator identity is matched against the canonical Supabase UUID. A malformed configured owner UUID fails closed to the creator role.
- Report submission derives `reporter_user_id` from the verified user identity; the client cannot choose the reporter field through the route.
- Suspension creation rejects an administrator attempting to suspend their own account.
- Moderation storage errors are returned as generic messages rather than upstream response bodies.
- The moderation migration enables RLS and revokes direct client access to suspension and audit tables. The audit table is granted server-side SELECT/INSERT only and explicitly has UPDATE/DELETE/TRUNCATE revoked from `service_role`.
- Notification list and read operations filter by the authenticated user's ID.

## Findings and recommendations

### A1 — Immutable owner ID must be confirmed in production (high priority)

The auth service retains a backward-compatibility path: if `OWNER_USER_ID` is empty, admin identity falls back to matching the token's email claim against `OWNER_EMAIL`. Email addresses can change and are a weaker administrator identifier than the immutable Supabase Auth UUID.

**Recommendation:** verify through a safe, read-only configuration check that production has `OWNER_USER_ID` set to the intended owner UUID. Do not paste the UUID or any secret into chat or commit it. Once verified, remove the email fallback in a separately tested change.

### A2 — Moderation state mutation and audit insertion are not atomic (high priority)

Report review, suspension creation, and suspension revocation mutate their primary table and then call `_write_audit` as a separate REST request. If the audit insert fails after the first request succeeds, the moderation action remains applied without its corresponding audit event.

**Recommendation:** move each state change and audit insert into a single narrowly scoped database transaction/RPC. Add an idempotency key or equivalent duplicate-action protection and verify the returned audit event.

### A3 — Suspension checks are read-before-action (medium priority)

`ensure_user_not_suspended` performs a separate read before feature execution. A suspension can be created between the check and the protected action. The current check is useful but is not a transaction-level enforcement boundary.

**Recommendation:** enforce suspension state within the transaction that performs each protected mutation or privileged operation. For long-running AI jobs, re-check at the server-side job/charge boundary.

### A4 — Admin listing endpoints are capped at 100 without pagination (medium priority)

Report and suspension listing endpoints request at most 100 rows and expose no cursor. Older cases may become inaccessible through the current admin API as the dataset grows.

**Recommendation:** implement stable cursor pagination, bounded page sizes, and deterministic ordering; preserve filters and audit access controls.

### A5 — Audit log has no read-only admin API in the reviewed routes (medium priority)

The migration creates a server-managed append-only audit table, but the reviewed API exposes no endpoint to browse or export those events. This reduces operational usefulness and makes it harder to detect missing events.

**Recommendation:** add a read-only, paginated admin audit endpoint guarded by `require_admin`. Never expose audit log writes, edits, or deletes to the client.

### A6 — No dedicated route/service tests for moderation mutation failure paths (medium priority)

Current tests cover key schema validation and admin route authorization, but the reviewed test set does not demonstrate that report/suspension mutations fail safely when audit writes fail, nor that cross-account report data is hidden from non-admin callers.

**Recommendation:** add tests for creator denial on every admin endpoint, invalid/missing admin identity, audit-write failure, duplicate/repeated revocation, cross-account report submission identity, and pagination boundaries.

## Rollout gates

1. Confirm production `OWNER_USER_ID` is set to the intended UUID using a secure settings view; never expose it in logs or chat.
2. Reconcile live RLS, grants, migration ledger, and actual RPC availability before any database change.
3. Implement transactional moderation RPCs and regression tests in the feature branch.
4. Add paginated admin audit read access, protected by immutable admin identity.
5. Re-run backend and frontend CI before requesting production approval.

## Explicit non-actions

- No production environment variable was read or changed.
- No user or moderation records were accessed.
- No SQL or migration was executed.
- No suspension, report, or audit event was created or changed.
- No deployment or PR merge was performed.

## Audit refresh — administrative cabinet UI and operational coverage (2026-11-24)

### What is actually present in the frontend

The current account page contains an owner-only moderation panel. It provides:
- a refresh action;
- a report list with reporter/target identifiers, description and content reference;
- status and moderator-note editing;
- a suspension form with target UUID, reason, scope and optional expiry;
- a suspension list and revoke action.

The panel is hidden on account changes and is revealed only after the backend `/api/auth/me` response reports the server-derived `admin` role. The role-load and initial admin-workspace load both check the auth-context version after asynchronous reads. This is a useful UI safeguard, not an authorization boundary; every backend route must continue to enforce `require_admin`.

### What is not yet an administrative cabinet

The reviewed frontend and route inventory do not provide:
- a dedicated audit-history page or `GET /api/admin/audit-log` endpoint;
- pagination/search/filtering for reports, suspensions or audit history (the service lists are capped at 100);
- operational analytics for visitors, generation volume, AI token/cost telemetry, provider spend or revenue;
- tariff/plan management, subscription lifecycle or payment administration;
- wallet balance/reservation/ledger management UI;
- asset/storage administration or media moderation queue;
- a complete PУЛЬС publication, likes, comments or creator-follow moderation workflow.

The wallet and pricing modules are source-level foundations only: the production catalog is intentionally empty and the current chat/prompt routes do not reserve or settle user credits. Do not present those modules as an active financial cabinet.

### Additional UI concurrency observation

The admin workspace list loader checks the initiating auth-context version after its parallel reads. The individual report-review and suspension-form/revoke handlers do not consistently capture and re-check that same version after their mutation requests before updating feedback or refreshing the panel. This is a stale-UI race during account switching, not evidence that one account can read another account's data. Before expanding the admin UI, capture the initiating user ID/context version for every mutation and suppress all post-await UI work when the context has changed.

### Moderation audit event attribution

The service now populates the migration's dedicated `target_user_id` for report review (when a reported account exists), suspension creation and suspension revocation. Tests assert actor and target are distinct and correctly attributed. This improves traceability but does not resolve the still-open M1 transaction gap: the state mutation and audit insert remain separate REST operations.

### Current readiness summary

| Area | Source-level status | Release assessment |
|---|---|---|
| Immutable owner UUID auth | Implemented with legacy email fallback | Verify production `OWNER_USER_ID` securely; do not disclose it |
| Admin route guards | Implemented for diagnostics, reports and suspensions | Keep route-level tests and backend guards |
| Report review | Implemented, no pagination/concurrency version | Needs atomic mutation + audit and optimistic concurrency |
| Suspension create/revoke | Implemented, no pagination/idempotency | Needs atomic mutation + audit and duplicate-action protection |
| Append-only audit storage | Migration source defines server-only insert/read | Live grants/policies not verified |
| Audit history UI/API | Not implemented | Required before operational use at scale |
| Analytics/finance/billing | Not connected or intentionally inactive | Do not activate pending cost and schema reconciliation |
| Full admin control center | Partial moderation workspace only | Not complete |

## Explicit boundaries reaffirmed

This is a repository-source audit, not a live production certification. No live owner configuration, user rows, moderation data, billing settings or production secrets were read. No SQL was executed, no financial feature was activated, no deployment was made, and PR #4 remains unmerged.

## Admin audit-history API — implementation update (2026-11-24)

A read-only endpoint has now been added on the feature branch:

- `GET /api/admin/audit-log`
- server-side `require_admin` dependency;
- page-based pagination, default 50 and hard maximum 100 rows;
- stable descending order by `created_at`, then `id`;
- optional exact filters for actor UUID, target UUID, action and entity type;
- bounded fetch of `page_size + 1` rows to compute `has_more`;
- response returns only the selected audit columns; no write/update/delete route was added.

The service validates actor and target UUIDs before any storage request. Query syntax and page bounds are validated by FastAPI. The existing migration source grants service-role SELECT/INSERT on the audit table and denies client roles; this API reads through the server-only service role after the admin guard. Tests cover unauthenticated and creator denial, admin access, filters, stable order, pagination bounds, and invalid input.

### Remaining limitations

- Pagination uses offset-based pages. Under concurrent inserts, a new event can shift page boundaries; consumers should refresh from page 1 and avoid treating page numbers as immutable cursors. A future cursor based on `(created_at, id)` is preferable for very large audit histories.
- The owner workspace now includes a dedicated audit-history section with actor/target/action/entity filters, 25-row page navigation, refresh through the moderation workspace, and expandable metadata details. It is only rendered inside the server-role-gated admin panel; the API independently enforces `require_admin`.
- No live Supabase grants, RLS, migration ledger or table contents were inspected. The endpoint is source-level only until the production schema is reconciled and the migration's presence is confirmed.
- The state-change/audit-write transaction gap in moderation mutations remains open; this read endpoint does not fix it.


### Frontend connection and CI update (2026-11-24)

The admin workspace now calls `GET /api/admin/audit-log` after loading moderation lists. It renders the selected page using DOM text nodes (including metadata via `textContent`, not HTML injection), exposes exact-match filters, and disables forward navigation when `has_more` is false. Responses are discarded when the signed-in account context changes while a request is in flight. The panel is hidden unless `/api/auth/me` confirms the admin role; the API guard remains the actual security boundary.

Both required CI checks completed successfully for the frontend connection commit: backend test workflow and movie-cloud-context workflow. The API test commit's backend tests also completed successfully. These checks validate repository code only; they do not establish production Supabase schema/grants or live audit data availability.


## Follow-up review — admin mutation context and operational dashboards (2026-11-24)

### Account-switch race hardening

The report-review, suspension-revoke, and suspension-create handlers now capture both the initiating auth-context version and actor user ID before sending a mutation. After each awaited request, they suppress feedback, form resets, workspace refreshes, and error-state updates if the active account context has changed. The submit button is re-enabled only for the same still-active account. This prevents an older administrator request from writing stale status into a newly signed-in account's interface; it does not cancel a request already accepted by the server.

### Confirmed missing operational modules

A fresh source scan of `index.html`, `app.js`, and the FastAPI route inventory confirms that the admin panel still has no visitor analytics, AI usage/cost dashboard, provider-spend report, revenue or subscription dashboard, tariff editor, wallet/reservation/ledger interface, or media/storage moderation console. The media library itself still states that real file uploads, previews and shared storage are under development. No such functionality should be represented as live.

The API currently records AI usage telemetry from the chat and prompt handlers, but exposes no admin reporting route for those records. Telemetry is therefore a server-side data foundation, not an operational analytics dashboard. No visitor counter or reliable all-time unique visitor source was found in the reviewed frontend/API routes.

### Financial safety gate

The unified wallet migration remains source code only. It defines service-role RPCs and append-only ledger foundations, but this review did not verify that migration in the live database. Two source-level concerns remain release blockers before charging users:
- the reservation release function permits release from both `reserved` and `reconciliation_required`; an ambiguous provider outcome must be reconciled before credits are returned;
- the RPCs accept a user UUID argument, so the server caller must derive that UUID from the verified access token and never trust a client-supplied identity.

No payment provider, billing activation, live wallet mutation, or financial charge was attempted.

### Remaining moderation reliability gap

The three frontend handlers now avoid stale account-context UI updates, but the backend report/suspension mutation and audit insert are still separate REST operations. A database transaction/RPC plus idempotency and failure-path integration tests remains necessary before treating the audit trail as guaranteed. Existing report/suspension list endpoints also remain capped at 100 and lack pagination.

### Scope and non-actions

This remains a source-only review of the feature branch. No production service, live Supabase table, storage bucket, visitor analytics account, billing provider, or secret configuration was accessed. No SQL was executed, no payment or wallet action was triggered, and PR #4 remains open and unmerged.


## Admin AI usage reporting API foundation (2026-11-24)

Added owner-only `GET /api/admin/ai-usage` backed by server-side service-role access. It supports bounded pagination (1–100 rows), optional user/provider/endpoint filters, and selects only operational metadata from `ai_usage`—never prompts, generated text, credentials, or message content. The response includes token totals, known USD cost, and count of unknown-cost events **for the current page only**, explicitly marked `summary_scope=current_page`. It fetches one extra row to determine `has_more`.

The endpoint depends on `require_admin`; the service does not accept a user identity from an untrusted request body. The optional user filter is a validated UUID query parameter. The service returns 503 if server-side storage credentials are absent and sanitizes upstream errors.

This is an API foundation, not yet an admin dashboard. Page summaries must not be presented as all-time totals. A trustworthy all-time/date-range report needs database-side aggregation over a reconciled live schema, including explicit treatment of null costs and telemetry gaps. The current best-effort telemetry writer can fail without failing generation, so these records are not a complete financial ledger and must not be used alone for customer billing or provider invoice reconciliation.

Two service tests were added for bounded pagination/filtering, current-page-only summaries, null-cost accounting, and missing storage configuration. CI has not yet returned a run for the latest feature-branch head at the time of this note. No live Supabase schema was queried or changed, no SQL was run, and no payment action occurred.


## User and visitor analytics readiness review (2026-11-24)

### Verified source-level data

- `public.profiles` has a `created_at` timestamp and is populated by the `auth.users` insert trigger. This can support registration counts only after confirming the live migration and profile completeness.
- `public.studio_projects` has owner ID and created/updated timestamps. It can support project activity counts, but it is not a reliable measure of human visits or unique active users.
- `public.ai_usage` contains successful chat/prompt usage events, but the writer is best-effort. Missing telemetry is possible, and the data must not be treated as a complete activity or billing ledger.
- The inspected API/frontend source contains no first-party visit/session event collector, no documented consent/retention policy for visitor analytics, and no deduplicated unique-visitor source.

### What must not be shown as a fact yet

Do not invent a live visitor count, unique visitor total, online-user count, retention curve, or all-time activity total. Profile/project timestamps are not substitutes for visits. A browser page load is not automatically a person, and IP/device fingerprinting is not an acceptable shortcut.

### Safe implementation sequence

1. Reconcile the live migration ledger, profile/project table definitions, RLS, grants, and retention before using them for admin aggregates.
2. Define a minimal first-party event contract (for example, session-start and studio-open) with short-lived pseudonymous session IDs, coarse event names, server timestamps, strict payload allowlists, rate limits, and documented retention. Do not collect IP addresses, full user agents, page contents, prompts, or generated media for analytics.
3. Decide and document consent/notice requirements and whether anonymous visitors are counted separately from authenticated accounts.
4. Add a server-side ingestion path and database-side daily aggregation only after the schema and privacy design are approved. Deduplicate by session/event window; distinguish raw events, sessions, authenticated active accounts, and registered accounts.
5. Expose an owner-only, bounded date-range report with explicit metric definitions and data-quality warnings. Mark periods with missing telemetry rather than filling gaps with estimates.
6. Add integration tests for spoofed user IDs, duplicate event delivery, rate limits, invalid event names, retention deletion, and account/session separation.

### Current status

This stage is a source audit and implementation plan, not a deployed visitor analytics feature. No new visit-tracking endpoint or migration was added because the live database state and privacy/retention requirements have not been reconciled. Existing registrations and project counts may be candidates for later admin aggregates, but they are not reported as visitor metrics. No SQL was executed and no production data was queried or changed.



## Registration and active-account analytics source review (2026-11-24)

### Registration sources

- The initial schema defines `public.profiles(id, created_at, updated_at)` and an `auth.users` AFTER INSERT trigger that creates the matching profile row. This is a plausible registration-count source **only if** migration 0001 and its trigger are present in production and profile creation has remained complete. The source audit cannot prove either live condition.
- The separate `public.user_profiles` table from migration 0009 is a community-facing profile. The current service lazily creates it when a signed-in user first opens their community profile; it is not a dependable registration table and must not be used to count registrations.
- The JWT auth dependency verifies account identity but does not persist sign-in events or a last-seen timestamp.

### Activity sources and limits

- The initial schema contains `public.studio_projects`; the cloud-project migration separately defines `public.projects`. Both include owner and timestamps, but their presence and completeness in the live database are unverified. Project create/update activity can be reported as project activity only after determining which table the active application writes to and reconciling its migration state.
- `public.ai_usage` can evidence successful AI chat/prompt usage, but writes are best-effort. It misses other studio activity and may contain gaps, so it is not a complete active-account metric.
- No reliable server-side last-seen event, authenticated activity event stream, or online-presence source was found. A project update or AI call should not be silently relabeled as a general active user.

### Safe reporting contract

A future admin report may expose separately named metrics only after live schema verification:
1. **Registered accounts:** count of distinct `profiles.id` by `profiles.created_at`, with a visible completeness caveat until trigger/profile reconciliation is proven.
2. **Accounts with project activity:** distinct project owners with a qualifying project create/update in the selected window, after identifying the authoritative project table. This is not a count of all active accounts.
3. **Accounts with AI activity:** distinct `ai_usage.user_id` values in the window, clearly labeled as observed successful AI usage and subject to telemetry gaps.
4. **Active accounts:** defer this broader label until a defined, reliable server-side activity event is implemented.

All reports should be owner-only, date-bounded, aggregated server-side, and return no emails, usernames, project titles, prompts, or individual account activity rows. Never return fabricated totals for periods without verified coverage.

### Current status and boundary

This is a source-level readiness review only. No API route, frontend dashboard, database migration, SQL execution, live Supabase query, or production configuration change was made. The production migration ledger, RLS, grants, profile completeness, and actual project-table write path remain unverified. The existing visitor analytics design remains a separate prerequisite for counting visits or sessions.


## Aggregate admin analytics API foundation (2026-11-24)

Added owner-only `GET /api/admin/analytics?start_at=...&end_at=...` and source migration `0014_admin_analytics_summary.sql`.

The database function returns only three aggregate counts for a maximum 31-day UTC window:
- registrations from `public.profiles.created_at`;
- distinct owners of movie rows updated in `public.projects`;
- distinct users with recorded rows in `public.ai_usage`.

The browser/API caller cannot supply a user identity. The endpoint is guarded by `require_admin`; the server calls a SECURITY DEFINER RPC using server-only Supabase credentials. The RPC validates the range, uses a fixed empty search path and is executable only by `service_role`. No account IDs, email addresses, project titles, prompts, messages, or media paths are returned.

The response deliberately labels the data limitations: profile-trigger completeness is not verified; AI telemetry is best-effort; project updates are not all account activity; visitor/session counts are not included. It must not be called an online-user count or unique visitor counter.

The frontend admin panel is now connected in the working branch: it offers a selectable period (default seven days), a 31-day client-side guard, three separately labeled aggregate cards, and an explicit unavailable state when the RPC is not installed. It loads only after `/api/auth/me` confirms the admin role and only while the owner panel is visible. The API independently enforces `require_admin`; account-context guards prevent a stale response from being rendered after an account switch. This UI is read-only and does not expose individual account records.\n\nMigration 0014 remains source-only and must not be applied until the live migration ledger, the presence/definitions of `profiles`, `projects`, and `ai_usage`, RLS/grants, and service-role RPC permissions are reconciled. If the RPC is absent, the API returns a safe 503 rather than inventing counts. No live Supabase query, SQL execution, or production change occurred. The frontend account-context workflow and backend test workflow passed for the connected dashboard commit; this confirms automated repository checks, not browser-level visual testing or production readiness.
