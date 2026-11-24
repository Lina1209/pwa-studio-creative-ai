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


## Branch follow-up — strict local read uses one storage pass

A final adapter review found that the cloud-specific reader first parsed localStorage, then called the regular UI reader, which read the key a second time and swallowed any later read/normalization-write exception by returning an empty array. A storage failure between those two reads could therefore still be mistaken for an empty collection.

The reader now uses the same normalization path with an explicit strict mode: the UI path can continue displaying its existing error state, while cloud sync/load re-throws the original storage or normalization error and stops before an upsert or merged local write. The redundant preliminary read has been removed. This is a source-level fix; it still needs browser-level storage fault injection and CI confirmation.


## Branch follow-up — deletion-queue reads fail closed

The cloud adapter previously converted any tombstone (owner-scoped deleted-project key) read/JSON error into an empty deletion list. That could allow a pending local deletion to be omitted from the cloud delete step and potentially re-uploaded or reintroduced. The cloud adapter now throws on inaccessible or malformed tombstone storage instead of treating it as empty. UI-only tombstone reading remains separate. Added regression scenarios require sync to stop before upsert/local rewrite and cloud load to stop before local overwrite/render when the deletion queue cannot be read. These are authored tests; execution and CI status remain unverified.


## Branch follow-up — local project write failures fail closed

The cloud-operation adapter already relies on synchronous storage writes throwing through to its operation-level error handlers:
- during sync, a failed owner-keyed local write stops the operation before the cloud upsert and before success feedback;
- during cloud load, a failed local write is caught before rendering, scheduling a follow-up sync, or showing success feedback. The pre-existing local project list is not replaced by a partial in-memory merge.
- the browser adapter does not swallow localStorage.setItem exceptions for project lists, so quota/security failures remain visible to the cloud-operation error path.

A regression test now simulates a quota failure during cloud load and asserts that render, follow-up scheduling, and success feedback do not occur, while the load-error handler receives the storage error. This test is authored but has not yet been executed; CI/browser fault-injection status remains unverified.


## Branch follow-up — UI writes blocked after unreadable local project state

A source review of the ordinary Mini Cinema buttons found a separate hazard from cloud sync: the UI reader intentionally returns an empty list after a localStorage read/JSON error so it can display a friendly error. A create/edit/rename/delete action could then attempt to write that empty-derived list and overwrite projects that were merely unreadable. The UI now records a failed read and blocks subsequent project writes until a later read succeeds. Successful reads clear the guard; ordinary write failures continue to surface through the existing save-error message. This is a source-level safeguard and still requires execution of the frontend tests and browser fault-injection checks.


## Branch follow-up — retry after a failed stage save

Review of the Mini Cinema stage editor found that its optimistic concurrency timestamp was advanced before the localStorage write result was known. If a write failed (for example, quota exhaustion), the editor could then reject a retry as if another window had changed the project. The timestamp is now advanced only after `movieWrite` succeeds, so a failed save does not invalidate the editor's base revision. This change is source-reviewed; browser fault-injection and automated test execution remain pending.


## Branch follow-up — deletion queue read integrity

The Mini Cinema UI previously treated local deletion-queue read/JSON errors as an empty queue. That could allow a delete action to proceed without accounting for pending cloud deletions. The UI now uses a strict reader: absent key means an empty queue, but inaccessible storage, malformed JSON, and non-array values stop the delete action with a visible message. If local project removal fails and rollback of a newly added tombstone also fails, the UI now explains that the cloud deletion remains queued instead of silently implying the project is safely retained everywhere. Added focused tests for missing, valid, inaccessible, corrupt, and wrong-shaped queues. Tests have not yet been executed.


## Branch follow-up — UUID-compatible local project IDs

The browser fallback for project IDs previously emitted a non-UUID string when `crypto.randomUUID` was unavailable. Cloud serialization normalizes such IDs to UUIDs, so a delete racing the first cloud sync could fail to create a UUID tombstone for the local ID while the normalized cloud row was being uploaded. Project ID generation now falls back to a UUID v4-shaped identifier (using `getRandomValues` where available and a compatibility fallback otherwise), keeping deletion markers compatible with cloud IDs. Focused tests cover native, secure-random, and compatibility paths. Tests have not yet been executed.


## Branch follow-up — auth bootstrap race

The initial `getSession()` promise and the auth-state listener can resolve in either order. Previously, a late initial-session result could overwrite a newer sign-in/sign-out/account-switch event. The bootstrap now captures the current auth-context generation and applies its result only if no auth event has advanced that generation. A rejected bootstrap promise is also handled without changing a newer session. This protects the owner context used by Mini Cinema local keys and cloud operations. Source-reviewed; no live auth session was altered.


## Branch follow-up — guest draft expiry validation

Guest drafts remain isolated under the guest localStorage key; authenticated project keys are not subjected to guest expiry. A source review found that a missing expiry was initialized, but a malformed non-empty expiry string parsed to `NaN` and therefore never expired. The reader now normalizes missing or malformed guest expiry values to a fresh 24-hour deadline without mutating the original object. Valid existing deadlines are preserved and are not extended by reads, so this does not silently turn the fixed 24-hour guest retention policy into a rolling inactivity timer. The normalization is applied only while reading the guest key; signed-in project records are left unchanged. Focused Node test definitions cover valid, missing, malformed, and non-mutating behavior. Execution and CI confirmation remain pending.
