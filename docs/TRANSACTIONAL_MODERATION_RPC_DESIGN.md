# Transactional Moderation RPC Design

Date: 2026-11-24  
Status: design only; not implemented or applied  
Target branch: `fix/supabase-key-compat-2026-11-23`

## 1. Why this design exists

The current moderation service performs a REST mutation and then a separate REST insert into `admin_audit_log`. PostgreSQL cannot roll those requests back as one unit. A failed audit insert can therefore leave a changed report or suspension with an API error and no audit event.

The correction must be a PostgreSQL transaction, exposed as a small set of server-only RPCs. Do not imitate transactions with retries or sequential HTTP calls.

## 2. Existing schema facts verified from migration source

The source migration `0005_moderation_admin.sql` defines:

- `user_reports`: UUID primary key; status check permits `pending`, `reviewing`, `resolved`, `rejected`; review fields include `moderator_note`, `reviewed_by`, `reviewed_at`.
- `user_suspensions`: UUID primary key; user, reason, scope, creator, expiry, revocation fields. Scope is `platform`, `assistant`, or `community`.
- `admin_audit_log`: identity bigint key; actor, action, optional target, entity type/id, JSON metadata, timestamp.
- RLS is enabled. Direct client access to suspension and audit tables is revoked; service_role is granted the server-side privileges described in the migration.

These are source-file facts only. The actual live schema, applied migration ledger, policies, grants, triggers, and indexes have not been queried. Reconcile those before writing or applying a migration.

## 3. Trust boundary

1. FastAPI routes continue to require `require_admin`.
2. The actor UUID passed to an RPC must come only from the verified `StudioUser.user_id`; never accept it from request JSON, query parameters, or browser state.
3. RPC execution must be granted only to `service_role`; revoke execute from `PUBLIC`, `anon`, and `authenticated`.
4. The service-role key remains backend-only.
5. A SECURITY DEFINER function must use an empty/fixed `search_path` and fully qualified table/function names.
6. Important limitation: because the backend invokes RPC with the service-role credential, the database function cannot independently prove the actor is the configured owner/admin merely from the supplied UUID. The trusted boundary is the backend's verified JWT plus `require_admin`. Do not describe the RPC as independently admin-authenticating.

## 4. RPC contracts

Names below are proposed, not yet present in the repository or database.

### `admin_review_user_report`

Inputs:
- report UUID;
- verified moderator UUID;
- expected current status;
- requested status and moderator note;
- operation idempotency UUID.

Transaction:
1. Validate non-null inputs and allowed statuses.
2. Lock the exact report row with `FOR UPDATE`.
3. If the idempotency record already exists, return its stored result only when actor, operation, and request fingerprint match; otherwise raise an idempotency conflict.
4. Compare current status to expected status; on mismatch raise a stable conflict (HTTP 409 at API boundary).
5. Apply the review fields and timestamp.
6. Insert exactly one audit row with action `report.reviewed`, target_user_id from the locked report row, and bounded metadata.
7. Persist the idempotency result in the same transaction.
8. Return the updated report and audit identifier.

A repeated request with the same key and identical payload returns the original result. A different key against a stale expected status conflicts instead of silently overwriting another moderator's review.

### `admin_create_user_suspension`

Inputs:
- target user UUID, verified moderator UUID;
- reason, scope, optional timezone-aware expiry;
- operation idempotency UUID.

Transaction:
1. Validate target, actor, reason length, scope, and expiry.
2. Resolve idempotency key before inserting. A reused key with a different request fingerprint conflicts.
3. Insert one suspension row.
4. Insert its `user.suspended` audit row in the same transaction.
5. Persist and return the result under the idempotency key.

Do not invent a global "one active suspension per user" rule yet. The product may need simultaneous scopes or different expiry/reason history. Decide duplicate-active semantics explicitly after examining existing production data and product policy. Stable idempotency prevents duplicate retries of the same operation without silently merging distinct moderator decisions.

### `admin_revoke_user_suspension`

Inputs:
- suspension UUID, verified moderator UUID, idempotency UUID.

Transaction:
1. Resolve a matching idempotency record first.
2. Lock the exact suspension row with `FOR UPDATE`.
3. Require `revoked_at IS NULL`; otherwise return a stable already-revoked conflict/not-found result.
4. Set revocation fields.
5. Insert `user.suspension_revoked` audit row in the same transaction.
6. Persist idempotency result and return.

## 5. Idempotency storage proposal

A dedicated server-only table is preferable to overloading the immutable audit log. Proposed fields:

- `id` UUID primary key (the client operation key);
- `operation` text with a strict allowlist;
- `actor_user_id` UUID;
- `request_hash` text (canonical hash of normalized operation inputs);
- `result` JSONB;
- `created_at` timestamptz.

Enforce a unique primary key and reject key reuse when operation, actor, or request hash differs. Grant no direct access to anon/authenticated; only narrowly required server-side function access. Decide retention/cleanup only after operational and audit-retention requirements are defined. Never store secrets or full auth tokens in this table.

The database transaction must insert the idempotency record, state mutation, and audit event together. A unique-key race must be handled by re-reading the committed idempotency record and comparing its fingerprint, not by blindly repeating the mutation.

## 6. Backend integration

- Generate one UUID idempotency key per user-initiated moderator operation and retain it for retries of that same operation.
- Send only normalized, validated values to the matching RPC.
- Translate explicit stale-state/idempotency conflicts to HTTP 409; missing target to 404; invalid arguments to 422; hide raw database exception details.
- Do not retry automatically after an ambiguous network timeout with a new key. Retry with the same key or inspect state and audit history.
- Keep the existing route-level `require_admin`; tests must prove creator requests are rejected before RPC invocation.
- Do not leave the old REST mutation + separate audit write path reachable after cutover.

## 7. Required tests

### PostgreSQL integration tests (required before rollout)

1. Force the audit insert to fail; assert the report/suspension mutation and idempotency record both roll back.
2. Two moderators review the same report from the same expected status; exactly one transition wins, the other receives a conflict.
3. Same suspension-create key and same payload submitted twice; one suspension and one audit event exist, both calls resolve to the same result.
4. Same key reused with a different actor, operation, or payload; reject without mutation.
5. Two concurrent identical suspension-create requests; no duplicate rows/audit events.
6. Revoke the same suspension twice with the same key; return the original result and keep one audit event.
7. Revoke with a different key after it is already revoked; return a stable conflict/not-found result and do not append a second event.
8. Verify function execute privileges are denied to `PUBLIC`, `anon`, and `authenticated`, and allowed to `service_role`.

### Backend tests

- Admin route passes the verified actor ID and idempotency key to the correct RPC.
- Creator and unauthenticated requests never call the RPC.
- RPC conflict, missing row, invalid input, and ambiguous transport failures map to safe API responses.
- No route falls back to the old multi-request mutation/audit sequence.

Unit tests that merely mock the RPC are useful but do not prove transaction rollback or concurrency. They are not a substitute for the PostgreSQL integration suite.

## 8. Safe implementation and rollout sequence

1. Reconcile live migration ledger and actual definitions/grants/RLS for the three moderation tables. Use the existing SELECT-only diagnostics; do not run DDL.
2. Confirm current data compatibility and any existing duplicate active suspensions. Do not impose a unique-active-suspension constraint without a product decision.
3. Implement a source-only migration and backend RPC adapter on the feature branch.
4. Run static SQL tests, backend unit tests, and PostgreSQL integration tests against an isolated disposable database.
5. Review the generated migration and its privilege statements.
6. Only after explicit separate approval, apply the migration to the intended Supabase environment, verify RPC behavior, and plan production rollout.

## 9. Non-actions

No migration was created or applied by this design note. No SQL was executed. No live Supabase schema, policies, grants, reports, suspensions, audit events, or user data were accessed or changed. No PR merge or production deployment was performed.
