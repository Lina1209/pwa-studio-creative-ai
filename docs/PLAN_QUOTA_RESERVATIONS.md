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
