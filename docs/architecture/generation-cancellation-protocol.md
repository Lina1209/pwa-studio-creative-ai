# Generation cancellation protocol

Status: design baseline for implementation; not a claim that provider cancellation is available.

## Goals

- A cancellation request is authorized by the authenticated job owner.
- A running provider operation is never treated as stopped merely because a local asyncio task was cancelled or a worker lease was lost.
- User credits and plan quota reservations remain held until the external operation is reconciled and a worker atomically acknowledges cancellation.
- Completion and cancellation race through one database row lock; exactly one terminal outcome wins.
- Provider-side spend is recorded independently of whether the user receives a credit refund.

## Implemented baseline

Migration 0085 implements owner-scoped cancellation requests:
- `queued` and `retry_wait` jobs become `cancelled` and release a held credit in the same transaction.
- `running` jobs become `cancel_requested`; the lease and held credit are preserved.
- repeated requests are idempotent; terminal jobs are immutable.

Migration 0086 and the provider-neutral worker now add:
- structured heartbeat states: `active`, `cancel_requested`, `terminal`, and `lease_lost`;
- lease renewal continues while the matching worker reconciles a cancellation request;
- in-flight provider operations may journal their definitive acceptance/result/failure after cancellation was requested, while new provider submissions remain blocked;
- a fenced acknowledgement requires the same worker's unexpired lease and either no provider-operation journal or a definitive `provider_failed` / `result_received` journal state;
- the worker does not locally cancel an in-flight provider call when cancellation is requested; it records the provider result and any available usage evidence before acknowledging;
- ambiguous provider outcomes remain `cancellation_pending` and are not refunded.

## Remaining recovery gap

The queue claim RPC does not yet reclaim expired `cancel_requested` leases. If a worker exits while the provider outcome is unknown, the job and credit hold remain safely pending, but automated reconciliation after lease expiry is not yet implemented. This is the next required step before considering the cancellation flow complete.

No real DeepSeek adapter or cancellation endpoint has been registered or verified. Do not infer provider cancellation support from this generic worker protocol.

## Required worker protocol

The heartbeat contract must become a structured state (or an equivalent explicit RPC result):
- `active`: caller still owns a valid running lease; renew it.
- `cancel_requested`: caller still owns the lease and the job is awaiting cancellation reconciliation; do not start new provider work.
- `lease_lost`: caller no longer owns a valid lease; stop all state mutations.
- `terminal`: another transaction already settled the job.

A cancellation acknowledgement RPC must:
1. Lock the generation job row.
2. Require `status = 'cancel_requested'`.
3. Require the exact `lease_owner` and a non-expired lease.
4. Require the provider operation to be definitively stopped or completed and reconciled.
5. Transition the job to `cancelled`, clear lease fields, and set completion metadata.
6. Release the held credit through the existing idempotent settlement helper in the same transaction.
7. Let the existing quota terminal-state trigger release quota reservations.

If the provider status is unknown, keep `cancel_requested`, lease/reconciliation ownership, credit hold, and quota reservations intact. Retry reconciliation; do not refund.

## Provider operation handling

- If cancellation is requested before provider submission is authorized, do not submit.
- If submission is in flight, wait for its response or reconcile by the stable idempotency key.
- If the provider offers a documented cancellation endpoint, use it only through an explicit provider adapter and require a definitive acknowledgement.
- If cancellation is unsupported, wait for the operation to finish or reach a definitive provider state. Record any provider usage/cost, discard the generated asset, then acknowledge cancellation.
- A local timeout, process shutdown, lost lease, or `asyncio.CancelledError` is not evidence that the provider stopped.
- Do not claim DeepSeek cancellation support until verified against current official provider documentation and implemented in a server-side adapter.

## Race and locking rules

- Cancellation request and successful completion must lock the same job row first.
- If completion commits first, the job is `succeeded`; a later cancellation request returns `already_terminal` and does not refund.
- If cancellation request commits first, completion must reject the `cancel_requested` job; only a valid worker acknowledgement can settle it as `cancelled`.
- Preserve the established lock order: job, then credit hold/wallet as applicable. Avoid any path that locks wallet/hold and then waits for the job.
- All settlement operations remain idempotent and transactional.

## Required tests before enabling the path

### SQL / database
- Owner-only cancellation and non-owner not-found behavior.
- Immediate queued and retry-wait cancellation with quota release and exactly one credit release.
- Repeated cancellation requests do not duplicate ledger entries.
- Running cancellation preserves lease, credit hold, and quota reservations.
- Completion wins race: no refund after success.
- Cancellation request wins race: completion cannot capture credits afterward.
- Acknowledgement requires matching worker and unexpired lease.
- Repeated acknowledgement is safe and does not duplicate refunds.
- Unknown provider status cannot be acknowledged.
- A settlement failure rolls back job status and quota/credit changes together.

### Worker
- Heartbeat distinguishes active, cancel-requested, lost lease, and terminal states.
- Cancellation during provider submission does not cancel the local coroutine and assume provider stop.
- Provider result received after cancellation is journaled and provider cost is recorded before cancellation acknowledgement.
- Unknown provider outcome leaves the job and credit hold pending reconciliation.
- A stale worker cannot acknowledge cancellation or mutate job state.
- Normal completion remains unchanged when no cancellation is requested.

## Rollout constraints

- Keep production `main` untouched until explicit approval.
- No production migration, deployment, billing activation, paid provider request, or provider switch without explicit approval.
- Keep the current provider choice unchanged; this protocol is provider-neutral and does not register a new provider adapter.
