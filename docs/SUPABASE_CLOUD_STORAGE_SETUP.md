# Supabase cloud storage setup

## Current status

The Mini Cinema frontend stores a per-account local copy of movie drafts and also contains an authenticated cloud project-sync path to `public.projects`. This cloud path stores project records/settings, not uploaded media binaries. Guest drafts remain device-local. Live RLS correctness and cross-account behavior still require verification. A shared private media library, asset metadata API, upload/download service, and cross-studio asset linking are not yet implemented.

The live database must be inspected before project CRUD or media storage is enabled. Repository migration files are source history, not proof of the current live schema.

## Critical migration safety notice

**Do not run migration 0002 or either file named 0005 from the repository as a setup step yet.**

The source audit found overlapping Storage policy names and different bucket settings between `0002_storage_and_moderation.sql` and `0005_cloud_projects_and_storage.sql`. There are also two distinct migration files with version `0005`. Replaying these files without the live migration ledger and policy state could replace policies or change bucket configuration unexpectedly.

The next safe action is read-only inspection and reconciliation. No SQL in this guide should be applied until a reviewed migration plan identifies the exact live state and the correct forward-only change.

## Step 1 — inspect, do not change

Open the Supabase SQL Editor and run:

`supabase/diagnostics/inspect_cloud_storage.sql`

This is a read-only diagnostic. It reports:
- which of the expected table names exist;
- exact columns in the project, character, scene, and media tables;
- whether the two private storage buckets already exist;
- whether the `public.is_admin()` helper exists.

This diagnostic is only an initial inventory. For the broader read-only inventory, also run `supabase/diagnostics/inspect_project_asset_security.sql`. It checks migration-ledger locations/columns, table definitions, constraints, indexes, RLS flags, policies, table grants, Storage bucket settings, and approximate row counts. Review all output before designing any migration. It does not prove cross-account isolation; that requires controlled tests with two accounts.

Keep the results available. They determine the safe mapping for cloud synchronization.

## Intended storage properties (not a setup instruction)

The repository contains source definitions for two private buckets:
- `studio-media` for source images, audio, and video;
- `studio-exports` for rendered exports.

The source files contain different size limits and different policy scopes. Do not assume either configuration matches the live project.

Object paths are intended to begin with the authenticated user's UUID, for example:

`<user-uuid>/projects/<project-uuid>/source/photo.webp`

Private access must be owner-scoped. Do not make either bucket public.

Configured object-size limits are application choices and do not override Supabase plan-level limits, storage quotas, or bandwidth limits.

## Security and implementation notes

- The browser may use only the Supabase publishable key. Never put a service-role/secret key in GitHub, HTML, JavaScript, or chat.
- Private files must be accessed through authenticated Supabase Storage requests or short-lived signed URLs.
- Postgres should hold project/asset metadata and storage paths, not video binaries.
- Do not connect the Mini Movie Studio to guessed column names. First inspect the live schema and then implement against the actual table definitions and RLS policies.
- Existing Mini Cinema project sync and future media-object storage are separate capabilities. Do not replace or disable the existing project-sync path while implementing the asset library. Verify project sync with two accounts and multiple devices before expanding it.
- Moderation tables and admin review workflows are separate from storage and require their own verified admin-role and policy review.
- See `docs/CREATIVE_ASSET_STORAGE_ARCHITECTURE.md` for the target cross-studio asset model and rollout gates.

## Current rollout boundary

No storage migration is approved by this guide. No SQL should be run until the live-state audit is complete, the duplicate migration-version issue is resolved, and the proposed change has been tested in a disposable environment.


## Additional read-only inventory

Run `supabase/diagnostics/inspect_project_asset_security.sql` after the initial check. It is SELECT-only and does not alter schema, rows, grants, RLS, policies, or buckets. Its output is intended for an engineering review, not for automatic migration generation.

The inventory intentionally does not read project contents or media. Approximate row counts come from PostgreSQL statistics and may be stale. If the migration ledger is present under a nonstandard schema/table name, use the reported location and columns to inspect its actual records separately; do not assume a specific migration framework or version format.
