# Mini Cinema Project Lifecycle and Ownership — Security Audit

Status: **read-only source audit** of the PR branch. This document does not claim live Supabase policies or two-account behavior were re-verified.

## Executive result

The Mini Cinema cloud project path has meaningful owner scoping and account-switch race protections. The frontend captures an immutable owner/auth-generation context, reads and deletes only rows for that owner and `project_type = movie`, and serializes `owner_id` explicitly. The cloud table's migration defines RLS using `auth.uid() = owner_id` for both USING and WITH CHECK.

This is good defense in depth, but it is not a substitute for a live policy inspection and disposable two-account tests. The frontend writes directly to Supabase; there is no backend project API enforcing a second authorization layer.

## Verified protections

### 1. Cloud query scope and account context

In `movie-cloud-operations.js`:

- Every scheduled sync/load receives a captured immutable context containing `ownerId` and `authContextVersion`.
- Stale contexts are rejected before work begins and rechecked after awaited Supabase operations.
- Cloud project reads filter by both `owner_id = context.ownerId` and `project_type = movie`.
- Tombstone deletes filter by ID list, captured `owner_id`, and `project_type = movie`.
- Cloud serialization receives the captured owner explicitly; it does not infer the owner from mutable global session state.
- Old sync cleanup cannot clear a newer operation's context; pending work is rechecked before rescheduling.
- Guest contexts cannot schedule cloud writes.

The application adapter also refuses to read local project data for an owner other than the currently authenticated session. Browser storage keys are partitioned by owner ID.

### 2. Database policy in migration source

`supabase/migrations/0005_cloud_projects_and_storage.sql` defines `public.projects.owner_id` as a foreign key to `auth.users(id)` and declares an authenticated-user policy:

- USING: `auth.uid() = owner_id`
- WITH CHECK: `auth.uid() = owner_id`

That policy is intended to constrain reads, updates, deletes and inserted/updated row ownership to the signed-in user. This is source-level evidence only; the actual live policy must be inspected.

### 3. Delete and restore behavior

- Deletion first removes the project from the account-partitioned local list and records a UUID tombstone in the account-partitioned browser queue.
- A later cloud sync deletes only the matching owner's movie project rows.
- Cloud load also processes that owner's tombstones before merging cloud rows, preventing a deleted cloud project from being reintroduced by the ordinary merge path.
- Restore-from-version updates the same project record and retains version history; it is not a cross-owner operation.
- Copy creates a new project UUID and retains the original record.

The tombstone is a browser-local queue, not a durable server-side deletion job. Clearing browser storage or switching devices before the deletion sync completes can lose the pending delete request. The original cloud project can then reappear on another device. This is a data-consistency limitation, not a demonstrated cross-account disclosure.

## Findings and risks

| Severity | Finding | Required treatment |
|---|---|---|
| High release gate | Live RLS, grants and actual `projects.owner_id` nullability have not been re-inspected for this audit | Run the read-only schema/policy diagnostics before release; do not infer live state from migration source |
| Medium | Cloud project operations are browser-to-Supabase direct, without a backend project API | Preserve strict RLS; verify that the deployed browser only uses the public/publishable key and authenticated user session |
| Medium | Delete tombstones live only in browser localStorage until sync succeeds | Add visible pending-delete state and a durable server-side deletion queue only after schema reconciliation; do not silently claim deletion is cloud-confirmed |
| Medium | Project sync is an upsert of local project rows and merge-by-timestamp, not a full conflict-resolution protocol | Define concurrent multi-device edit policy and test two-device edits before promising conflict-free collaboration |
| Medium | The current merge chooses the newer `updatedAt`; client clocks can differ | Consider server timestamps/version counters or optimistic concurrency before multi-device simultaneous editing |
| Medium | The compatibility migration can add nullable `owner_id` to a pre-existing table without backfill/NOT NULL enforcement | Inspect live nullability and orphan rows; if needed, prepare a separate forward migration after an explicit recovery plan |
| Low | `updated_at` is client-supplied in the current cloud row serializer; migration source has no timestamp trigger | Treat it as a UI conflict hint, not an authoritative audit timestamp; move to server-controlled revision/time for stronger conflict semantics |

## Concurrency and regression coverage

The production-shared controller is tested in `tests-frontend/movie-cloud-operations.test.js` using mocked Supabase operations and deferred promises. Covered cases include:

- A's delayed sync discarded after switching to B;
- A's in-flight upsert retains A's captured owner and cannot update B's UI;
- B's pending sync survives A's cleanup;
- cloud SELECT is owner-scoped;
- stale A SELECT cannot populate B's local list;
- same-user reauthentication invalidates an older context generation;
- guest drafts cannot be uploaded;
- a delayed A deletion cannot continue into B local state.

Both GitHub Actions workflows passed for the media audit commit `c30a3bb735785453ef3bff93f32a95e5449222ad`: Backend tests and Frontend account-context tests. The tests are deterministic unit/controller tests; they do not connect to the hosted Supabase project.

## Required live verification

Before calling project isolation production-verified:

1. Inspect live `public.projects` columns, nullability, foreign keys, unique constraints and indexes.
2. Inspect RLS enabled/forced flags, all policies and grants for `public.projects`.
3. Confirm the live browser key is the publishable/anon key and that no service-role credential is present in frontend assets.
4. Use two disposable accounts A and B to test list, direct UUID read, update, delete, and attempted owner reassignment in both directions.
5. Verify that an A project is never visible in B's list and cannot be read, modified or deleted by B.
6. Test deletion while offline, browser reload before sync, and a second device; record whether deletion is pending or cloud-confirmed.
7. Test simultaneous edits from two devices and document the chosen conflict behavior.

Use harmless synthetic projects and never test adversarial access with the owner's personal account or private creative work.

## Safe next improvements

- Show separate states: saved locally, waiting for cloud sync, cloud saved, deletion pending, deletion confirmed, and sync failed.
- Add retry/backoff for tombstone sync without losing the local queue.
- Add server-controlled revision/version semantics before supporting simultaneous multi-device editing.
- Keep the existing immutable auth-context guard and owner-scoped query filters.
- Keep guest drafts local; never auto-assign guest work to a newly signed-in account.

## Explicit non-actions

- No live Supabase query or account test was performed.
- No project rows were read, created, updated or deleted.
- No SQL, migration, RLS policy or grant was changed.
- No production deployment or PR merge occurred.


## Follow-up regression coverage — 2026-11-24

Added focused controller tests for two additional deletion invariants:

- Tombstone deletion must carry all three filters: the captured project ID list, the captured `owner_id`, and `project_type = movie`.
- If the cloud deletion returns an error, the operation must not proceed to upsert or emit a cloud-success message; the controller reports a sync error and does not clear the tombstone.

These tests extend the mocked production-shared controller suite. They do not exercise hosted Supabase or prove live RLS behavior. GitHub Actions was triggered for both backend and frontend workflows on the new commit; results are pending at the time this note was added.

The browser integration still has a known consistency limitation: deletion tombstones are held in account-partitioned localStorage until cloud sync succeeds. A browser storage clear or device loss before sync can lose the pending deletion. The UI should distinguish local removal from cloud-confirmed deletion before this workflow is presented as durable.

## Follow-up: concurrent editing and version-history review (2026-11-24)

- Mini Cinema stage forms now capture the project's `updatedAt` (falling back to `createdAt`) when opened. Draft-save and stage-completion handlers re-read the latest local project and refuse to write if that version marker changed while the form was open. This prevents a stale form in another tab/device from silently overwriting newer locally visible edits; the user is asked to reopen the stage.
- The baseline marker is advanced after a successful save, so repeated saves in the same open stage remain possible.
- This is a client-side optimistic guard, not a database transaction or a multi-device conflict-resolution system. It relies on client timestamps; same-timestamp collisions, clock skew, cloud upsert races, and simultaneous edits that are not yet visible in local storage remain possible.
- Version history is capped at 20 snapshots. Snapshots are created before edits to project details, stage drafts/completion, renames, and restores. Restoring a version first snapshots the then-current project and retains the history array.
- The history dialog preview still reflects the snapshot list captured when opened, so it can look stale if another tab changes history. Restore now re-resolves the selected snapshot against the latest local history and cancels safely if it is no longer present.
- The snapshot helper is shallow (`{...project}`) and removes only `versions`. Current project fields are predominantly strings and primitive arrays; if nested mutable objects are introduced, snapshotting should switch to a structured deep clone with schema validation.
- No hosted Supabase reads/writes, SQL, migration, merge, or deployment were performed during this review.

- History restore now verifies that the selected snapshot (matching both `savedAt` and serialized snapshot data) is still present in the latest local project's history before applying it. If another edit or history-cap event removed/replaced it while the dialog was open, restore is cancelled with a clear instruction to reopen history. This avoids restoring a stale snapshot that is no longer part of the current retained history.

## Follow-up: tombstone race during sync (2026-11-24)

- Sync now re-reads the owner's tombstone list after any awaited cloud deletion and excludes newly deleted project IDs from the subsequent upsert batch. This closes a client-side race where a deletion created while cleanup was in flight could otherwise be re-uploaded by the same sync cycle.
- A regression test covers a new tombstone added during the pending delete request and verifies that the project is not included in the upsert batch and that the new tombstone remains queued.
- This remains a browser-side coordination safeguard. It does not provide cross-device transactionality or guarantee against concurrent cloud writes from another device/session.

- Additional regression coverage verifies that a new account B load can start and complete while a stale account A load is still pending; the late A response is ignored and cannot populate B's local project list.
