# Cross-worker media lifecycle race — disposable integration test specification

**Status:** test specification only; not executed. No migrations, worker processes, Storage requests, or production data are touched.
**Target:** disposable PostgreSQL 16/Supabase-compatible database with draft migrations 0018 and 0019 applied.
**Workers:** verification and cleanup are separate processes. This test validates their shared database lifecycle boundary; it does not claim real Storage E2E.

## Why this test is separate

The existing suites test verification claims and cleanup claims independently. They also test cleanup-reference races. They do not yet execute a single combined scenario in which the verification worker and cleanup worker contend for the same character's media lifecycle.

The intended safety invariant is:

- Cleanup reservation must not commit while a child asset is `pending_upload` or `object_uploaded`.
- Verification may move only the matching, currently reserved asset to `ready`, with a valid live claim and exact fingerprint.
- Once cleanup intent commits, no new media association/reservation for that character may succeed.
- A cleanup worker may claim only an asset already marked `cleanup_pending` and associated with the same cleanup operation.
- A stale verification claim must never make an asset ready after cleanup has been reserved.
- A cleanup worker must never delete an object for an asset whose upload verification is still in flight.

## Fixture

Use one disposable auth user and one character. Create one upload reservation with a unique owner-scoped idempotency key, immutable object key, and known PNG fingerprint. Use generated fixture bytes only. No real user assets.

## Scenario A — verification wins before cleanup intent

1. Reserve upload; assert media row is `pending_upload` and one verification event exists.
2. Mark the object uploaded; assert `object_uploaded`.
3. Claim verification with worker token A.
4. While the verification claim is live, call `pwa_request_character_media_cleanup` in a second database session.
5. Expected: cleanup request fails closed because upload is in flight; its transaction leaves `cleanup_operation_id` null, asset state unchanged, and creates no cleanup event.
6. Complete verification with the exact reserved SHA-256, byte count, MIME, width and height using token A; assert asset `ready` and verification event `delivered`.
7. Request cleanup again with a fresh operation ID; assert character cleanup marker, `cleanup_pending` asset and exactly one cleanup event commit atomically.
8. Claim cleanup with worker token B; assert the claim names the same owner, character, asset, event, operation, bucket and canonical object key.
9. Complete cleanup only in the disposable DB harness; assert asset `deleted`, detached, event `delivered`, and character finalization succeeds only after all child assets are gone.

## Scenario B — cleanup intent wins before a new upload

1. Start with a pre-existing `ready` media asset attached to the character.
2. Request cleanup and commit; assert cleanup marker, `cleanup_pending` asset and one cleanup event.
3. Attempt a new upload reservation/asset association for the same character in a second session.
4. Expected: the character-row lock/cleanup-intent guard rejects the reservation; no second asset or verification event is created.
5. Claim cleanup; before any simulated Storage side effect, assert the claimed operation ID equals the character's cleanup operation ID and the asset remains `cleanup_pending`.
6. Complete cleanup in the disposable harness; assert the original asset is detached/deleted and the character can be finalized.
7. Assert the rejected upload did not leave an orphan verification event or media row.

## Scenario C — stale verifier after lease expiry and cleanup attempt

This scenario is deliberately adversarial:

1. Reserve and mark an upload object uploaded. Worker A claims verification.
2. Expire A's lease and let worker B reclaim the same event with a new token.
3. Attempt verification completion with A's token; it must fail without changing media or event state.
4. Before B completes, attempt cleanup. Expected: cleanup refuses because the media lifecycle is still `object_uploaded`; the cleanup marker and event must not commit.
5. Complete verification with B's token and the exact fingerprint.
6. Retry cleanup after verification reaches `ready`; it may now reserve cleanup.
7. Assert no stale A completion can change the asset after the cleanup reservation.

## Scenario D — crash windows and uncertain side effects

Use test-only fault injection in the disposable environment; remove all hooks after the run.

- Verifier process exits after claim but before Storage read: lease expires; next verifier reclaims with a new token.
- Verifier exits after successful Storage read/decode but before completion RPC: next verifier repeats the read and completes once.
- Cleanup process exits after claim but before DELETE: lease expires; next cleanup worker claims with a new token.
- Cleanup DELETE succeeds but completion RPC is not committed: next worker's DELETE receives already-absent/404 and completes the tombstone using the new token.
- Completion RPC fails after external side effect: database event and asset transition remain atomic; replay is safe.
- Old worker attempts completion/retry after a new worker has reclaimed: every stale-token write is rejected.

A test double or local private Storage service may be used for deterministic HTTP responses, but this does not count as Supabase Storage E2E. Real Storage semantics require a separate disposable Supabase project and private bucket.

## Assertions and evidence to retain

For every scenario, capture only non-secret test evidence:
- event IDs, asset IDs, character IDs and operation IDs generated for the disposable run;
- before/after lifecycle states and attempt counters;
- which claim token won (do not print service credentials);
- SQLSTATE for expected conflicts;
- proof that no duplicate event, orphan row, or cross-owner operation occurred;
- test process exit codes and CI run URL.

Never log JWTs, service-role keys, signed URLs, raw object bytes, or production object paths.

## Execution prerequisites

- Disposable database URL and fixture auth user/character only.
- Exact reviewed draft migration chain applied to that disposable database.
- Two independent database sessions for every race; synchronization barriers rather than timing sleeps.
- Test-only clock/failpoint controls that cannot be enabled in production.
- Cleanup trap that removes only the fixture rows created by this test.
- CI runner must reject any database target not explicitly labelled disposable.

## Pass criteria

All four scenarios pass, with both worker implementations using their actual repository claim/complete/retry functions in the test harness. SQL-only simulations are useful contract tests but do not prove process shutdown, Storage transport behavior, or deployment lifecycle. A separate real-private-Storage E2E run remains mandatory before any worker activation.

**Current decision:** no worker deployment, no API/UI wiring, no production migration, and no production Storage access. Passing this specification later is a prerequisite, not automatic authorization to deploy.
