# Supabase migration reconciliation runbook

Date: 2026-11-25  
Status: repository-only planning artifact. No live migration ledger or schema has been read. No SQL has been run.

## Purpose

Establish a safe, evidence-based path from the repository's manually maintained SQL files to a known Supabase schema state. This runbook deliberately does not assume that every file was applied, that files were applied in filename order, or that a CLI migration ledger exists.

## 1. Repository inventory and dependency map

The repository currently contains 15 SQL files and 14 distinct numeric prefixes because two files share `0005`.

| File | Main objects | Prerequisites / dependency notes | Current source-level status |
|---|---|---|---|
| `0001_initial_schema.sql` | `profiles`, legacy `studio_projects/characters/scenes/media`, RLS, new-user trigger | Supabase Auth; creates the legacy studio model | Historical baseline; live state unknown |
| `0002_storage_and_moderation.sql` | Private `studio-media` and `studio-exports` buckets; four Storage policies | Supabase Storage schema | Overlaps with cloud-project 0005 |
| `0003_ai_usage_metering.sql` | `ai_usage` | Supabase Auth | Used by analytics and usage telemetry |
| `0004_assistant_chat_history.sql` | Assistant conversations/messages and timestamp trigger | Supabase Auth; trigger references its conversation table | Independent feature schema |
| `0005_cloud_projects_and_storage.sql` | Mini Cinema `projects`, owner RLS, media bucket/policies | Supabase Auth and Storage | Shares numeric prefix 0005; overlaps Storage policy names with 0002 |
| `0005_moderation_admin.sql` | Reports, suspensions, admin audit log | Supabase Auth | Shares numeric prefix 0005; separate feature schema |
| `0006_notifications.sql` | `user_notifications` | Supabase Auth | Required by 0010; runtime moderation/notification features use it |
| `0007_direct_messages.sql` | Conversation threads and direct messages | Supabase Auth | Runtime messaging schema |
| `0008_user_blocks.sql` | User block list | Supabase Auth | Runtime messaging block checks |
| `0009_user_profiles.sql` | Community-facing `user_profiles` | Supabase Auth | Distinct from legacy `profiles` in 0001 |
| `0010_direct_message_notifications.sql` | Notification type constraint update | Requires `user_notifications` from 0006 | Must not precede 0006 |
| `0011_atomic_message_rate_limit.sql` | Message rate-limit table and RPC | Supabase Auth; trusted backend service-role caller | Backend depends on this RPC when enabled |
| `0012_atomic_ai_rate_limit.sql` | AI rate-limit table and RPC | Supabase Auth; trusted backend service-role caller | Chat/prompt endpoints depend on this RPC when enabled |
| `0013_unified_credit_wallet.sql` | Wallet, reservation, ledger tables and RPCs | Supabase Auth; backend-only operations | Source-only; not proof billing is deployed |
| `0014_admin_analytics_summary.sql` | Aggregate analytics RPC | Requires `profiles` (0001), `ai_usage` (0003), and Mini Cinema `projects` (cloud-project 0005) | Source-only unless confirmed live |

This table is a source dependency map, not a claim about production application order.

## 2. Do not resolve the duplicate 0005 by renaming history

The two 0005 files are separate historical artifacts. Before any CLI adoption or replay:
- Do not rename either file in place.
- Do not rewrite migration versions that may already be recorded by a deployed environment.
- Do not insert guessed rows into `supabase_migrations.schema_migrations`.
- Do not run `supabase db push`, `migration repair`, or a full directory replay against production as an experiment.

First establish the deployment mechanism:
1. Was the project maintained only through SQL Editor?
2. Was Supabase CLI linked and used for migrations?
3. Were both methods used at different times?
4. Is there a migration ledger table, and what exact records does it contain?
5. Are there migration files or one-off SQL changes outside this repository?

If CLI-managed:
- Export the exact ledger rows and preserve their recorded versions, names, and timestamps.
- Compare each recorded version to the repository and identify the collision.
- Build a forward-only reconciliation strategy that preserves deployed history. Depending on the evidence, this may require a reviewed baseline/snapshot or a uniquely versioned bridge migration in a clean test project; do not invent a production repair command.
- Test the chosen strategy against a disposable clone before any production change.

If manually managed:
- The SQL Editor history may not provide a canonical migration ledger.
- Compare live objects against the intended effects of each file.
- Record each object group as present-and-matching, present-but-drifted, partially present, or absent.
- Preserve the manual application evidence. Do not create a fake CLI ledger to make the repository appear synchronized.

## 3. Specific conflict decisions that must be made

### Storage overlap (0002 versus cloud-project 0005)

Source sequence consequence:
- 0002 configures private `studio-media` at 250 MiB and `studio-exports` at 1 GiB; its four user policies cover both buckets.
- Cloud-project 0005 changes `studio-media` to 100 MiB with a different MIME allowlist, then drops/recreates those same four policy names scoped only to `studio-media`.
- If both run in that order, authenticated user policy coverage for `studio-exports` is removed. The bucket remains private; do not infer public exposure.

Before any repair, product owner must decide:
- Is `studio-exports` intended for user-authenticated access or backend-only access?
- What exact MIME and size limits are intended for each bucket?
- Is direct browser upload/download planned, or will the backend issue short-lived signed URLs?
- What are the actual live policies and bucket settings?

Do not automatically recreate export policies or loosen limits.

### Separate profile and project models

- `public.profiles(id,...)` from 0001 and `public.user_profiles(user_id,...)` from 0009 are different models.
- `public.studio_projects(user_id,...)` from 0001 and `public.projects(owner_id,...)` from cloud-project 0005 are different models.
- Do not merge, rename, backfill, or infer data equivalence without an explicit data-migration plan and owner-level validation.

### Forward-only Mini Cinema concurrency change

The server-side revision/CAS design in `docs/MINICINEMA_SERVER_SIDE_CAS_DESIGN.md` requires a new unique forward migration only after the live `projects` schema, RLS, table grants, and migration history are reconciled. It must be tested in a disposable PostgreSQL/Supabase environment before rollout.

## 4. Live metadata collection — read-only gate

After confirming the exact Supabase project from non-secret deployment metadata:
1. Inspect the migration ledger schema and rows without changing it.
2. Run `supabase/diagnostics/inspect_full_security_reconciliation.sql` as a read-only inventory.
3. Retain results privately; redact project identifiers, role/user IDs, and any unexpected sensitive metadata before sharing.
4. Compare live columns, constraints, indexes, RLS flags, policies, grants, functions, triggers, default privileges, sequences, and Storage configuration against the repository.
5. Never select application message bodies, prompts, project payloads, media object paths, signed URLs, tokens, or secrets for this reconciliation.

The diagnostic script is an inventory aid. It does not automatically decide whether a live object is safe or correct; each difference requires review.

## 5. Required evidence matrix

For each migration/object group, record:

| Field | Required evidence |
|---|---|
| Migration/file | Exact repository filename and content hash |
| Deployment source | CLI, SQL Editor, mixed, or unknown |
| Ledger state | Exact version/name/timestamp if a ledger exists; otherwise documented manual evidence |
| Live objects | Tables, columns, constraints, indexes, policies, grants, functions, triggers, buckets |
| Comparison | Matching, drifted, partial, absent, or unable to verify |
| Dependencies | Which backend/frontend features require the object |
| Risk | User data, access control, Storage, billing, or availability impact |
| Decision | No action, forward-only migration, application compatibility change, or further investigation |
| Approval | Separate explicit approval before any shared/production write |

Unknown is a valid result. Never convert missing evidence into an assumption that a migration is absent or applied.

## 6. Disposable environment and CI requirements

Before any candidate migration is considered:
- Create a disposable PostgreSQL/Supabase-compatible project with no production credentials or copied user content.
- Bootstrap a reviewed baseline matching the reconciled schema.
- Apply candidate migrations in the proposed order.
- Test two accounts (A/B), owner-only reads/writes, anonymous denial, admin-only service routes, Storage object ownership, function EXECUTE grants, and rollback behavior.
- For Mini Cinema CAS, use concurrent transactions to prove that exactly one writer succeeds for a given expected revision and that a stale writer cannot revive a deleted row.
- Add CI that provisions the disposable database and executes actual SQL integration tests. Current backend unit CI does not provision PostgreSQL and cannot prove row-lock behavior. Use `docs/SUPABASE_RPC_DISPOSABLE_TEST_MATRIX.md` as the RPC-specific acceptance checklist.

## 7. Stop conditions

Stop without changing production if:
- target project identity is uncertain;
- migration ledger format or deployment history is unknown;
- duplicate 0005 records cannot be mapped to actual applied objects;
- a policy/grant difference could expose another user's data;
- Storage purpose, bucket access, or intended limits are unresolved;
- a candidate migration is not repeatable on the disposable baseline;
- rollback or backup strategy is not verified.

## 8. Current status

- Repository files and dependencies reviewed only.
- Duplicate 0005 remains unresolved by design.
- Storage overlap remains unresolved by design.
- No live migration ledger or live schema has been queried.
- No SQL was executed.
- No production or staging database was changed.
- No migration was renamed, repaired, or applied.
- This runbook is committed on the isolated PR branch only.
