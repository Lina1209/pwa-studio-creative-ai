# Supabase cloud storage setup

## Current status

Mini Movie Studio keeps a local-first copy in browser `localStorage` and synchronizes signed-in users' projects with `public.projects` through Supabase. Migration `0005_cloud_projects_and_storage.sql` has been applied and the project table, owner policies, and private `studio-media` bucket were verified in the live project. Cross-device behavior, concurrent edits, and deletion synchronization still require end-to-end tests. No media upload UI exists yet.

The live database must be inspected before project CRUD is implemented. The repository's original schema file may not match the tables already created manually in the Supabase dashboard.

## Step 1 — inspect, do not change

Open the Supabase SQL Editor and run:

`supabase/diagnostics/inspect_cloud_storage.sql`

This is a read-only diagnostic. It reports:
- which of the expected table names exist;
- exact columns in the project, character, scene, and media tables;
- whether the two private storage buckets already exist;
- whether the `public.is_admin()` helper exists.

Keep the results available. They determine the safe mapping for cloud synchronization.

## Step 2 — create private media buckets

After the diagnostic, compare the result with the live setup before changing anything. The `studio-media` bucket is already created by migration 0005 and was verified. Only apply migration 0002 if the required `studio-exports` bucket is missing and you have reviewed its policies. Migration 0002 creates or updates two **private** buckets:
- `studio-media` for source images, audio, and video (250 MiB per object limit);
- `studio-exports` for rendered exports (1 GiB per object limit).

Object paths must begin with the authenticated user's UUID, for example:
`<user-uuid>/projects/<project-uuid>/source/photo.webp`

RLS policies restrict listing, reading, uploading, updating, and deleting to the owner of that UUID path. Do not make either bucket public. Migration 0002 is named `storage_and_moderation` for historical reasons; it does not create moderation tables or workflows.

The configured object-size limits are application choices and do not override Supabase plan-level limits, storage quotas, or bandwidth limits.

## Security and implementation notes

- The browser may use only the Supabase publishable key. Never put a service-role/secret key in GitHub, HTML, JavaScript, or chat.
- Private files must be accessed through authenticated Supabase Storage requests or short-lived signed URLs.
- Postgres should hold project metadata and storage paths, not video binaries.
- Do not connect the Mini Movie Studio to guessed column names. First inspect the live schema and then implement against the actual table definitions and RLS policies.
- Storage setup does not itself enable cloud project sync. That is a separate frontend implementation and must be tested with two accounts to confirm isolation.
- Moderation tables and admin review workflows are intentionally separate from this first storage step; they require a verified admin-role policy and will be reviewed before activation.
