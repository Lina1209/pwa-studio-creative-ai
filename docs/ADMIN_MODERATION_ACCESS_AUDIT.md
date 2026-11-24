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
