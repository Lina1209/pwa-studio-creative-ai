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
