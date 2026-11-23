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

## Application security review (source review)

Reviewed the notification, moderation, profile, messaging, authentication, request-schema, and API-route code on this branch.

- User-facing notification reads and updates are scoped to the authenticated user's ID supplied by the server-side route dependency. The client does not submit an acting user ID for these operations.
- Report creation derives `reporter_user_id` from the authenticated session. Report review, report listing, suspension creation/listing/revocation, and Supabase diagnostics are behind the server-side `require_admin` dependency. Moderator/audit actor IDs are derived from that authenticated admin.
- Profile edits target the authenticated user's own ID. Public profile lookup returns only the explicitly selected public fields and requires both public visibility and directory listing for other users.
- Conversation/message reads, read receipts, edits, deletion, and block-list operations derive the acting identity from the authenticated session. Message edit is sender-scoped; self-delete checks participant membership on both the read and write.
- Suspension checks are performed before community messaging/search and assistant/prompt requests. Message sending checks blocks in either direction and applies a per-user recent-message limit.

Items still requiring hardening or live verification:

1. The in-process sequence used for the 20-messages-per-minute check is not atomic. Concurrent requests can pass the count check together. A database-backed atomic rate limiter (or an external rate-limit service) is preferable before opening messaging to a large public audience.
2. The owner role supports a legacy email fallback when `OWNER_USER_ID` is unset. Production should be checked and configured with the immutable Supabase Auth user UUID; do not infer that the setting is already present from repository code.
3. The suspension expiry field is currently accepted as a bounded string by the request schema. Validate it as a timezone-aware datetime before writing to the database, and reject past/invalid values according to a documented policy.
4. The source review does not prove that the live database constraints, RLS policies, indexes, and Storage policies match the repository migrations. The duplicate `0005` version and overlapping export-bucket policies remain unresolved pending live schema/history inspection.
5. No authenticated live integration tests were run against Supabase. The GitHub Actions suite validates mocked/unit behavior only.

No production configuration, database schema, user data, or deployed service was changed during this review.

## Atomic direct-message rate limiting

A follow-up patch replaces the in-process read-then-count check with a database RPC backed by `public.message_rate_limits`.

- The RPC uses one row per user and an atomic `INSERT ... ON CONFLICT DO UPDATE` to increment a fixed 60-second window counter.
- The limit is 20 accepted message attempts per user per fixed window. Concurrent requests for the same user serialize through the unique-row conflict and cannot all pass based on a stale count.
- The counter table has RLS enabled and no client-role table privileges. The function is executable only by `service_role`; the trusted backend supplies the authenticated sender UUID.
- If the RPC cannot be reached, the message request fails closed rather than bypassing abuse protection.
- This is a fixed-window limiter, not a sliding-window limiter; a user may send up to the limit on either side of a minute boundary. Revisit the policy if abuse telemetry justifies a stricter sliding window.

Migration `0011_atomic_message_rate_limit.sql` is a forward migration and has not been applied. It must be reconciled with the actual production migration history and reviewed before execution.
