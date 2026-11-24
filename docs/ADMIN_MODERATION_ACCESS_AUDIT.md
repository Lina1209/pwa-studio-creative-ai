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
- No frontend history screen has been added yet.
- No live Supabase grants, RLS, migration ledger or table contents were inspected. The endpoint is source-level only until the production schema is reconciled and the migration's presence is confirmed.
- The state-change/audit-write transaction gap in moderation mutations remains open; this read endpoint does not fix it.
