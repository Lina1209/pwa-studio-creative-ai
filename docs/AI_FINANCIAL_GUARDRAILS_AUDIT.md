# AI financial guardrails — implementation audit

**Status:** audit/design only; no credit debits or budget enforcement are enabled by this document.
**Branch:** `feature/character-library-foundation`.
**Production:** no production database, deployment, provider key, or paid provider configuration was changed.

## Verified current behavior

- `POST /api/chat` and `POST /api/prompts` authenticate the caller and apply a process-local burst limiter before calling the AI provider.
- The limiter is defense-in-depth only: it is not shared across workers or instances.
- Chat input is bounded to 24,000 aggregate characters; individual message/history limits also apply.
- Provider output is capped at 2,048 tokens, timeout is 90 seconds, and one retry is allowed.
- Successful provider usage is recorded to `public.ai_usage` after the provider call. The telemetry row contains request/user/endpoint/provider/model/token/cost metadata, not prompt or response text.
- Telemetry is best-effort. If its write fails, the provider operation has already happened and the call is not rolled back.
- A missing provider cost value is represented as null. Therefore telemetry alone cannot be treated as a hard spending control.
- The existing `ai_usage` table is an append-only usage record for this purpose; it is not a wallet, reservation ledger, or atomic budget gate.
- The credit system specification explicitly remains a proposal. Public plan quotas and the monetary value of a credit are not approved.

## Financial risk

The current implementation limits request frequency and response size, but it does **not** reserve or enforce a per-user or platform-wide monetary budget before calling DeepSeek. It also cannot guarantee a strict cross-worker rate limit. A provider call may incur cost even if the subsequent telemetry write fails.

Do not describe current usage metering as budget enforcement, credit charging, or guaranteed spend prevention.

## Safe target architecture

1. **Atomic preflight reservation:** a database transaction/RPC checks active policy, user allowance, and global provider allowance, then creates a uniquely keyed reservation before the external call.
2. **Idempotency:** one reservation per request idempotency key; duplicate submissions return the existing reservation and cannot reserve twice.
3. **Bounded exposure:** reserve a conservative maximum based on model, bounded input, and output-token cap. Do not rely on client-supplied price or token counts.
4. **Settlement:** after the provider response, settle against validated actual usage/cost. Release unused reservation. If actual cost is unknown, apply an explicit conservative policy rather than silently treating it as zero.
5. **Failure handling:** release or retain reservation according to provider outcome and retry semantics. Provider retries must not accidentally multiply exposure.
6. **Global kill switch:** server-side switch can stop paid AI calls when the platform budget is exhausted or accounting becomes unavailable.
7. **Shared rate limiting:** move strict burst enforcement to an atomic shared store/database RPC; keep the in-process limiter only as an additional defense.
8. **Auditability:** immutable reservation/settlement/release events, bounded retention, and admin-only reporting. Never log prompts, completions, API keys, or raw provider errors.
9. **Fail-closed policy:** when the reservation service is unavailable, paid calls should be rejected once budget enforcement is formally enabled. Before that rollout, do not claim the budget is protected.

## Rollout gates

- No public prices, credit exchange rate, plan quota, or hard USD cap is inferred from the draft credit specification.
- Product owner must approve numerical per-user and platform limits after unit-economics review.
- Implement and test the SQL RPC/migration in isolated CI only; do not run it against the live Supabase project from this work.
- Test concurrent reservations, duplicate idempotency keys, reservation expiry, provider timeout/unknown outcome, null cost, over-reservation, settlement, release, and global stop.
- Verify that both chat and prompt routes reserve before `ask_ai`, and that every exit path settles/releases safely.
- Do not enable enforcement or deploy until migration review, CI, and explicit production rollout approval are complete.

## Next implementation sequence

A. Specify reservation/ledger tables and transaction boundaries, including lock ordering and idempotency.
B. Add an isolated database migration and SQL concurrency tests.
C. Add a backend budget service with unit tests and no default production cap until approved.
D. Wire both AI routes through reserve → provider → settle/release.
E. Add admin-only budget visibility and a global stop control.
F. Re-run the full backend, PostgreSQL, and browser CI suites.

This audit records the verified boundary between current protections and the future financial-control system; it does not activate billing or alter provider selection.

## New isolated implementation artifacts (feature branch only)

- `supabase/migrations/0022_ai_budget_reservations.sql` defines private policy, reservation, and append-only ledger tables plus privileged reserve/settle/unknown/release RPCs.
- The global transaction advisory lock serializes reservation decisions across users and workers. An active platform policy is mandatory; provider/user policies are optional additional caps.
- The global control row is seeded with `enforcement_enabled=false` and `kill_switch_enabled=true`. No monetary policy rows or numerical limits are seeded.
- The reserve RPC returns whether it created a new reservation. A duplicate request must not call the provider again.
- `backend/app/services/ai_budget_store.py` is a server-only Supabase RPC adapter. It is not wired to routes.
- `backend/app/services/ai_budget.py` remains a provider-independent orchestration contract. It requires a trusted server-calculated reservation amount; the pure estimator contract now exists, but is not yet wired to a tokenizer, rate card, or routes.
- Disposable CI applies the migration and runs SQL checks. The current SQL suite verifies sequential cap enforcement and transaction-level invariants; it does NOT yet launch concurrent sessions, so race behavior still needs a true multi-session stress test. A global advisory transaction lock serializes reserve calls in the RPC.
- No live Supabase migration was run. No production setting, provider key, route, or billing flow was changed.

### Versioned cost-estimator contract

- Added `backend/app/services/ai_cost_estimator.py`, a pure Decimal-based upper-bound calculator requiring a server-supplied, versioned provider/model rate card and trusted token upper bounds.
- It rejects missing/invalid prices, non-finite rates, invalid token counts, and counts beyond the reviewed rate-card ceilings; rounding is upward to ledger precision.
- No real DeepSeek or other provider prices are embedded. No tokenizer, rate card, numerical spending cap, or route integration is configured. The estimator cannot be used safely until a trusted tokenizer/bound source and reviewed rate card are supplied.

### Reconciliation and exposure refinements

- Added `mark_stale_ai_budget_reservations_unknown`: a bounded, service-role-only RPC that converts old `reserved` rows to `unknown` and appends a ledger event. It never releases a stale reservation.
- Added `list_ai_budget_reconciliation_candidates`: a bounded, service-role-only read RPC exposing only reservation metadata needed for manual/provider reconciliation; it returns no prompt or response content.
- Added a backend adapter method for invoking that RPC; no scheduler or background worker is configured.
- Exposure aggregation now filters by both the active policy's scope and its period. Platform policies aggregate all provider/user reservations in-period; provider and user policies aggregate only matching rows.
- SQL tests now check disabled-by-default behavior, browser-role privilege denial, idempotency, settlement, unknown exposure, confirmed no-charge release, stale reservation reconciliation, and that a provider cost overrun is recorded at its actual amount rather than clipped to the reservation.
- The corrected migration/reconciliation SQL integration run completed successfully in CI (`46095350845`). The versioned estimator, its validation tests, and documentation workflows also completed successfully (`46095400515`, `46095412636`, `46095418512`).

## Remaining blockers before route integration

1. Add and pass a true multi-session PostgreSQL concurrency test; current SQL contract tests are sequential.
2. Select a trusted server-side tokenizer or conservative token-bound method, then review and version actual model input/output prices including retry exposure.
3. Add an authenticated, audited reconciliation operator workflow for reservations stranded in `reserved` or `unknown`; no scheduler exists, and ambiguous provider requests must never be TTL-released.
4. Decide how to authenticate and audit policy/control changes and how to handle user deletion under ledger retention requirements.
5. Only after numerical limits are approved, implement route integration and an explicit staged rollout.
