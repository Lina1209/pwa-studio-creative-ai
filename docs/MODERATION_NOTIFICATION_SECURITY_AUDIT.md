# Moderation and Notification Security Audit

Date: 2026-11-24  
Audited revision: `5745817c365600565ba0af220d3f2d0a98edf74f`  
Scope: source-code and migration review only. No live Supabase schema, RLS, grants, migration ledger, or data was queried or changed.

## Verified protections

- Report submission requires an authenticated `StudioUser`; the reporter ID is taken from the verified token, not from request JSON.
- Admin report listing/review and suspension create/list/revoke routes use `require_admin`.
- Report and suspension UUID inputs are validated; suspension expiry must be timezone-aware and in the future.
- Notification list/read operations include the authenticated user's ID in the REST filter.
- Message reads verify thread membership; edits filter by sender; per-user message rate limiting uses a database RPC.
- Supabase REST errors are converted to generic API errors rather than returning upstream response details.
- Migration `0005_moderation_admin.sql` enables RLS and denies direct client writes to moderation/suspension/audit tables.
- Migration `0006_notifications.sql` makes notifications server-managed; migration `0010_direct_message_notifications.sql` adds the `direct_message` notification type emitted by the message endpoint.

## Findings requiring follow-up

### M1 — Moderation mutation and audit write are not atomic

In `moderation_service.py`, report review, suspension creation, and suspension revocation first mutate the target row and then call `_write_audit`. If the audit insert fails, the API can return an error even though the moderation action has already taken effect. A retry may create duplicate suspensions or otherwise confuse the operator.

**Recommended correction:** move each state change and its audit insert into one PostgreSQL transaction exposed through a narrowly scoped RPC. Return success only after both commit. Add idempotency keys/unique constraints for create operations. Do not try to emulate a transaction with sequential REST calls.

### M2 — Suspension checks are a read-before-action check

`ensure_user_not_suspended` queries active restrictions before selected feature handlers proceed. A restriction can theoretically be created after that check but before a downstream action completes.

**Recommended correction:** for sensitive future operations (publishing, payments, asset access, destructive actions), enforce suspension state inside the same database transaction/RPC that performs the operation. Keep the API check as an early user-friendly rejection, not the only enforcement layer.

### M3 — Moderation list and review need operational pagination/concurrency controls

The admin report and suspension lists use a fixed limit of 100 without a cursor. Report review updates by ID without an expected-current-status condition. This is not a demonstrated authorization bypass, but can make older reports hard to reach and allow two concurrent reviews to overwrite each other.

**Recommended correction:** add bounded cursor pagination and optimistic concurrency (expected status/version) before the moderation queue is used at scale.

## Rollout gates

1. Run the existing SELECT-only Supabase diagnostics and reconcile the live migration ledger before applying or changing any SQL.
2. Verify actual RLS policies, grants, table constraints, and the applied state of migrations `0005`, `0006`, and `0010`.
3. Implement atomic moderation RPCs with tests against PostgreSQL, including injected audit failure and concurrent duplicate requests.
4. Add route/service tests for creator denial, report ownership, notification isolation, suspension enforcement, and idempotent moderation actions.
5. Do not enable public publishing or broaden moderation powers until these gates pass.

## Explicit non-actions

- No SQL was executed or applied.
- No production database, account, suspension, report, notification, or user data was changed.
- No production deploy or merge was performed.

## Audit refresh — moderation identifier validation

The moderation service now validates report IDs before review and suspension IDs before revocation, rejecting malformed values with HTTP 422 before making any Supabase REST request. Regression tests cover both paths. This narrows malformed-filter input at the API boundary; it does not replace database authorization or transactional enforcement.

The M1 atomicity finding remains open: moderation mutations and audit-log inserts are still separate REST operations. It would be unsafe to claim atomicity or attempt to simulate it in application code. The correction requires a narrowly scoped PostgreSQL transaction/RPC after live schema and migration-ledger reconciliation.

No SQL, live database action, or deployment was performed.

## Audit refresh — affected-account attribution

Moderation audit events now populate the migration's dedicated `target_user_id` column when a report review identifies a reported account, and when a suspension is created or revoked. The report review query now returns the reported account ID for this purpose. Regression tests assert the actor and affected account are distinct and correctly recorded.

This improves audit-log searchability and attribution; it does not make the mutation and audit insert atomic. The M1 transaction finding remains open.

### Audit-log access boundary

The inspected migration makes `admin_audit_log` server-managed and revokes UPDATE, DELETE, and TRUNCATE from `service_role`, granting SELECT and INSERT. The inspected API currently writes audit events but does not expose a dedicated admin audit-history read endpoint. A future read endpoint should be admin-only, paginated, and return a safe allowlist of fields; it must not grant client-side table access.

## Follow-up review — mutation failure semantics and retry safety (2026-11-24)

A fresh inspection of the current branch confirms the M1 issue has a concrete operator-facing failure mode:

1. The service sends a PATCH/POST to the primary moderation table.
2. The primary mutation can commit and return its row.
3. A second REST request attempts to insert the audit event.
4. If that second request fails, the service raises an HTTP error even though the moderation state may already have changed.

This means an administrator can see an error despite a successful state change. Retrying suspension creation can create a second active suspension; retrying a report review can overwrite the first review metadata/time. The audit event can be missing. This is not fixed by catching the error or adding another sequential REST call.

### Current protections and remaining gaps

- Report review validates the report UUID and updates only the exact report ID.
- Suspension revocation validates the UUID and filters to an exact record whose `revoked_at` is NULL; a repeated revoke normally returns 404.
- Suspension creation validates the target UUID and future timezone-aware expiry, but does not carry an idempotency key or enforce a documented duplicate-active-suspension policy at the service boundary.
- Report review does not include an expected-current-status predicate, so concurrent moderators can overwrite each other's review.
- Existing unit tests verify actor/target attribution and normal mutation calls, but do not inject an audit-write failure after a successful primary mutation or prove transaction rollback.

### Required correction before operational reliance

Do not patch this with a client retry loop. First reconcile the live migration ledger and actual moderation table constraints. Then implement narrow database RPCs that, in one transaction:

- lock and validate the target report/suspension row;
- enforce allowed state transitions and an expected-current-status/version;
- accept a stable idempotency key for create/revoke operations;
- write the state change and append-only audit event together;
- return the committed result and audit event only after transaction success.

Add PostgreSQL integration tests for audit insert failure rollback, two moderators reviewing the same report, repeated suspension-create requests with the same idempotency key, duplicate revoke, and both concurrent ordering outcomes. Until then, treat a moderation mutation API error as an ambiguous result: inspect the current record and audit history before retrying.

### Scope boundary

This is source-level evidence only. No RPC or migration was added, no SQL was executed, and no live reports, suspensions, audit events, policies, or grants were accessed. Production behavior remains unverified.
