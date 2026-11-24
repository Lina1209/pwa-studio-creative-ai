# Account and User Data Lifecycle — Source Audit

Date: 2026-11-24  
Scope: repository source review of authentication, guest drafts, Mini Cinema project records, community profile storage, and deletion/restore behavior.  
Status: read-only audit; no live account or database operations.

## Executive summary

The repository has a meaningful account-isolation foundation:
- browser authentication uses the Supabase publishable key, not a service-role key;
- backend identity is derived from a verified Supabase JWT and stable subject UUID;
- browser account-context generations invalidate stale asynchronous UI operations;
- Mini Cinema local data is partitioned by authenticated user ID, and cloud project queries include owner and project-type filters;
- the `projects` migration source defines owner-based RLS for reads and writes;
- community profile APIs derive the acting user from the verified backend principal and return an allowlisted public profile.

However, this is not yet proof of live account isolation. The live RLS/grants/migration ledger have not been inspected, and the two-account test plan has not been executed against a disposable Supabase environment.

## Data lifecycle map

### 1. Guest session

- Guest Mini Cinema drafts are stored under the browser key `pwa-studio-movie-projects:guest`.
- Guest drafts receive a 24-hour expiry marker when first normalized by the local reader.
- Guest contexts do not create cloud-sync contexts, so guest drafts are not automatically uploaded to a newly authenticated account.
- Guest data is browser-local. Clearing site data, changing browser/device, or expiry can remove access to it; it is not a cloud backup.

### 2. Registration and sign-in

- The browser initializes Supabase Auth with `PWA_SUPABASE_CONFIG.publishableKey`.
- Sign-in and sign-up are performed through Supabase Auth.
- Backend protected routes verify JWT signature through the Supabase JWKS endpoint and require `exp`, `sub`, `iss`, and `aud`; expected issuer and `authenticated` audience are checked.
- Backend role assignment uses `OWNER_USER_ID` when configured, with email as a backward-compatibility fallback only when the UUID is absent.
- No request-body user ID is used as the authenticated actor for the reviewed profile, messaging, report, notification, or moderation routes; tests explicitly check several of these boundaries.

This source review does not inspect Render environment values, reveal secrets, or establish which owner setting is currently active in production.

### 3. Authenticated Mini Cinema project records

- Local project lists use `pwa-studio-movie-projects:<user UUID>`.
- Local deletion queues use `pwa-studio-movie-deleted:<user UUID>`.
- Cloud reads, deletes, and upserts are scoped to the captured owner UUID and `project_type = movie`.
- The immutable cloud context carries both owner ID and auth-context generation; stale requests are checked before and after asynchronous operations.
- The current project table is `public.projects(owner_id)`, separate from the legacy `studio_projects(user_id)` table in migration `0001`.
- The cloud row stores project payload in `settings` JSONB. It is not a media-binary upload mechanism.
- Local edits and cloud sync use client-generated timestamps and a latest-timestamp merge. This is not a transactional multi-device conflict protocol.

### 4. Community profile

- `/api/community/profile` uses the verified `StudioUser.user_id` for reads and updates.
- The public profile query requires both `visibility = public` and `show_in_directory = true`.
- Public serialization is allowlisted and excludes email and private metadata.
- The backend uses a service-role REST client, so the service layer must always constrain queries to the verified UUID. Current profile methods do so.
- Profile initialization now uses a PostgREST insert-only upsert (`on_conflict=user_id`, `resolution=ignore-duplicates`) and re-reads the verified owner's row when another request wins the first-insert race. This avoids overwriting profile fields and makes concurrent first access idempotent.

### 5. Delete and restore

- Mini Cinema delete removes the project from the current local list and adds its UUID to an owner-partitioned localStorage tombstone queue.
- A later sync sends the cloud delete scoped by IDs, owner UUID, and movie type.
- If the cloud delete fails, the sync path reports failure and retains the tombstone.
- The UI distinguishes local removal from pending cloud confirmation.
- Tombstones are not durable server-side jobs. Browser storage loss before successful sync can lose the pending delete; the cloud row may remain and reappear on another device.
- Version restore re-resolves the selected snapshot against the latest local history before applying it. Version history is capped at 20 entries.
- Project deletion and version restore do not represent a media-object deletion workflow because an end-to-end asset pipeline is not implemented.

## Findings and recommended treatment

| Severity | Finding | Treatment |
|---|---|---|
| High release gate | Live Supabase migration ledger, project RLS, grants, nullability, and Storage policies are not verified by this source review | Run the existing read-only diagnostics in the correct project and compare with intended migration history before release |
| Addressed in branch | If localStorage rejects writing the deletion tombstone, the delete handler now leaves the project in place and shows an error. If the later queue cleanup write fails, sync reports failure rather than success and retains the retry marker | Regression test covers cleanup-write failure; manual browser quota/security testing remains outstanding |
| Medium | Tombstones are browser-local until cloud deletion succeeds | Add a durable server-side deletion queue only after migration reconciliation; meanwhile clearly retain pending status and retry |
| Medium | Client timestamps are used for merge/conflict hints and cloud `updated_at` | Do not promise conflict-free multi-device editing; consider server-controlled revision/version checks before collaboration |
| Addressed in branch | Cloud project upserts now reject malformed row ownership/type/settings and cap each serialized project at 256 KiB and each sync batch at 2 MiB | Regression tests added for oversized and malformed payloads; limits are application-side safeguards, not a replacement for database constraints |
| Addressed in branch | Community profile initialization uses insert-only upsert and re-reads the verified user's row after a concurrent first-insert race | Keep the concurrency regression test in CI |
| Release gate | Existing mocked tests do not prove live RLS or real two-account denial | Execute the disposable two-account test plan, including direct UUID read/update/delete denial and delayed account-switch requests |

## Test coverage already present in source

The repository contains focused tests for:
- JWT owner UUID precedence and fail-closed malformed owner configuration;
- missing/invalid authentication and admin authorization;
- profile owner scoping and public-field allowlisting;
- routes using verified user IDs rather than body-supplied identities;
- stale Mini Cinema contexts, owner-scoped project queries, account switching, guest isolation, tombstone races, and deletion failure behavior;
- community profile initialization insert-only upsert and concurrent first-access race handling.

These are repository test definitions. This audit did not execute them and does not claim they passed in this commit.

## Next safe engineering tasks

1. Run the new payload-limit regression tests in CI and review the user-facing error path for oversized drafts.
2. Add an isolated PostgreSQL/Supabase-compatible CI environment and run migration plus transaction tests.
3. Execute `docs/TWO_ACCOUNT_PROJECT_AND_STORAGE_ISOLATION_TEST_PLAN.md` with disposable accounts after the live migration and RLS metadata are reconciled.

## Explicit non-actions

- No Supabase connection was made and no live schema or user data was queried.
- No user accounts were created or accessed.
- No project/profile/media records were read, created, updated, or deleted.
- No SQL, migration, policy, grant, or Storage setting was changed.
- No production deployment or PR merge occurred.

## Branch follow-up — bounded cloud project payloads

The Mini Cinema cloud sync adapter now validates each outgoing row before calling Supabase:
- row must be an object scoped to the captured owner;
- if present, `project_type` must be `movie` and `settings` must be a non-array object;
- serialized row size is limited to 256 KiB per project and 2 MiB per sync batch;
- serialization failures and limit violations stop the upsert and surface through the existing sync-error feedback path. The local draft remains available; no cloud write is attempted for the invalid batch.

Regression test definitions cover an oversized settings payload and malformed settings. These tests have been added but are not yet confirmed passing; the latest commit's CI result must be checked before treating them as verified.


## Branch follow-up — deletion queue durability and account switching

The latest Mini Cinema changes tighten the local deletion-queue contract:
- the browser adapter returns an explicit boolean from tombstone writes;
- the project delete handler refuses to remove a cloud-backed local project when it cannot persist the tombstone;
- if a cloud delete succeeds but clearing the local tombstone fails, sync reports an error instead of a false success, leaving the marker available for a safe retry;
- load and sync re-read the tombstone queue after awaited cloud deletion so a newer local deletion is not lost or reintroduced;
- stale account-A operations are checked after awaited requests and cannot render or write account-B state; account-B can start its own load while an obsolete A load is pending;
- guest contexts do not create authenticated cloud-sync work; guest drafts remain in their separate browser-local key and are not silently imported into a signed-in account.

Regression test definitions cover cleanup-write failure, account-switch races, same-user reauthentication, guest isolation, and tombstones created during in-flight operations. These tests are present in the branch, but the current head's CI result has not yet been confirmed. This remains source-level and mocked-test evidence, not proof of live RLS or browser-storage behavior.


## Branch follow-up — version-history integrity and unreadable local storage

- Movie version snapshots now use JSON deep copies and exclude nested version history. History remains capped at 20 entries, newest first.
- Restore validates the timestamp, project identity, and basic snapshot shape before changing the live project. A malformed or foreign-project snapshot is rejected without replacing the current draft.
- A successful restore first records the current live draft as the newest history entry, then applies an independent copy of the selected snapshot and preserves the original project ID/creation time.
- Local movie reads now report storage/format failures instead of silently presenting the failure as a normal empty collection.
- The cloud adapter performs a strict owner-keyed local-storage read. If storage is inaccessible, invalid JSON, or not an array, cloud sync/load aborts before upsert or before writing merged cloud data over device state. This prevents a storage read failure from being mistaken for an empty local project list.
- Regression test definitions were added for deep-copy behavior, 20-entry retention, safe restore, malformed/foreign snapshots, and local read failures during sync and cloud load. They are present in the branch; this audit does not claim they passed CI or browser testing.
- No live storage was accessed and no Supabase data was modified.
