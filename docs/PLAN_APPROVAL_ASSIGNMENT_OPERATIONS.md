# Plan approval and pending assignment operations

Migrations: `0061_plan_approval_assignment_rpcs.sql` and `0062_plan_approval_audit_atomicity.sql`.

## Approval RPC

`approve_plan_catalog_draft` copies one immutable draft into `approved_plan_versions`. It serializes approval attempts for the draft, rejects missing drafts, preserves the exact draft snapshot, and is idempotent for an identical actor/reason retry. Reusing the same draft with different approval details is rejected.

The approved snapshot and central `admin_audit_events` record are written in the same database transaction. A unique source-draft constraint prevents a draft from being approved twice.

## Assignment RPC

`create_pending_user_plan_assignment` creates an append-only assignment with status `pending`. It verifies that the approved plan version exists, serializes retries by user/idempotency key, rejects key reuse with different parameters, and writes the initial assignment event in the same transaction.

Pending assignments are intentionally inert. They are not returned as active entitlements, do not grant credits, and do not enable checkout or generation.

## Trust boundary

Both RPCs are executable only by `service_role`; public, anon and authenticated roles are explicitly revoked. A future backend route MUST authenticate the caller and check the specific admin permission before invoking them. Never expose service-role credentials or call these RPCs from browser code. Actor UUIDs supplied to the RPC must come from the verified backend identity, not request JSON.

## Not yet implemented

- No admin HTTP endpoints are exposed by these migrations.
- No activation, cancellation, expiry or renewal transition is enabled.
- No active-plan resolver or quota reservation is connected.
- No credits, payments or checkout are activated.
- No production migration has been applied.

The next step is a backend-only admin service with permission checks and read-back verification, followed by tests for authorization, idempotent retries and audit failure rollback.
