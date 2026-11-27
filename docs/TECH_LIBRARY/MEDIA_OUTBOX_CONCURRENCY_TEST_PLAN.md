# PWA Studio — media outbox concurrency and crash-recovery test plan

**Status (2026-11-27):** migration chain 0005/0012/0017/0018/0019 and both 0019 SQL harnesses passed in GitHub Actions run 43 against a disposable PostgreSQL 16 instance with a minimal Supabase-compatible auth/storage schema. The harnesses were executed, not merely authored. This is not a full Supabase stack and does not exercise real Supabase Storage HTTP operations or production configuration.
**Target:** disposable PostgreSQL/Supabase project matching the reviewed migration chain.
**Never run this plan against production.**

## 1. Two-worker claim race

Fixture: one pending event due now; workers A and B start simultaneously.

1. Start two independent database sessions.
2. Synchronize both sessions immediately before the claim RPC.
3. Execute the claim RPC concurrently.
4. Assert exactly one worker receives the event.
5. Assert the row has one claim token, one expiry, and attempts incremented exactly once.
6. Assert the other worker receives no claim and cannot acknowledge or retry the event.

Repeat with a batch of 50 events and 5 workers. Assert no event is actively claimed by two workers and no event disappears.

## 2. Expired lease and stale worker

1. Worker A claims event with token A and short test lease.
2. Advance database time beyond lease expiry (use a controllable test clock or explicit expiry fixture; do not sleep in CI).
3. Recovery makes the event eligible for a new claim.
4. Worker B claims it with a fresh token B.
5. Attempt acknowledgement, retry, and asset-state mutation using token A.
6. Assert every token-A write affects zero rows / returns a stale-claim conflict.
7. Assert token B can perform the permitted transition exactly once.

## 3. Atomicity fault injection

Use a disposable database and a test-only trigger/RPC fault switch:

- Fail outbox insertion after media row insertion: assert both roll back.
- Fail media status mutation after event insertion: assert both roll back.
- Commit both: assert exactly one matching event exists.
- Retry same owner-scoped idempotency key and same request fingerprint: return the original operation without adding a row.
- Reuse key with different fingerprint or asset ID: reject with conflict and leave state unchanged.

Remove all fault-injection hooks after tests.

## 4. Crash windows

Simulate process termination at each boundary:

- after claim commit but before side effect;
- after Storage upload but before metadata-ready transition;
- after metadata-ready transition but before event acknowledgement;
- after Storage delete but before tombstone finalization;
- after tombstone finalization but before event acknowledgement.

For each case, restart a worker and replay the event. Assert idempotent reconciliation, no cross-owner effects, no duplicate object overwrite, no premature ready state, and no deletion of a referenced object.

## 5. Security and isolation

With disposable users A and B:

- A's event cannot reference B's media asset.
- B cannot select, claim, inspect, acknowledge, or retry A's event.
- Browser roles `anon` and `authenticated` cannot select or mutate outbox rows.
- A forged owner ID or Storage path in the request cannot affect worker resolution.
- Worker lookup filters by both `asset_id` and `owner_id`.
- Every cleanup attempt re-checks exact bucket+path references immediately before deletion.

## 6. Invariants to assert

- At most one live claim per event.
- Claim attempts increase exactly once per successful claim.
- Every claim token is unique for the event's successive leases.
- A stale token never mutates event or asset state.
- No event is lost between committed metadata transition and outbox insertion.
- Delivery is at-least-once; side effects are idempotent.
- Retry is bounded; exhausted events enter dead-letter and alert.
- No secret, signed URL, raw object path, or file bytes enter event records or logs.

## 7. Current pure-model coverage

`backend/tests/test_media_outbox.py` now includes stale-token rejection after worker B reclaims an expired worker A lease, acceptance of only worker B's token, exhausted-attempt handling, and rejection of stale retries. These tests exercise the pure Python model only; they do not establish PostgreSQL locking, transaction atomicity, RLS, or Storage correctness.

Static SQL guardrails in `backend/tests/test_media_cleanup_sql_contract.py` also pass, checking globally sorted advisory-lock acquisition, cleanup ordering, browser privilege revocations, and service-role-only RPC grants.

**Execution status:** the pure Python tests and the 0019 disposable PostgreSQL transaction/race harnesses have executed successfully in GitHub Actions. The CI database is PostgreSQL 16 with stubbed Supabase auth/storage schemas; it verifies PostgreSQL migrations, row locks, RPCs, and independent-session claim behavior, but not Supabase Auth, Storage service, actual RLS JWT integration, or object deletion. The broader 50-event/5-worker race and transaction fault-injection cases remain pending.

## 8. Media upload verification worker (migration 0018 draft)

For one character-reference event in a disposable database and private Storage bucket:

1. Commit a pending_upload media row and its verification event through the reservation RPC.
2. Upload a valid object but intentionally leave the row pending_upload. Claim and verify it; assert the worker can advance it directly to ready after matching SHA-256, size, MIME, width, and height.
3. Repeat with object_uploaded status. Assert the same final ready + delivered outcome.
4. Mutate one byte, truncate the object, change MIME metadata, or alter dimensions. Assert no ready transition occurs; retry remains bounded and the final state is upload_failed + dead_letter.
5. Delete the object before verification. Assert a transient 404 is retried with backoff and never becomes ready.
6. Let worker A's lease expire during verification; let worker B reclaim with a fresh token. Assert A cannot complete or retry and B alone can commit.
7. Race two claim RPCs against one event. Assert FOR UPDATE SKIP LOCKED yields exactly one active claim.
8. Fail the completion transaction between the media update and outbox acknowledgement. Assert both changes roll back.
9. Simulate a crash after byte verification but before completion. Assert a later worker can safely repeat the download and complete exactly once.
10. Verify that a completed ready asset is not downgraded by the upload request's later object_uploaded RPC response path.

**Not executed:** these are required integration/fault-injection cases. The authored Python worker/repository tests mock all external systems and do not substitute for this database/Storage matrix.

## 9. Executable two-session claim race harness

A disposable-only shell harness is available at `supabase/tests/0018_media_upload_claim_race.sh`. It opens two independent `psql` connections concurrently against one reserved verification event and asserts that exactly one receives the event while the other receives SQL NULL. It then expires the winning lease deterministically, has a second token reclaim the same event, and verifies that the old worker cannot complete or schedule a retry. Finally it checks that the event remains claimed by the fresh token and that the attempt counter is exactly two.

Required environment:
- `DISPOSABLE_DATABASE_URL`: connection string for a disposable PostgreSQL/Supabase database with migrations 0005, 0012, 0017, and 0018 applied.
- `PWA_TEST_OWNER_ID`: existing auth user UUID.
- `PWA_TEST_CHARACTER_ID`: character UUID owned by that user.
- Local `psql` and Python 3.

Run with `bash supabase/tests/0018_media_upload_claim_race.sh`. The script refuses to run if any other media verification event is pending or claimed, creates one fixture, runs the race, and deletes its own fixture on exit. It does not call Storage. Use a disposable database only; never production. This harness has been authored but not executed.

## 10. Character deletion and cross-owner cleanup matrix (release gate)

Migration 0019 now drafts a transactional cleanup-intent fence, reference checks, cleanup outbox, leased claims, fenced completion/retry, and a finalizer. The SQL transaction harness covers core single-session behavior and metadata-reference refusal. The two-session race harness is in section 11. These checks are no longer merely authored: the transaction and two-session race harnesses passed on disposable PostgreSQL 16 in CI. The transaction harness now also checks that a foreign owner cannot reserve cleanup for a known character UUID, that an empty character finalizes without an outbox event, and that a transient retry can be reclaimed under a fresh fencing token. The remaining matrix below is still a release gate.

Remaining release-gate cases:
- Character A with zero media rows: remove only the owner-matched character; no Storage request.
- Character A with several assets: every eligible asset becomes `cleanup_pending` and receives exactly one cleanup event in the same transaction.
- Passport or another media row references an object: refuse cleanup; never delete the referenced object.
- User B submits A's character, asset, or Storage path: no cross-owner lookup or DELETE.
- Storage DELETE succeeds, returns 404, times out after possible success, or returns a permanent error: reconcile and retry without premature tombstoning.
- A new reference races with cleanup intent: exactly one operation wins under the database serialization guards. Reference triggers and the cleanup reservation acquire per-object advisory locks in deterministic bucket/path order to reduce lock-order inversion risk when rows contain multiple references.
- A dead-letter event remains recoverable by an operator; the character must not be finalized while any associated media row remains.
- Final character deletion succeeds only after every child media row is detached and confirmed absent.

No user-facing delete route or frontend integration is enabled. Migration 0019 is a draft and must first be applied and tested only in a disposable database. No production migration, Storage deletion, or worker deployment has occurred.

## 11. Character cleanup outbox and worker (migration 0019 draft)

The disposable-only SQL harness is `supabase/tests/0019_media_cleanup_transaction.sql`. It creates a character and one private media fixture, verifies foreign-owner denial, reserves cleanup twice with the same operation ID, checks exactly one outbox event, claims with worker A, expires the lease, reclaims with worker B, and verifies that A cannot complete or retry. It simulates Storage DELETE success by invoking worker B's completion RPC, verifies the tombstone is detached and the event delivered, and finalizes the character. It also checks zero-media finalization and a transient retry followed by a fresh claim and successful completion. All database fixtures roll back.

Run only with:
- `DISPOSABLE_DATABASE_URL` pointing to a disposable Supabase/PostgreSQL database.
- `PWA_TEST_OWNER_ID` set to an existing disposable Auth user UUID.
- Migrations 0005, 0012, 0017, 0018, and 0019 applied to that disposable database.
- `psql` available locally.

Example:
```bash
psql "$DISPOSABLE_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -v PWA_TEST_OWNER_ID="$PWA_TEST_OWNER_ID" \
  -f supabase/tests/0019_media_cleanup_transaction.sql
```

The SQL harness does **not** call Supabase Storage; it validates database transaction and fencing behavior only. Separately run the Python worker/repository tests with the backend test environment. Neither test suite has been executed yet. The Storage delete unit tests also cover mocked 200/404, timeout, permanent rejection, invalid path/bucket, and missing credentials; these mocks do not verify a real Supabase Storage deployment.

The two-session race harness is `supabase/tests/0019_media_cleanup_claim_race.sh`. It creates one disposable character and ready image, requests cleanup, launches two independent `psql` sessions, and asserts exactly one claim. It then expires the lease, reclaims with a new token, verifies that the stale token cannot retry or complete, completes using the fresh token, and finalizes the character. It does not contact Storage.

Run only after migrations 0005, 0012, 0017, 0018, and 0019 are applied to a disposable database:
```bash
DISPOSABLE_DATABASE_URL="..." PWA_TEST_OWNER_ID="..." bash supabase/tests/0019_media_cleanup_claim_race.sh
```
The script requires an otherwise idle cleanup queue. If it fails, it intentionally preserves its fixture in that disposable database for diagnosis. The harness passed in GitHub Actions run 43 against disposable PostgreSQL 16. Its parser treats psql's blank `-qAt` output for SQL NULL as the expected losing-worker result (not as a missing execution result).

Still required before activation: run the full Supabase two-account RLS/Storage matrix; test actual Storage DELETE success/404/timeout-after-delete; run an adversarial reference-write-vs-cleanup race; test batches of many events and workers; and exercise dead-letter/operator recovery. The foreign-owner cleanup reservation check is now covered by the passing SQL transaction harness. Never run these harnesses against production.

The 0019 SQL harness passed in CI and verifies that authenticated browser roles have no direct media metadata INSERT/UPDATE/DELETE or character DELETE privilege, cannot forge the server-managed cleanup marker, and that late character-reference upload reservations are rejected after cleanup intent is committed. It also checks foreign-owner denial, refusal of an unindexed private path, external metadata references, and rollback when an upload is still in flight. The migration scans media metadata and other character passports for surviving references. These are PostgreSQL integration checks on the disposable compatibility schema, not live Supabase RLS/Storage tests.
