# AI budget reservation protocol (design draft)

**Status:** design-only SQL contract; not an executable migration.
**Branch:** `feature/character-library-foundation`.
**Do not apply to any Supabase project.** Numerical caps, currency conversion, credit pricing, and enforcement activation are intentionally undefined pending owner approval.

## Why this is a separate ledger

`public.ai_usage` is post-call telemetry. It cannot reserve funds before an external call, prevent concurrent overspend, or prove that a missing cost is zero. Keep it as the usage facts table; do not overload it as a wallet.

## Proposed records

### `ai_budget_policies` (singleton/global + optional user overrides)
- `scope`: `platform`, `provider`, or `user`.
- `scope_key`: stable key (e.g. provider name or verified auth UUID).
- `period_start`, `period_end`: explicit UTC accounting window.
- `limit_usd`: approved numeric cap; no default production value.
- `enabled`, `updated_at`, `updated_by`.
- Unique key on (scope, scope_key, period_start, period_end).

### `ai_budget_reservations`
- UUID primary key; `request_id` unique; verified `user_id`; endpoint/provider/model.
- Client idempotency key plus server-calculated request fingerprint.
- `reserved_usd`, nullable `actual_usd`, `status` (reserved/settled/released/unknown).
- `expires_at`, `created_at`, `settled_at`.
- Unique (user_id, idempotency_key). Reusing a key with a different fingerprint must return conflict, never create another reservation.

### `ai_budget_ledger` (append-only)
- UUID/idempotency key, reservation ID, user/provider, event type (reserve/settle/release/adjustment), signed amount, currency USD, timestamp, safe metadata.
- No prompt, completion, credential, or raw provider error fields.
- Corrections are compensating events, never updates/deletes to prior entries.

## Atomic reservation transaction

The backend calls a privileged RPC before `ask_ai`:
1. Validate the authenticated user UUID and server-known provider/model/endpoint. Ignore client-supplied owner, price, or budget.
2. Lock policy rows in a deterministic order: platform → provider → user. Use `SELECT ... FOR UPDATE` or equivalent serialization.
3. Find the idempotency record. If the same key and fingerprint already exist, return its current state; if the fingerprint differs, reject with conflict.
4. Calculate committed exposure as settled spend in the active window + live reservations. Expired reservations must not be blindly released if a provider request may still be running; transition them to `unknown` and reconcile before freeing exposure.
5. Check each applicable policy against committed exposure + requested worst-case reservation. If any limit would be exceeded, reject before external provider call.
6. Insert reservation and immutable reserve ledger event in the same transaction.
7. Return reservation ID and server-calculated maximum. The caller must not invoke the provider unless reservation is confirmed.

All requests that share a policy row serialize on the same lock. This is essential for a real global cap; process-local Python locks are insufficient.

## Settlement and failure semantics

- **Known success and known cost:** atomically append settlement event, mark reservation settled, release unused reserved amount from outstanding exposure.
- **Known failure with no provider charge:** append release event and mark released.
- **Timeout / connection loss / unknown provider outcome:** mark unknown and keep exposure reserved until reconciled; do not assume zero cost.
- **Provider response with null/untrusted cost:** retain conservative reserved amount or move to manual reconciliation; never settle at zero by default.
- **Retry:** each provider attempt must be explicitly represented and reserved, or one reservation must reserve the documented maximum for all allowed attempts. Current LiteLLM retry behavior must be accounted for; do not silently multiply attempts.
- **Overrun:** if validated actual cost exceeds reserved amount, record the actual cost and raise an alert/stop switch. Never hide the overrun or create a negative balance.
- **Expiry:** reservation cleanup is a reconciler, not a blind TTL delete. A request can outlive its HTTP client timeout.

## Fail-closed activation

A server-side setting may enable enforcement only after:
- policy rows exist for all applicable scopes;
- RPCs and lock behavior have passed isolated PostgreSQL concurrency tests;
- reservation service health is verified;
- both `/api/chat` and `/api/prompts` reserve before `ask_ai`;
- every success, exception, timeout, and cancellation path settles/releases or marks unknown;
- provider retry semantics are bounded and documented.

When enabled, RPC/database unavailability rejects paid AI calls before provider invocation. Before activation, this is a design, not a live spending control.

## Required PostgreSQL tests

1. 50 concurrent reservations against one small platform cap: accepted total exposure never exceeds cap.
2. 50 concurrent reservations for one user: same invariant for user cap.
3. Same idempotency key + same fingerprint: exactly one reservation and one reserve ledger event.
4. Same key + different fingerprint: conflict, no second reservation.
5. Simultaneous users sharing platform/provider policy: deterministic locking, no deadlock or overspend.
6. Settle/release repeated twice: idempotent, no duplicate ledger event.
7. Timeout/unknown state: exposure remains counted until reconciliation.
8. Null cost and provider retry: no zero-cost settlement.
9. Disabled global switch: all paid requests rejected before provider call.
10. RLS and grants: browser roles cannot read/write reservations, policies, or ledger; only backend service role can invoke RPC.

## Operator reconciliation workflow (design-only)

Reconciliation is a privileged, auditable workflow; it is not a TTL cleanup job and must never infer that an ambiguous request was free.

1. An authenticated operator requests a bounded page of metadata-only candidates. The query exposes reservation ID, user ID, provider/model, endpoint, amount, status, and timestamps only—never prompts, completions, credentials, or raw provider errors.
2. The operator verifies the reservation against authoritative provider usage/billing records or a documented provider request identifier. A timeout or missing telemetry row is not proof of no charge.
3. Record an immutable reconciliation decision with operator ID, timestamp, evidence reference (non-secret), decision, and a short allow-listed reason code. Do not store raw billing exports or personal content in the ledger.
4. If the provider confirms a charge, settle with the verified actual amount—even when it exceeds the original reservation. The overrun remains visible and must trigger an alert/stop review.
5. Release only when authoritative evidence confirms no provider charge. The release RPC must be idempotent and reject a reservation that has already settled.
6. If evidence is inconclusive, keep the reservation in `unknown`; add an audit note and revisit it later. Never auto-release unknown exposure.
7. Every decision must be read back and verified after the RPC. A failed write, stale operator view, or competing terminal transition must be surfaced as unresolved, not reported as success.

Before any route is implemented, require role/permission tests, CSRF/session protections appropriate to the admin surface, audit-log integrity tests, pagination limits, rate limits, and concurrent operator-versus-provider-settlement tests. The current RPC/store layer is only a backend foundation: no admin reconciliation endpoint, UI, scheduler, or production policy is enabled.

## Integration contract

Backend orchestration should be a small service with explicit operations:
- `reserve_ai_budget(...)` → reservation ID or safe 429/503 response.
- `settle_ai_budget(reservation_id, actual_cost, usage_metadata)`.
- `release_ai_budget(reservation_id, safe_reason)`.
- `mark_ai_budget_unknown(reservation_id, safe_reason)`.

Never place reserve/settle calls only in a best-effort telemetry helper. The reservation is a precondition; settlement is part of the request lifecycle. Keep telemetry separate so telemetry outages cannot bypass a budget gate.
