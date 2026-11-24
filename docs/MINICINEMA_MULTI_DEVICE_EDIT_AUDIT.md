# Mini Cinema multi-device editing audit

Status: source-level audit completed on PR #4 head `0467a320bf12db8eec70deb0d9042d1d9f422078`. This document records verified frontend behavior and the remaining server-side concurrency limitation. No production deployment, live Supabase query, schema change, or user-data mutation was performed.

## Scope reviewed

- `app.js`: project details editor, stage draft/completion, rename, copy, restore, local persistence, and cloud-sync scheduling.
- `movie-version-history.js`: immutable snapshots, history cap, restore validation, and backup of the current project.
- `movie-cloud-operations.js`: cloud load merge, timestamp conflict preflight, and upsert.
- `tests-frontend/movie-version-history.test.js` and `tests-frontend/movie-cloud-operations.test.js`.

## Verified protections

1. **Details and stage editing use a stale-edit baseline.** Each editor captures `updatedAt` (or `createdAt`) when opened, re-reads the latest local project before saving, and aborts if that baseline changed. The baseline advances only after successful local persistence.
2. **Rename re-reads after the prompt.** It checks the current project's baseline before snapshotting and changing the name. A stale form does not silently rename over a newer local copy.
3. **Copy uses the latest locally readable project.** It creates a new project ID, new creation/update timestamps, and an empty version history. It does not mutate the original.
4. **Restore validates the selected history entry against the latest local history.** It checks that the entry still exists, validates the snapshot's project ID and structure, preserves the current live project as the newest history backup, and only reports success after local persistence succeeds.
5. **Cloud load merges rather than blindly replacing local drafts.** A strictly newer cloud timestamp replaces an older local copy; equal timestamps preserve local data; a valid cloud timestamp can replace a local copy with a missing/invalid timestamp; invalid cloud timestamps do not replace a valid local copy.
6. **Cloud sync has a preflight read.** If the cloud copy is already strictly newer at the time of SELECT, that project is retained locally and excluded from the subsequent upsert.

## Important limits

### Local editor guards are not server-side revisions

The editor baseline is a client timestamp string, not a monotonic server revision. It protects against many stale local-editor situations after a newer cloud copy has been loaded into local storage. It cannot prove that no other device has changed the row since the last load, and timestamp equality/clock skew can make client timestamps ambiguous.

### The SELECT-then-upsert sequence is not atomic

The cloud sync sequence is:

1. SELECT existing cloud rows.
2. Compare timestamps.
3. Upsert local rows.

Another device can update a row between steps 1 and 3. The upsert can then overwrite that newer update. This is a confirmed design limitation, not a test or deployment failure. The current frontend cannot fully solve it with another timestamp comparison.

**Required durable fix:** a server-side compare-and-swap operation using a monotonic revision (or equivalent expected-version condition) that atomically rejects stale writes and returns the current row/revision. The server must enforce owner scope and project type. Client timestamps may remain useful for display/merge heuristics but must not be the concurrency authority.

Do not implement this by casually adding a column or applying a migration to the live Supabase project. First reconcile the actual migration ledger, table schema, RLS, grants, and duplicate migration-version history; then test the atomic operation against a disposable PostgreSQL/Supabase environment with two concurrent writers.

## Test coverage and remaining verification

- Version-history unit tests cover deep-copy behavior, 20-entry history cap, restore backup/validation, stale stage completion baseline, rename stale-baseline guard, and restore persistence feedback.
- Cloud-operation tests use deferred promises to exercise account switches, deletion queues, load merges, timestamp precedence, and stale-cloud preflight behavior.
- These are deterministic Node tests against the production-shared frontend modules, not real-browser tests against two signed-in devices and the hosted Supabase project.
- No automated test currently proves an atomic two-device write because no atomic server-side compare-and-swap endpoint exists.
- Real two-account/two-device staging verification remains necessary after the server-side revision mechanism is implemented.

## Release boundary

PR #4 remains open and draft; `main` is unchanged. No live Supabase schema/RLS/Storage change, SQL execution, production deployment, payment, or user-project modification was performed.
