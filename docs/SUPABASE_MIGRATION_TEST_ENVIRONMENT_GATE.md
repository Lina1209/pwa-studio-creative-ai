# Supabase migration and test-environment reconciliation gate

Date: 2026-11-24  
Status: read-only repository-source review; no live database access

## Repository migration inventory

The GitHub Contents API returned the complete visible contents of `supabase/migrations/` on branch `fix/supabase-key-compat-2026-11-23` at the time of this review. It contains 15 SQL files:

1. `0001_initial_schema.sql`
2. `0002_storage_and_moderation.sql`
3. `0003_ai_usage_metering.sql`
4. `0004_assistant_chat_history.sql`
5. `0005_cloud_projects_and_storage.sql`
6. `0005_moderation_admin.sql`
7. `0006_notifications.sql`
8. `0007_direct_messages.sql`
9. `0008_user_blocks.sql`
10. `0009_user_profiles.sql`
11. `0010_direct_message_notifications.sql`
12. `0011_atomic_message_rate_limit.sql`
13. `0012_atomic_ai_rate_limit.sql`
14. `0013_unified_credit_wallet.sql`
15. `0014_admin_analytics_summary.sql`

### Confirmed migration-order blocker

There are two distinct files with the same numeric version prefix, `0005`:

- `0005_cloud_projects_and_storage.sql`
- `0005_moderation_admin.sql`

This is a confirmed filename-level collision, not merely a suspicion. A migration runner that expects unique version identifiers may reject the directory or apply one file before the other in an implementation-dependent way. Do not rename either file or run the migration sequence until the intended history and any already-applied versions in the target project have been reconciled. The repository directory inventory is complete for this branch, but it does not prove the contents of the production project's migration ledger or whether production was provisioned by another route.

## Moderation schema facts from source

`0005_moderation_admin.sql` defines:
- `user_reports` with report status values `pending`, `reviewing`, `resolved`, `rejected`;
- `user_suspensions` with scopes `platform`, `assistant`, `community`, and a partial active-user index on rows where `revoked_at IS NULL`;
- `admin_audit_log` with identity bigint key and actor/action/target/entity/metadata/timestamp fields.

The migration grants authenticated users insert/select on their own reports via RLS, while suspension and audit tables are server-only. The audit table grants service_role SELECT and INSERT, and explicitly revokes UPDATE, DELETE, and TRUNCATE from service_role.

`0006_notifications.sql` defines server-managed notifications. `0010_direct_message_notifications.sql` later replaces the notification type check to include `direct_message`. This is an example of why the complete ordered migration history matters.

`0011_atomic_message_rate_limit.sql` creates a SECURITY DEFINER RPC with `search_path = public, pg_temp`, revokes execution from public/anon/authenticated, and grants it to service_role. A new moderation RPC should follow the stricter fixed/empty search_path and fully-qualified-object pattern described in the transactional design, not copy a weaker pattern without review.

## CI environment finding

The currently inspected `.github/workflows/backend-tests.yml` installs Python requirements and runs `pytest -q`. It does not provision PostgreSQL, install a Supabase local stack, apply migrations to a disposable database, or run SQL integration tests.

Therefore:
- existing backend CI cannot prove transaction rollback;
- mocked Python tests cannot prove row-lock concurrency;
- static SQL checks cannot prove runtime grants or function execution;
- no database integration result should be claimed until an isolated PostgreSQL service and a reconciled migration bootstrap are added.

## Exact gates before implementation

1. Confirm the migration inventory on the intended deployment branch as well as this feature branch.
2. Resolve the duplicate `0005` version prefix without rewriting history blindly. Determine whether either migration has already been applied in the target project and preserve the actual deployment history.
3. Obtain a read-only export of the target project's migration ledger, relevant table definitions, indexes, triggers, constraints, RLS policies, grants, and function definitions. Do not include user content or secrets.
4. Compare that live metadata with the complete intended migration sequence; document drift rather than automatically repairing it.
5. Build a disposable PostgreSQL/Supabase-compatible test target. It must never use production credentials or a production host.
6. Add a CI job that provisions the disposable database, applies the reconciled baseline and candidate migration, and runs real concurrent transaction tests.
7. Only after tests pass, review the candidate migration and obtain separate explicit approval before applying anything to a shared Supabase environment.

## Safety boundary

No connection was made to Supabase. No SQL was run. No schema, migration ledger, policy, grant, function, storage object, report, suspension, or audit row was read or changed in a live database. No migration was created or applied as part of this reconciliation note.
