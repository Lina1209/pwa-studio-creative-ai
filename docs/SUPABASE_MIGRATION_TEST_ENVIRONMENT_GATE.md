# Supabase migration, Storage, and test-environment reconciliation

Date: 2026-11-24  
Status: read-only repository-source review; no live database access

## Repository migration inventory

The GitHub Contents API returned the complete visible contents of `supabase/migrations/` on both `main` and `fix/supabase-key-compat-2026-11-23`. Both branches expose the same 15 migration filenames:

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

This is a repository-file inventory, not proof of the production project's migration ledger or actual deployed schema.

## Confirmed migration-order blocker

There are two distinct files with the same numeric version prefix, `0005`:

- `0005_cloud_projects_and_storage.sql`
- `0005_moderation_admin.sql`

This is a confirmed filename-level collision on both branches. A migration runner that expects unique version identifiers may reject the directory or apply one file before the other in an implementation-dependent way. Do not rename either file or run the migration sequence until the intended history and any already-applied versions in the target project have been reconciled.

## Confirmed Storage migration overlap

The source of `0002_storage_and_moderation.sql` and `0005_cloud_projects_and_storage.sql` has overlapping, non-identical effects:

- `0002` creates or updates two private buckets: `studio-media` (250 MiB) and `studio-exports` (1 GiB), and creates four authenticated-user Storage policies scoped to both bucket IDs.
- `0005_cloud_projects_and_storage.sql` later upserts `studio-media` with a 100 MiB limit and a different MIME allowlist. It then drops and recreates the same four policy names, but the replacement policies are scoped only to `studio-media`.
- Consequently, if both files are applied in that order, the later migration narrows the `studio-media` bucket configuration and removes the authenticated-user policy coverage for `studio-exports`. The export bucket remains private; the likely effect is loss of the intended authenticated access path, not public exposure.

This is a source-level sequence consequence, not a live-project finding. Do not automatically restore export policies or alter bucket limits until the intended product behavior and live Storage configuration are confirmed. The filename `0002_storage_and_moderation.sql` is also broader in name than its current contents: the inspected file contains Storage setup, not the moderation tables found in `0005_moderation_admin.sql`.

## Current application integration: what exists and what does not

### Mini Cinema cloud projects

The browser application uses the Supabase client directly for the `public.projects` table:
- reads select the project fields and filter by the authenticated `owner_id` and `project_type = movie`;
- deletes filter by project IDs, authenticated owner ID, and movie project type;
- upserts send rows generated with the captured owner ID and use `id` as the conflict key;
- the context helper captures the authenticated user ID and auth-context version, and operations check that context before/after awaited requests;
- local deletion tombstones are re-read around asynchronous operations to avoid reintroducing deleted projects.

The table migration enables RLS and defines an owner policy using `auth.uid() = owner_id`. The explicit client-side owner filters are useful defense-in-depth, but RLS remains the database security boundary. The app code does not prove that the target project's live RLS policy matches this source.

The legacy `studio_projects` table from `0001` is distinct from the current `projects` table introduced in `0005_cloud_projects_and_storage.sql`. Do not assume the two schemas are interchangeable.

### Media and export Storage

A read of the root browser `app.js` found no calls to `storage.from(...)`, `upload(...)`, `createSignedUrl(...)`, `getPublicUrl(...)`, or Storage download APIs. The current Mini Cinema cloud modules likewise operate on the `projects` table and local project data, not Storage objects.

The backend has an `asset_access.py` owner-scope helper, but its module documentation says it is deliberately not wired to routes until live schema/RLS is reconciled. The inspected `main.py` exposes no media upload/download route. No `storage_service.py` or `media_service.py` file exists at the inspected paths.

Therefore the repository source currently establishes private bucket configuration and owner-path policies, but does not establish a completed application upload/download/export pipeline. The bucket policy discrepancy is still important before that feature is connected.

## Recommended target Storage contract (proposal, not applied)

Before implementing media routes or repairing policies, choose and document:
1. Which bucket stores original user media and which stores rendered exports.
2. Whether each bucket is user-readable through authenticated Storage APIs, backend-only, or both.
3. Maximum upload sizes and MIME types for each bucket, matching actual product needs.
4. A canonical object key layout, such as `<verified-user-uuid>/<project-uuid>/<asset-uuid>.<extension>`.
5. Whether browser clients upload directly using authenticated Supabase sessions or obtain short-lived signed upload/download URLs from the backend.
6. How the backend verifies ownership, file size, MIME type, and project association; client-supplied owner IDs must never define authorization.
7. How delete, replace, and export retention behave, including cleanup of orphaned objects.

Prefer private buckets, verified identity-derived object paths, short-lived signed URLs when appropriate, and explicit ownership checks. Never use public URLs for private user media.

## CI environment finding

The currently inspected `.github/workflows/backend-tests.yml` installs Python requirements and runs `pytest -q`. It does not provision PostgreSQL, install a Supabase local stack, apply migrations to a disposable database, or run SQL integration tests.

Therefore:
- existing backend CI cannot prove transaction rollback;
- mocked Python tests cannot prove row-lock concurrency;
- static SQL checks cannot prove runtime grants or function execution;
- no database integration result should be claimed until an isolated PostgreSQL service and a reconciled migration bootstrap are added.

## Exact gates before implementation

1. Confirm whether the repository migration history matches the actual intended deployment history; the two branches currently expose the same filenames.
2. Resolve the duplicate `0005` version prefix without rewriting history blindly. Determine whether either migration has already been applied in the target project and preserve the actual deployment history.
3. Decide the intended Storage contract for `studio-media` and `studio-exports`, bucket size limits, MIME types, and direct-vs-backend upload flow.
4. Obtain a read-only export of the target project's migration ledger, relevant table definitions, indexes, triggers, constraints, RLS policies, grants, Storage buckets/policies, and function definitions. Do not include user content or secrets.
5. Compare that live metadata with the complete intended migration sequence; document drift rather than automatically repairing it.
6. Build a disposable PostgreSQL/Supabase-compatible test target. It must never use production credentials or a production host.
7. Add a CI job that provisions the disposable database, applies the reconciled baseline and candidate migration, and runs real concurrent transaction tests.
8. Only after tests pass, review candidate migrations and obtain separate explicit approval before applying anything to a shared Supabase environment.

## Safety boundary

No connection was made to Supabase. No SQL was run. No schema, migration ledger, policy, grant, function, storage object, report, suspension, or audit row was read or changed in a live database. No migration was created or applied as part of this review.
