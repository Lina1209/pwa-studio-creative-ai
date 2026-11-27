# PWA Studio — media outbox concurrency and crash-recovery test plan

**Status:** test plan only; no database tests were executed.
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

**Execution status:** tests are authored but not executed. Database concurrency and fault-injection tests remain pending until a disposable Supabase project and exact migration baseline are available.

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
