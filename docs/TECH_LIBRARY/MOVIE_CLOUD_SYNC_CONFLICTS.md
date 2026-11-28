# Movie Cloud Sync and Cross-Device Conflict Review

Status: feature-branch implementation and static regression coverage only. No production deployment or live Supabase test was performed.

## Protections implemented

- Local movie storage is parsed fail-closed. Invalid JSON, invalid project records, duplicate IDs, and malformed version history block writes rather than silently becoming an empty library.
- Cloud rows are checked for UUID identity, expected owner, movie project type, and valid update timestamp.
- Cloud load compares local and remote content. A divergent local draft is preserved as a separate local project before the cloud copy becomes the primary project.
- Cloud sync reads the current remote row before updating. Updates use compare-and-swap filters over the observed update timestamp and relevant row content; a zero-row update is treated as a conflict, not success.
- New rows use insert rather than blind upsert, so an ID collision is surfaced.
- Account-context checks fence asynchronous reads and writes.
- Conflict handling is covered by frontend static regression assertions in `tests/test_movie_storage_guard.js`.

## Important limitation: cross-device deletion is not yet safe

Movie deletion currently records a tombstone in browser-local storage and then hard-deletes the cloud row. That tombstone is not shared with another device. A second device that still has an old local copy can later see the cloud row as absent and attempt to insert it again. This can resurrect a deleted project.

This is not solved by the current optimistic-concurrency update guard. It requires a durable server-side deletion marker or deletion ledger, owner-scoped read/write policies, and a defined retention/reconciliation protocol. No such schema change or production migration is included in this review.

Until that design is implemented and tested, do not treat delete synchronization as a reliable cross-device delete. Avoid claiming full cross-device conflict/deletion safety.

## Remaining verification

- CI runs against the feature branch and disposable test infrastructure only.
- No real two-device browser test against live Supabase has been run.
- No production database, storage, user data, deployment, secrets, or environment settings were changed.
