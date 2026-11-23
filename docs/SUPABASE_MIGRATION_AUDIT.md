# Supabase migration audit

This document records a source-repository review only. It is not evidence of which migrations have been applied to the live Supabase project.

## Files currently in the repository

| File | Purpose | Dependencies / notes |
| --- | --- | --- |
| `0001_initial_schema.sql` | Initial studio tables, RLS policies, and new-user profile trigger | Uses Supabase Auth users and Storage is not required here. |
| `0002_storage_and_moderation.sql` | Private `studio-media` and `studio-exports` buckets plus per-user object policies | Requires Supabase Storage schema. |
| `0003_ai_usage_metering.sql` | Private AI usage metering table | References `auth.users`; intentionally has no client policies. |
| `0004_assistant_chat_history.sql` | Assistant conversations and messages | References `auth.users` and its own conversations table. |
| `0005_cloud_projects_and_storage.sql` | Cloud projects and private `studio-media` bucket policies | Creates/updates `public.projects`; overlaps with the earlier storage migration's bucket and object-policy names. |
| `0005_moderation_admin.sql` | Reports, suspensions, and append-only admin audit log | Independent of cloud projects; same numeric migration prefix as the preceding file. |
| `0006_notifications.sql` | Private in-app notifications | Creates `public.user_notifications`. |
| `0007_direct_messages.sql` | Private conversations and direct messages | References `auth.users` and creates conversation/message tables. |
| `0008_user_blocks.sql` | User block list | References `auth.users`. |
| `0009_user_profiles.sql` | Community-facing profiles | References `auth.users`. |
| `0010_direct_message_notifications.sql` | Allows the existing `direct_message` notification type | Requires `0006_notifications.sql` to have been applied first. |

## Findings requiring a live migration-history check

1. Two different files use version prefix `0005`. This is a migration-history collision for tools that identify migrations by their numeric version. Do not run the entire directory through a migration runner until the project's migration ledger and deployment method are known.
2. The repository documentation describes these SQL files as manually reviewed/applied in Supabase SQL Editor in several places. If that is how the live project was maintained, the actual application order must be reconstructed from the live schema and migration history, not inferred from filenames alone.
3. `0002_storage_and_moderation.sql` and `0005_cloud_projects_and_storage.sql` both manage the `studio-media` bucket and similarly named Storage policies. Their bucket size limits and MIME allow-lists differ. The last migration applied can therefore change the effective bucket configuration.
4. `0010_direct_message_notifications.sql` changes only the notification type constraint and must not be applied before the notifications table exists.
5. No live schema, migration ledger, production data, or Storage bucket settings were queried during this audit.
6. There is also a concrete Storage policy overlap: `0002_storage_and_moderation.sql` creates the four user-owned object policies for both `studio-media` and `studio-exports`. Later, `0005_cloud_projects_and_storage.sql` drops those same policy names and recreates them for `studio-media` only. If both files were applied in that order, user-level access policies for `studio-exports` would no longer be present. This may be intentional if exports are server-only, but it conflicts with the earlier migration's explicit user access design and must be decided before changing production. The bucket's size/MIME configuration also depends on which overlapping migration ran last.

## Safe next procedure

- Identify the exact Supabase project referenced by the deployed backend without revealing any credentials.
- Read the Supabase migration ledger (if the project uses CLI-managed migrations) and inspect the relevant table definitions, constraints, policies, and bucket configuration.
- If the project was maintained manually, compare the live schema against each migration's intended objects and record which changes are already present.
- Only then create a reconciled, uniquely versioned migration plan. Do not blindly replay old SQL files or rename historical migration files after deployment.
- Apply changes in a controlled maintenance window, then verify profile, notification, messaging, moderation, and storage operations using authenticated test accounts.

## Current status

This is a source review and a safety checklist only. No SQL has been executed against Supabase, no production data has been changed, and no Render deployment has been initiated.
