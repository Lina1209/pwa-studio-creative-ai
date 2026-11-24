# Supabase migration and test-environment reconciliation gate

Date: 2026-11-24  
Status: read-only source review; no live database access

## What was inspected

The feature branch source contains the following migration files that were readable during this review:

- `0001_initial_schema.sql`
- `0003_ai_usage_metering.sql`
- `0005_moderation_admin.sql`
- `0006_notifications.sql`
- `0009_user_profiles.sql`
- `0010_direct_message_notifications.sql`
- `0011_atomic_message_rate_limit.sql`
- `0012_atomic_ai_rate_limit.sql`
- `0013_unified_credit_wallet.sql`
- `0014_admin_analytics_summary.sql`

This is not a complete migration inventory. Some guessed filenames (including 0002, 0004, 0007, and 0008) were not found at those exact paths; that does not prove the migrations are absent because their actual names have not been enumerated from a repository tree.

The earlier repository audit also flagged duplicate `0005` migration version names. The exact competing paths and contents must be enumerated before any migration runner is used. Do not infer ordering from filenames alone.

## Moderation schema facts from source

`0005_moderation_admin.sql` defines:
- `user_reports` with report status values `pending`, `reviewing`, `resolved`, `rejected`;
- `user_suspensions` with scopes `platform`, `assistant`, `community`, and a partial active-user index on rows where `revoked_at IS NULL`;
- `admin_audit_log` with identity bigint key and actor/action/target/entity/metadata/timestamp fields.

The migration grants authenticated users insert/select on their own reports via RLS, while suspension and audit tables are server-only. The audit table grants service_role SELECT and INSERT, and explicitly revokes UPDATE, DELETE, and TRUNCATE from service_role.

`0006_notifications.sql` defines server-managed notifications. `0010_direct_message_notifications.sql` later replaces the notification type check to include `direct_message`. This is an example of why the full ordered migration history matters.

`0011_atomic_message_rate_limit.sql` creates a SECURITY DEFINER RPC with `search_path = public, pg_temp`, revokes execution from public/anon/authenticated, and grants it to service_role. A new moderation RPC should follow the stricter fixed/empty search_path and fully-qualified-object pattern described in the transactional design, not copy a weaker pattern without review.

## CI environment finding

The currently inspected `.github/workflows/backend-tests.yml` installs Python requirements and runs `pytest -q`. It does not provision PostgreSQL, install a Supabase local stack, apply migrations to a disposable database, or run SQL integration tests.

Therefore:
- existing backend CI cannot prove transaction rollback;
- mocked Python tests cannot prove row-lock concurrency;
- static SQL checks cannot prove runtime grants or function execution;
- no database integration result should be claimed until an isolated PostgreSQL service and migration bootstrap are added.

## Exact gates before implementation

1. Enumerate every migration filename in the branch and on the intended deployment branch; resolve duplicate version prefixes and confirm a single deterministic order.
2. Obtain a read-only export of the target project's migration ledger, relevant table definitions, indexes, triggers, constraints, RLS policies, grants, and function definitions. Do not include user content or secrets.
3. Compare that live metadata with the complete migration sequence; document drift rather than automatically repairing it.
4. Build a disposable PostgreSQL/Supabase-compatible test target. It must never use production credentials or a production host.
5. Add a CI job that provisions the disposable database, applies the reconciled baseline and candidate migration, and runs real concurrent transaction tests.
6. Only after tests pass, review the candidate migration and obtain separate explicit approval before applying anything to a shared Supabase environment.

## Safety boundary

No connection was made to Supabase. No SQL was run. No schema, migration ledger, policy, grant, function, storage object, report, suspension, or audit row was read or changed in a live database. No migration was created or applied as part of this reconciliation note.
