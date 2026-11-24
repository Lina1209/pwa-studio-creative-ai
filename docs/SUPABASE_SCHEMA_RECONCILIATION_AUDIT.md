# Supabase schema reconciliation audit — follow-up

Date: 2026-11-24  
Scope: repository-only review of migration inventory and read-only diagnostic scripts on the isolated PR branch. This is not a live Supabase inspection.

## Executive result

The repository contains **15 SQL files and 14 distinct numeric migration prefixes** because two unrelated files are both named `0005`. The inventory includes `0014_admin_analytics_summary.sql`. This is a rollout blocker for any migration runner that keys history by version. Do not rename either historical file or replay the directory until the actual deployment history is known.

The existing diagnostic scripts are SELECT-only. A broader inventory script has now been added, but its SQL has not been run against the live project. Repository-only function review also identified hardening items documented separately. No schema change is proposed until live state is reconciled.

## Migration inventory

| Prefix | File | Main objects / purpose |
|---|---|---|
| 0001 | `0001_initial_schema.sql` | `profiles`, legacy `studio_*` tables, owner RLS, auth profile trigger |
| 0002 | `0002_storage_and_moderation.sql` | `studio-media` and `studio-exports` buckets and object policies |
| 0003 | `0003_ai_usage_metering.sql` | `ai_usage` telemetry |
| 0004 | `0004_assistant_chat_history.sql` | Assistant conversations and messages |
| 0005 | `0005_cloud_projects_and_storage.sql` | Mini Cinema `projects`, Storage bucket/policies |
| 0005 | `0005_moderation_admin.sql` | Reports, suspensions, admin audit log |
| 0006 | `0006_notifications.sql` | User notifications |
| 0007 | `0007_direct_messages.sql` | Conversation threads and direct messages |
| 0008 | `0008_user_blocks.sql` | User block list |
| 0009 | `0009_user_profiles.sql` | Community-facing profiles |
| 0010 | `0010_direct_message_notifications.sql` | Extends notification type constraint |
| 0011 | `0011_atomic_message_rate_limit.sql` | Atomic message rate-limit RPC/table |
| 0012 | `0012_atomic_ai_rate_limit.sql` | Atomic AI rate-limit RPC/table |
| 0013 | `0013_unified_credit_wallet.sql` | Wallet, reservations, append-only ledger, RPCs |\n| 0014 | `0014_admin_analytics_summary.sql` | Owner-only aggregate analytics RPC; depends on `profiles`, `projects`, and `ai_usage` |

## Confirmed source-level conflicts and drift risks

1. **Duplicate migration version 0005 — blocker.** The cloud-project and moderation migrations have the same numeric prefix. A CLI migration ledger cannot safely infer a unique order from these filenames. Existing manual SQL Editor history may not match filename order.
2. **Storage policy replacement.** Migration 0002 creates four owner policies covering both `studio-media` and `studio-exports`. The cloud-project 0005 migration drops/recreates similarly named policies for `studio-media` only. If applied sequentially, the later migration removes the user policies for `studio-exports`. Confirm intended export access before any forward migration.
3. **Storage bucket configuration drift.** Migration 0002 sets `studio-media` to 250 MiB and includes PDF; cloud-project 0005 sets a different size/MIME allowlist. The effective configuration depends on the live history and last write.
4. **Two profile models.** Initial schema creates `public.profiles(id,...)`; community profile migration creates `public.user_profiles(user_id,...)`. These are separate data models. Do not treat them as interchangeable or assume one is a renamed version of the other.
5. **Two project models.** Legacy `studio_projects(user_id,...)` and Mini Cinema `projects(owner_id,...)` are separate tables and ownership contracts. Current Mini Cinema sync targets `projects`; the older studio tables are not proof of a common asset/project schema.
6. **Separate media model is incomplete.** The legacy `studio_media` row links to `studio_projects` with nullable `project_id` and `ON DELETE SET NULL`; the source schema does not enforce that media.user_id matches the linked project's user_id. No shared asset API is wired into the application.
7. **Migration instructions are mixed.** Several SQL headers describe manual SQL Editor application; docs also refer to migration-ledger inspection. The actual production deployment mechanism must be established before selecting a reconciliation procedure.
8. **Wallet migration is not a billing rollout.** `0013` is source-only; the pricing catalogue is empty and generation routes do not debit credits. Do not infer that wallet tables/RPCs exist in production.

## Diagnostic script review

### Existing scripts

- `supabase/diagnostics/inspect_cloud_storage.sql`: SELECT-only initial inventory of selected table names/columns, two Storage buckets, and `public.is_admin()`.
- `supabase/diagnostics/inspect_project_asset_security.sql`: SELECT-only focused inventory of selected columns, constraints, indexes, RLS flags, policies, table grants, bucket settings, approximate row estimates, and migration-ledger locations.\n- `supabase/diagnostics/inspect_full_security_reconciliation.sql`: expanded SELECT-only inventory of all public columns/constraints/indexes, public and Storage policies, table ACLs, function owners/SECURITY DEFINER/settings/EXECUTE ACLs, trigger definitions, sequence ACLs, default privileges, Storage bucket configuration, row estimates, and migration-ledger candidates. This script has been source-reviewed but not executed against production.

### Coverage gaps to close before a complete live audit

The scripts do not yet comprehensively inventory:
- every application table in migrations 0003–0013 (assistant history, usage, moderation, notifications, messaging, blocks, rate-limit tables, wallet tables);
- function definitions, owners, SECURITY DEFINER flags, effective EXECUTE grants, and function `search_path`;
- triggers and trigger-function definitions (including profile creation and timestamp/message lifecycle triggers);
- sequence/identity privileges and default privileges;
- Storage policy expressions plus bucket MIME allowlists in one consolidated output (bucket query exists, but policy query is broad and should be retained separately);
- migration ledger records and ordering (the current script only discovers candidate ledger locations/columns, intentionally does not assume a format).

The backend diagnostics endpoint is not a substitute for this SQL inventory: its table probe is a limited availability check using HEAD requests. It does not verify RLS, grants, policies, constraints, functions, triggers, or cross-account isolation. In particular, its profile probe targets `user_profiles`, not the separate legacy `profiles` table.

## Safe reconciliation sequence

1. Confirm the exact Supabase project identity from non-secret deployment metadata; never expose API keys, JWTs, signed URLs, or service-role credentials.
2. Obtain the live migration ledger and determine whether the project was managed by Supabase CLI, manual SQL Editor, or both.
3. Run only the existing SELECT-only inventory scripts after confirming the target project. Retain outputs privately and redact identifiers or user content before sharing.
4. Run `supabase/diagnostics/inspect_full_security_reconciliation.sql` (SELECT-only) to inventory tables, policies, grants, functions, triggers, sequences, defaults, and Storage settings. Do not select user content or private media. Review the repository-only findings in `docs/SUPABASE_FUNCTION_SECURITY_SOURCE_AUDIT.md`.\n5. Follow `docs/SUPABASE_MIGRATION_RECONCILIATION_RUNBOOK.md` to record per-migration evidence and resolve the duplicate 0005 without rewriting deployed history.
5. Compare live state to each migration's intended objects; record applied, partially applied, absent, and drifted objects. Do not infer application from a filename or documentation note.
6. Resolve the duplicate 0005 history without rewriting already-deployed migration records. Any future changes must use a new, unique forward version chosen after ledger inspection.
7. Design disposable-environment tests for two authenticated accounts (A/B), guest behavior, owner-scoped CRUD, storage object access, admin-only endpoints, and RPC privilege boundaries.
8. Only after a reviewed plan and explicit approval should any production SQL or deployment be considered.

## Current safety boundary

- No live Supabase connection or SQL was run for this audit.
- No schema, policies, grants, buckets, users, project data, or secrets were changed or read.
- No migrations were applied.
- No Render deployment or PR merge was performed.
- PR remains isolated from production.\n- The expanded diagnostic script and function source audit are committed on the PR branch only; neither has been run against live Supabase.
