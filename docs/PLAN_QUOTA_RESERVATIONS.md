# Customer plan quota reservation foundation

Migrations: `0064_atomic_plan_quota_reservations.sql` and `0065_plan_quota_window_semantics.sql`.

Backend adapter: `backend/app/services/plan_quotas.py`.

## What this adds

- Atomic, server-only reservation of plan quota units.
- Idempotent operation keys and request identity checks.
- Append-only quota event history.
- Completion consumes the reserved quota; release returns it.
- Daily and monthly periods are anchored to UTC calendar boundaries.
- Concurrent AI reservations count only while reserved and are released on completion/failure.
- The active plan is resolved from the immutable assignment event stream: the latest event must be `activated`, and exactly one assignment must be effective now.

Supported dimensions: daily/monthly AI requests, concurrent AI requests, and daily/monthly image, video and audio generations.

## Important separation

This is not the existing operational AI admission gate, which protects provider and server capacity with per-minute, daily, monthly and concurrency ceilings.

This is also not the credit wallet or signed pricing quote system. Quota reservation does not debit credits, authorize provider spend, create a generation job, or capture a charge. The generation pipeline must coordinate all required reservations and job creation atomically before provider execution.

## Fail-closed behavior

- No activated assignment: deny.
- More than one effective activated assignment: deny.
- Missing, malformed or zero feature limit: deny.
- Quota exceeded: deny.
- Database unavailable or malformed response: backend adapter fails closed.
- Reusing an idempotency key with different parameters: reject.

Pending assignments do not count as active plans. The assignment base row remains immutable; activation is represented by a future append-only `activated` event. No activation operation is added here.

## Not yet wired into generation

The adapter is deliberately not called from current generation endpoints yet. Before wiring it in, the generation submission transaction must be reviewed so plan quota reservation, signed price quote verification, credit hold, durable job/outbox creation, and rollback/release semantics cannot leave partial reservations.

No customer plan is activated, no free entitlement is enabled, no credits are granted, no provider is called, and no production migration or deployment is performed by this change.


## Atomic generation admission and lifecycle integration

Migrations `0067` and `0068` connect plan quotas to the existing lot-aware credit ledger and durable job/outbox boundary.

The service-role-only RPC `create_plan_credited_generation_job_with_outbox` now composes, in one PostgreSQL transaction:

1. Durable generation job creation.
2. Transactional outbox event creation.
3. Signed quote amount snapshot and lot-aware credit hold.
4. All applicable plan quota reservations.

If the plan is missing, any quota is exhausted, the wallet lacks credits, or any insert/constraint fails, PostgreSQL rolls back the complete submission. A retry with the same owner/idempotency key returns the original job, hold and quota reservations.

Quota mapping:
- Image jobs: daily + monthly image units (the signed quote quantity is the number of image outputs).
- Video jobs: one daily + monthly video generation per job; duration limits remain a separate future dimension.
- Audio and speech jobs: one daily + monthly audio generation per job.
- AI processing jobs: daily + monthly AI requests + one concurrent AI slot.
- Media export is deliberately not admitted by this RPC until a separate quota policy exists.

A request may reserve multiple quota dimensions. The reservation key is unique per user, request and feature dimension; each dimension also has its own deterministic idempotency key.

A database trigger resolves reservations in the same transaction as terminal job state:
- Successful jobs consume daily/monthly usage and release the temporary AI concurrency slot.
- Failed, cancelled or expired jobs release all plan quota reservations.
- Retry-wait jobs keep their reservations because the durable job remains admitted and may resume.

The combined backend service verifies the HMAC-signed quote and canonical request hash before calling the atomic RPC. Client-supplied prices, limits, owner IDs or quota dimensions are not trusted.

## Current activation boundary

This is a server-side admission primitive, not a live generation endpoint. Existing job/worker feature flags remain disabled by default. No pricing catalog has been activated, no plan has been activated for real users, no credits have been granted to real users, and no provider execution or production migration has been started.

The disposable PostgreSQL migration integration suite now includes plan/assignment fixtures and checks atomic admission, daily/monthly reservation, over-quota rollback of job/outbox/credit hold, and quota lifecycle resolution on success. CI must complete against the latest branch SHA before this foundation is treated as verified.


## Plan dimensions intentionally not yet enforced

The plan draft schema also permits `max_parallel_jobs`, `daily_generation_jobs`, `monthly_generation_jobs`, `max_video_seconds`, and `max_resolution`. These are not yet part of the combined admission RPC. They must not be presented as enforced product limits until their semantics are added to the same transaction and covered by integration tests. In particular, maximum video duration and resolution require validated request fields and should be checked against the immutable approved plan snapshot before job creation.
