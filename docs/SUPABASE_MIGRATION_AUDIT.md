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


## AI endpoint rate limiting

The API now calls a separate database RPC before sending requests to the configured AI provider from `/api/chat` and `/api/prompts`.

- The default policy is 10 accepted requests per user, per endpoint, per fixed 60-second window.
- Each endpoint has its own counter so chat traffic does not consume prompt-generation slots.
- The RPC uses an atomic unique-key upsert on `(user_id, endpoint)`; simultaneous requests cannot all pass using a stale read.
- The counter table has RLS enabled, client roles have no table privileges, and function execution is granted only to `service_role`.
- A denied request returns HTTP 429 before calling the AI provider. If storage protection is unavailable or returns an unexpected response, the API fails closed with HTTP 503.
- This is a request-frequency guard, not a subscription quota or monetary spending cap. It does not replace future server-side credit accounting, daily/monthly plan quotas, provider budget alerts, or cost reconciliation.
- The fixed-window design can permit a burst around a window boundary; revisit with real abuse telemetry.

Migration `0012_atomic_ai_rate_limit.sql` is source-only and has not been applied to Supabase. It must be reconciled with the live migration ledger and schema before rollout.


## AI output-token ceiling

The AI service now sends a server-controlled `max_tokens` value with every provider completion request. The setting is `AI_MAX_OUTPUT_TOKENS`, defaults to 2048, and is validated to remain between 256 and 8192. This bounds generated output tokens per request and makes the maximum output budget explicit in deployment configuration. It is not a full monetary cap: input tokens, model pricing, retries, and actual provider billing still require usage reconciliation and budget controls. The limit should be tuned against the selected DeepSeek model's supported parameters and the quality/length requirements of each studio workflow.


## Unified credits migration 0013 — source-level review

Reviewed `0013_unified_credit_wallet.sql` from the PR branch. This is a static source review only; it was not executed against PostgreSQL or Supabase.

- Creates one account-level wallet, idempotent reservation records, and a ledger with grant/reserve/capture/release/reconciliation events.
- Wallet rows are locked before reservation rows in grant/reserve/settle/release/reconciliation paths. This consistent lock order reduces deadlock risk for concurrent lifecycle operations.
- Reservation retries are checked after acquiring the wallet lock and must match operation code, pricing version, and reserved amount.
- Grant retries are serialized on the wallet row and checked against the existing ledger event; reusing the same source/reference with a different amount raises an error.
- Client roles have no table privileges. The service role receives SELECT only; mutation is intended to happen through SECURITY DEFINER RPCs whose EXECUTE privilege is revoked from PUBLIC/anon/authenticated and granted to service_role.
- Settlement returns the unused reservation amount to available balance; release returns the full reservation. Ambiguous provider outcomes retain reserved funds in `reconciliation_required`.
- The migration does not create subscription tables, a plan catalogue, persistent operation-pricing rows, payment records, expiry jobs, or frontend wallet support. Those remain future work.

### Review notes / preconditions

1. The RPC functions trust the backend service role to supply the correct user UUID, grant source, and operation outcome. This is acceptable only while the service key remains server-only and every caller derives user identity from verified auth context. Never expose these RPCs to browser clients.
2. The grant-source allowlist is enforced in the Python adapter, not duplicated in the database function. Keep the RPC service-role-only; consider a database-side allowlist before adding more callers or administrative tooling.
3. The current source review does not establish PostgreSQL behavior under concurrent sessions. Test concurrent grants/reservations, duplicate idempotency keys, settlement-vs-release races, and reconciliation transitions against a disposable PostgreSQL/Supabase project before rollout.
4. The migration's `CREATE TABLE IF NOT EXISTS` statements do not reconcile an existing table with a different shape. Before applying it anywhere, inspect whether any of these names already exist and compare every column, constraint, index, grant, and policy.
5. The migration does not seed wallets or create a wallet for a user during reservation. A first verified grant must create the wallet; a reservation without a wallet returns insufficient credits. Confirm this is the intended onboarding flow.
6. No production pricing is possible yet: the pricing catalog is empty and no provider rates, conversion factor, plan allowance, or operation price has been approved.

## Subscription and entitlement structure — design boundary

The next layer should remain a design/service foundation until migration history is reconciled. It should model:

- immutable, versioned plan definitions;
- subscription state and verified billing-period boundaries;
- feature entitlements and hard resource limits separately from credits;
- one-time, idempotent allowance grants per subscription period;
- a usage-event record that distinguishes requested operation, accepted job, provider usage, measured provider cost, and reconciliation status;
- an auditable link from subscription period to credit grant reference.

Do not create active paid plans, prices, credit allowances, payment webhooks, or credit deductions as part of this source audit. Guest demo limits must remain separate from registered-account subscription entitlements. Provider cost telemetry must remain separate from the user credit ledger.

## Source-only status of the newer migrations

- `0011_atomic_message_rate_limit.sql`: source-only fixed-window message limiter.
- `0012_atomic_ai_rate_limit.sql`: source-only fixed-window AI endpoint limiter.
- `0013_unified_credit_wallet.sql`: source-only wallet, ledger, and reservation lifecycle.
- None of these files has been verified against the live migration ledger or executed on the connected Supabase project.
- The two `0005` files and the `studio-exports` policy overlap remain the first migration-history blockers. Do not rename, reorder, or replay historical files based only on repository filenames.


## Existing AI usage telemetry — source verification

The repository contains `0003_ai_usage_metering.sql`, which defines the current `public.ai_usage` source schema:

- identity: generated bigint `id` and unique UUID `request_id`;
- owner and operation: `user_id` referencing `auth.users`, `endpoint` restricted to `chat` or `prompts`, and `provider`;
- model and measured usage: `model`, nullable non-negative `input_tokens`, `output_tokens`, and `total_tokens`;
- optional cost metadata: nullable non-negative `cost_usd numeric(20,10)` and nullable `cost_source`;
- event time: `created_at timestamptz`;
- indexes: `(user_id, created_at desc)` and `(created_at desc)`;
- RLS enabled, with no anon/authenticated policies declared in this migration. The backend writes using its server-only Supabase service-role credential.

The current backend path is `ask_ai()` → `AIResult` → `record_ai_usage()`, called after successful `/api/chat` and `/api/prompts` completions. LiteLLM usage fields are copied when present. Optional `response_cost` is read from LiteLLM hidden response metadata and labeled `litellm_response_cost`; it is a LiteLLM-calculated cost signal, **not proof of a provider invoice or a settled provider charge**. Missing token/cost data remains NULL. The telemetry insert is best-effort with a five-second HTTP timeout; failures do not fail the completed AI response and can therefore leave gaps.

A new unit-test module covers the payload contract, NULL cost semantics, omission of prompt/response content, missing server credentials, and non-fatal/redacted telemetry failures. These are mocked tests and do not establish that the live table exists or that production inserts succeed.

### Explicit limitations

1. The current table only models chat and prompt token usage. It cannot yet represent image counts, generated video/audio duration, render time, storage, bandwidth, asynchronous job lifecycle, provider job IDs, or invoice reconciliation.
2. It has no durable outbox/retry queue, so a transient Supabase outage may lose a telemetry event.
3. It has no currency/status/price-reference columns. Do not reinterpret NULL cost as zero, and do not aggregate LiteLLM-calculated cost as invoice-confirmed spend.
4. The live table definition, RLS policies, grants, row counts, retention, and migration ledger have not been queried. The migration file is source evidence only.
5. No new telemetry migration is proposed until the live schema and migration history are reconciled. No SQL was applied.


## Reconciliation with earlier documented live checks (2026-11-21)

A related repository document, `docs/IMPLEMENTATION_ROADMAP.md`, records earlier hands-on verification that `0004_assistant_chat_history.sql` and specifically `0005_cloud_projects_and_storage.sql` were manually applied to the connected Supabase project. It also records that `public.projects`, the private `studio-media` bucket, a test project row, and persistence after browser refresh were checked at that time.

This is important historical evidence and supersedes any broad reading of the phrase “no live schema ... were queried” above: live checks did occur for those named objects on 2026-11-21. The present audit did not repeat those checks and does not establish the current state as of this branch review. It also does not establish that the other file named `0005_moderation_admin.sql` was applied, how the duplicate version was recorded in any migration ledger, or what happened to the `studio-exports` policies after the cloud-project migration replaced shared policy names.

Accordingly:

- Treat `0004_assistant_chat_history.sql` and `0005_cloud_projects_and_storage.sql` as historically reported applied and partially verified, not as migrations to replay.
- Treat the live state of `0002_storage_and_moderation.sql`, `0005_moderation_admin.sql`, the `studio-exports` bucket/policies, and all later migrations as unconfirmed until inspected.
- Preserve the historical migration files and names. Do not rename or replay either `0005` file to “fix” the collision.
- Before any future migration, perform a read-only live inventory of the Supabase migration ledger (if available), tables, constraints, functions, grants, RLS policies, and both Storage buckets; then compare it with the dated evidence in the roadmap.
- The earlier verification was limited to the objects and behaviors explicitly listed above. It was not a two-account isolation, cross-device, full Storage-policy, or complete migration-history audit.

No live Supabase query or mutation was performed as part of this documentation reconciliation.

## Cloud project migration source review

Additional source-level findings from `0005_cloud_projects_and_storage.sql`:

- On a brand-new database, `public.projects.owner_id` is declared `NOT NULL` and references `auth.users(id)`.
- The compatibility statement later uses `ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES auth.users(id) ON DELETE CASCADE` without `NOT NULL`, a backfill, or a validation step. If an older `projects` table already existed without this column, the resulting column can remain nullable. The owner RLS predicate denies rows whose owner is NULL, but those rows may become inaccessible/orphaned and the intended invariant is not enforced.
- The migration does not install a trigger to maintain `updated_at`; the client currently supplies timestamps. Any future server-side writer must update this field consistently or add a reviewed database trigger.
- The browser upsert uses `ON CONFLICT (id)`; its safety depends on the owner RLS policy and the row's `owner_id`. Cross-account conflict attempts must be tested rather than assumed safe from the client filter.
- Do not patch this historical migration in place or apply it again to production. First inspect the live column nullability, foreign key, constraints, indexes, policies and existing rows. If correction is required, prepare a new uniquely versioned migration with an explicit orphan-row/backfill policy and test it against a disposable copy.

These are conditional schema risks inferred from the migration source; they are not claims about the current live database.
