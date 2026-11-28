# PWA Studio — dead-letter recovery and two-worker release gate

**Status:** design and test specification only. This document adds no executable SQL, API route, worker wiring, or deployment configuration.
**Branch:** `feature/character-library-foundation`.
**Safety:** do not apply migrations, run SQL, or contact Storage on production. All executable database tests must use a disposable PostgreSQL/Supabase environment.

## 1. Current implementation boundary

The feature branch contains two independent queue consumers:

- Verification: `python -m app.workers.media_outbox_worker`, event type `media_upload_verify_requested`.
- Cleanup: `python -m app.workers.media_cleanup_worker`, event type `media_cleanup_requested`.

Each process has its own poll loop, 3-second idle poll, 120-second claim lease, graceful SIGTERM/SIGINT handling, and bounded exponential retry delay (30 seconds doubled by attempt, capped at one hour). Each claim receives a fresh UUID fencing token. The SQL claim RPCs use `FOR UPDATE SKIP LOCKED`; completion and retry RPCs require the current token and a non-expired lease. The database retry budget is eight attempts.

The migration files 0018 and 0019 remain draft-only. The Render configuration currently runs the API only; neither worker is deployed. Do not infer that a worker process is live from the presence of its Python module or deployment runbook.

## 2. Dead-letter states and safe interpretation

### Verification event

When verification retries are exhausted, migration 0018 moves the event to `dead_letter` and changes an eligible `pending_upload` / `object_uploaded` media row to `upload_failed`. The object is not made readable. A recovery action must not mark the asset `ready` merely because an object exists: the complete byte decode and reserved fingerprint comparison (SHA-256, byte count, MIME, width, height) must run again.

Recommended recovery choices:
1. If the object is present and the immutable reservation metadata is still valid, explicitly requeue the same verification operation with a new recovery audit entry and a fresh attempt budget. The normal verifier must perform the full validation again.
2. If the object is absent or the fingerprint cannot be trusted, keep the asset unavailable. Require a new upload reservation/operation rather than manufacturing a `ready` state.
3. If Storage inspection times out or is ambiguous, leave the event in `dead_letter`; do not infer presence or absence.

### Cleanup event

When cleanup retries are exhausted, or the cleanup claim discovers invalid ownership/lifecycle/reference state, the event moves to `dead_letter`. The associated media row intentionally remains `cleanup_pending`, attached to the character; the character cannot be finalized. This is a safety tombstone, not proof that the Storage object was deleted.

Recommended recovery choices:
1. Revalidate the exact owner, character, cleanup operation, asset, bucket and immutable object key.
2. Recheck references under the same database serialization/advisory-lock rules used by cleanup reservation and reference-write guards.
3. Inspect the exact private Storage object server-side. If the result is ambiguous, stop and leave the event untouched.
4. If the object exists and no reference survives, requeue the immutable cleanup event. The worker may issue the same idempotent DELETE.
5. If the object is already absent and no reference survives, the ordinary worker may safely be requeued to receive 404 and complete the tombstone. Do not manually mark the event delivered without a separately reviewed reconciliation transaction.
6. If any reference exists, the operation ID differs, the path/bucket is malformed, or ownership cannot be proven, leave the event in `dead_letter` for investigation.

## 3. Required operator recovery boundary — not implemented

There is currently no dead-letter recovery RPC, admin endpoint, admin screen, or CLI. Do not update `media_asset_outbox` directly and do not manually change media/character statuses.

A future recovery command should be a narrowly scoped server-side operation with all of the following:

- An authenticated admin/ops actor verified by the backend from the user's current session and authoritative role record. Never trust an `is_admin` flag or actor ID supplied by the browser.
- A mandatory bounded reason and request/correlation ID.
- An immutable audit row recording actor, timestamp, event ID/type, owner/asset/character IDs, previous state, selected action, result, attempt count before/after, and a safe reason code. Do not record service keys, signed URLs, file bytes, or unnecessary raw object paths.
- A transaction that locks the event, media asset and (for cleanup) character; rejects active/unexpired claims; validates owner and operation identity; and rechecks database references before requeue.
- For cleanup, the same canonical object-key rules and per-object advisory lock ordering as the existing reference guards.
- A fresh attempt budget only after an audited recovery decision. Preserve prior attempt history in the audit record and increment a bounded recovery counter; do not silently erase the fact that the event exhausted its budget.
- A strict allowlist of actions by event type. No generic arbitrary status setter.
- Idempotency: repeating the same operator request must not create multiple recovery actions or queue events.
- Service-role-only execution; browser roles must not read or mutate the outbox or audit table.
- Read-back verification after the RPC. If the outcome is uncertain, do not blindly retry the write.

For cleanup, the transaction should requeue only the existing immutable event after all checks pass. For verification, it should requeue only when the same object can be fully revalidated by the normal worker; otherwise require a new upload operation. No recovery action may set `ready` or `deleted` directly.

## 4. Diagnostic data missing from the current queue schema

The outbox currently records state, attempt count, max attempts, availability, claim token/expiry and delivery time. It does not persist a structured last failure reason, last failure time, recovery count, or operator audit history. Worker logs retain the exception class, but that is not a durable operator diagnostic record.

Before an admin recovery surface is built, add a reviewed, privacy-safe diagnostic model:
- `last_error_code`: closed allowlist (for example `storage_not_found`, `storage_timeout`, `fingerprint_mismatch`, `invalid_claim`, `reference_conflict`, `unknown`).
- `last_error_at` and a bounded recovery counter.
- A separate append-only operator action audit table.

Do not store raw exception messages, user filenames, object URLs, signed URLs, request headers, or secrets in the outbox. Keep diagnostics safe and bounded. Schema changes require a new draft migration and disposable-database tests; no production migration is authorized by this document.

## 5. Two-worker verification matrix

Run both worker types as separate processes against one disposable database and private test bucket. Never run both consumers inside the API process.

| Scenario | Verification worker | Cleanup worker | Required assertion |
|---|---|---|---|
| Simultaneous claim | Two verifier sessions race one verification event | Two cleanup sessions race one cleanup event | Exactly one active claim; one token; attempts increments once |
| Independent queues | Verification worker sees cleanup event | Cleanup worker sees verification event | Wrong event type is never claimed |
| Lease expiry | A expires, B reclaims | A expires, B reclaims | B gets a new token; A cannot complete or retry |
| Retry | Storage/read transient failure | DELETE transient failure | Backoff is bounded; lease cleared only by successful fenced retry RPC |
| Exhaustion | Eight attempts | Eight attempts | Event dead-lettered; asset remains unavailable / cleanup tombstone remains |
| Crash before side effect | Stop after claim | Stop after claim | Lease expiry permits safe reclaim |
| Crash after side effect | Stop after object read/verification but before DB completion | Stop after DELETE but before DB completion | Replay is safe; verification repeats; cleanup DELETE 404 is idempotent |
| Concurrent cross-type activity | Verification races a cleanup request for same character | Cleanup races upload reservation for same character | Character/asset guards serialize; no object is marked ready and deleted concurrently |
| Duplicate delivery | Repeated verification delivery | Repeated cleanup delivery | No duplicate logical event; no stale token writes |
| Shutdown | SIGTERM during idle and during work | SIGTERM during idle and during work | Graceful exit; uncertain side effect is not acknowledged |
| Isolation | Owner A event vs owner B IDs | Owner A cleanup vs owner B character/path | No cross-owner Storage request or database mutation |
| Malformed claim | Invalid bucket/path/MIME/fingerprint | Invalid bucket/path/extension/operation | Rejected before Storage call |
| Storage ambiguity | Timeout/404/invalid bytes | Timeout-after-delete/404/permanent denial | No premature ready/deleted state |
| Load | 50 events / 5 sessions, then larger controlled batch | 50 events / 5 sessions, then larger controlled batch | Unique claims, no lost events, bounded DB contention |

The combined scenario is especially important: verification and cleanup are separate event types, but they can affect the same character's media lifecycle. The release test must prove the character-row lock and media lifecycle guards prevent cleanup from starting while upload/verification is still in flight, and prevent a late upload reservation after cleanup intent commits.

## 6. What existing CI proves

At the reviewed branch snapshot:
- GitHub Actions push and PR runs for commit `5aa71dae0a9476f8060b799148d26743c29541bc` both completed successfully with all three jobs successful.
- The 0019 PostgreSQL transaction harness exercises owner denial, browser privilege restrictions, cleanup reservation idempotency, in-flight upload refusal, reference refusal, stale-token fencing, retry, dead-letter tombstone preservation and finalization. It simulates Storage deletion by calling the completion RPC; it does not call Storage.
- The 0019 two-session claim race and two-sided reference-vs-cleanup race have passed in disposable PostgreSQL CI.
- The 50-event / 5-session cleanup batch harness is documented as passing in CI.
- The verification PostgreSQL integration test uses real PostgreSQL RPCs and the real worker/image decoder, but mocks the Storage HTTP transport. It is not a real Supabase Storage E2E test.
- The 0018 two-session verification claim-race shell harness is present but documented as not yet executed.
- The authored verification fault-injection plan includes crash windows and Storage failures that remain unproven against a real Storage service.

CI uses a disposable PostgreSQL 16 compatibility schema with stubbed Supabase auth/storage schemas. It does not prove Supabase Auth JWT/RLS behavior, actual Storage upload/delete semantics, Render worker lifecycle, or production configuration.

## 7. Release gates before any worker activation

1. Run the two worker processes separately against a disposable Supabase project with a private test bucket.
2. Execute the combined upload-vs-cleanup race matrix and the 0018 verification claim-race harness.
3. Test real Storage upload, download, delete success, 404, timeout-after-success, malformed content, and missing-object reconciliation.
4. Test worker stop/restart during every side-effect boundary and verify lease recovery.
5. Add durable safe diagnostics, dead-letter audit and reviewed operator recovery before exposing a recovery interface.
6. Add queue-age, expired-lease and dead-letter monitoring/alerts, plus a tested rollback procedure.
7. Only after all gates pass, propose a separate worker deployment plan. API deployment and worker deployment remain separate decisions.

**Current decision:** keep both workers un-deployed, migrations 0018/0019 unapplied to production, media upload/cleanup UI disconnected, and all live data untouched. This document is a design/release-gate artifact, not approval to activate the pipeline.
