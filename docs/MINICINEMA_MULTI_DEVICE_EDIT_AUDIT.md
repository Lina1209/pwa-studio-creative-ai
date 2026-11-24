# Mini Cinema multi-device editing audit

Status: source-level audit updated on PR #4 head `a49b4e42634d10bb8ff03d61a35aeba7230e7141`. This document records verified frontend behavior, local deletion-queue race mitigation, retry behavior, and the remaining cross-device/server-side concurrency limitation. No production deployment, live Supabase query, schema change, or user-data mutation was performed.

## Scope reviewed

- `app.js`: project details editor, stage draft/completion, rename, copy, restore, local persistence, and cloud-sync scheduling.
- `movie-version-history.js`: immutable snapshots, history cap, restore validation, and backup of the current project.
- `movie-cloud-operations.js`: cloud load merge, timestamp conflict preflight, tombstone processing, and upsert.
- `tests-frontend/movie-version-history.test.js` and `tests-frontend/movie-cloud-operations.test.js`.

## Verified protections

1. **Details and stage editing use a stale-edit baseline.** Each editor captures `updatedAt` (or `createdAt`) when opened, re-reads the latest local project before saving, and aborts if that baseline changed. The baseline advances only after successful local persistence.
2. **Rename re-reads after the prompt.** It checks the current project's baseline before snapshotting and changing the name. A stale form does not silently rename over a newer local copy.
3. **Copy uses the latest locally readable project.** It creates a new project ID, new creation/update timestamps, and an empty version history. It does not mutate the original.
4. **Restore validates the selected history entry against the latest local history.** It checks that the entry still exists, validates the snapshot's project ID and structure, preserves the current live project as the newest history backup, and only reports success after local persistence succeeds.
5. **Cloud load merges rather than blindly replacing local drafts.** A strictly newer cloud timestamp replaces an older local copy; equal timestamps preserve local data; a valid cloud timestamp can replace a local copy with a missing/invalid timestamp; invalid cloud timestamps do not replace a valid local copy.
6. **Cloud sync has a preflight read.** If the cloud copy is already strictly newer at the time of SELECT, that project is retained locally and excluded from the subsequent upsert.
7. **A delete recorded in the same browser profile while an upsert is pending is re-applied immediately after that upsert.** Sync re-reads the local durable tombstone queue after the awaited upsert and issues an owner- and project-type-scoped cloud delete for any row that the just-finished upsert could have resurrected. The tombstone remains queued until a later sync confirms deletion and clears it. This protects same-browser tabs sharing localStorage; it does not propagate tombstones to another device.
8. **Failed cleanup remains retryable.** If the post-upsert cloud delete fails, the tombstone is not cleared. The queued follow-up sync retries the deletion; only a confirmed deletion clears the queue.
9. **Copy and restore are blocked while a local deletion tombstone exists.** Both actions re-read the queue and fail closed if it cannot be read, preventing a stale open history dialog or project card from creating a copy or restoring the locally deleted ID while its cloud deletion is pending.

## Important limits

### Local editor guards are not server-side revisions

The editor baseline is a client timestamp string, not a monotonic server revision. It protects against many stale local-editor situations after a newer cloud copy has been loaded into local storage. It cannot prove that no other device has changed the row since the last load, and timestamp equality/clock skew can make client timestamps ambiguous.

### Local tombstones do not solve a two-device delete/upsert race

The deletion queue is stored in browser localStorage, so it is shared by tabs in the same browser profile but is not shared with another phone, computer, or browser profile. If device B deletes a project while device A has an upsert already in flight, device A cannot see B's tombstone. Depending on request ordering, A's later upsert can recreate the cloud row after B's delete. The new post-upsert cleanup only closes the same-browser-tab race; it must not be described as a cross-device deletion guarantee.

**Required durable fix:** deletion must become a server-side tombstone/soft-delete or revisioned state transition, and upserts must atomically reject rows whose expected revision predates the delete. This is part of the same server-side compare-and-swap requirement below.

### The SELECT-then-upsert sequence is not atomic

The cloud sync sequence is:

1. SELECT existing cloud rows.
2. Compare timestamps.
3. Upsert local rows.

Another device can update a row between steps 1 and 3. The upsert can then overwrite that newer update. This is a confirmed design limitation, not a test or deployment failure. The current frontend cannot fully solve it with another timestamp comparison.

**Required durable fix:** a server-side compare-and-swap operation using a monotonic revision (or equivalent expected-version condition) that atomically rejects stale writes and returns the current row/revision. The server must enforce owner scope and project type. Client timestamps may remain useful for display/merge heuristics but must not be the concurrency authority.

Do not implement this by casually adding a column or applying a migration to the live Supabase project. First reconcile the actual migration ledger, table schema, RLS, grants, and duplicate migration-version history; then test the atomic operation against a disposable PostgreSQL/Supabase environment with two concurrent writers.

## Test coverage and remaining verification

- A deferred-promise regression test records a same-browser tombstone while an upsert is pending and verifies that a scoped cloud delete follows the upsert while the tombstone remains queued.
- A retry test makes that post-upsert delete fail, verifies that the tombstone survives, then verifies a later sync retries and clears it only after success.
- A source-level regression test verifies that copy and restore check the tombstone queue before creating a clone or applying a restored snapshot.
- Version-history unit tests cover deep-copy behavior, 20-entry history cap, restore backup/validation, stale stage completion baseline, rename stale-baseline guard, and restore persistence feedback.
- Cloud-operation tests use deferred promises to exercise account switches, deletion queues, load merges, timestamp precedence, and stale-cloud preflight behavior.
- These are deterministic Node tests against the production-shared frontend modules, not real-browser tests against two signed-in devices and the hosted Supabase project.
- No automated test currently proves an atomic two-device write because no atomic server-side compare-and-swap endpoint exists.
- Real two-account/two-device staging verification remains necessary after the server-side revision mechanism is implemented.

## Release boundary

PR #4 remains open and draft; `main` is unchanged. No live Supabase schema/RLS/Storage change, SQL execution, production deployment, payment, or user-project modification was performed.
