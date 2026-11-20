# Supabase cloud storage setup

## Current status

The application currently stores Mini Movie Studio drafts in the browser's localStorage. The Supabase project and authentication are configured, but cloud project synchronization and private media storage are not yet connected.

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

After the diagnostic, run the contents of:

`supabase/migrations/0002_storage_and_moderation.sql`

This migration creates or updates two **private** buckets:
- `studio-media` for source images, audio, and video (250 MiB per object limit);
- `studio-exports` for rendered exports (1 GiB per object limit).

Object paths must begin with the authenticated user's UUID, for example:
`<user-uuid>/projects/<project-uuid>/source/photo.webp`

RLS policies restrict listing, reading, uploading, updating, and deleting to the owner of that UUID path. Do not make either bucket public.

The configured object-size limits are application choices and do not override Supabase plan-level limits, storage quotas, or bandwidth limits.

## Security and implementation notes

- The browser may use only the Supabase publishable key. Never put a service-role/secret key in GitHub, HTML, JavaScript, or chat.
- Private files must be accessed through authenticated Supabase Storage requests or short-lived signed URLs.
- Postgres should hold project metadata and storage paths, not video binaries.
- Do not connect the Mini Movie Studio to guessed column names. First inspect the live schema and then implement against the actual table definitions and RLS policies.
- Storage setup does not itself enable cloud project sync. That is a separate frontend implementation and must be tested with two accounts to confirm isolation.
- Moderation tables and admin review workflows are intentionally separate from this first storage step; they require a verified admin-role policy and will be reviewed before activation.
