# Credit Wallet, Pricing, and AI Cost Safety Audit

Date: 2026-11-24  
Audited revision: `1910c2cf5a941da09e3bd731a7afc8c8fddebfad`  
Scope: backend source, tests, and source-only migration review. No live wallet, ledger, provider account, or payment data was accessed.

## Current safe rollout state

- The production AI pricing catalog is empty. No model or operation price is enabled by default.
- Pricing is calculated server-side with `Decimal`; browser-supplied prices and multipliers are not used.
- A quote reserves against configured maximum input/output token ceilings before provider use.
- The credit adapter uses server-only Supabase RPC calls and validates user UUIDs, integer amounts, operation identifiers, pricing versions, and idempotency-key lengths.
- Wallet reservation, settlement, release, grants, and reconciliation state changes are designed as transactional database functions.
- Wallet, reservation, and ledger tables enable RLS; direct client access is revoked. Service role has SELECT access, while balance mutation is intended to occur through narrowly scoped SECURITY DEFINER RPCs.
- The ledger is intended to be append-only: service role UPDATE/DELETE/TRUNCATE privileges are revoked.
- Reservation keys are unique per user; grant source references are protected by a unique partial index.
- Provider usage with missing token counts, mismatched model/provider, changed pricing version, or usage above the reserved ceiling is not silently priced. The adapter marks the reservation for reconciliation.
- Existing AI usage telemetry stores measured metadata only, not prompts or generated text. Unknown provider cost remains NULL rather than being fabricated.
- Telemetry writes are best-effort today; failed writes are logged without request bodies or secrets.

## Findings and recommendations

### C1 — Ambiguous provider outcomes can currently be released (critical before enabling credits)

The source-only migration allows `release_user_credit_reservation` to release both `reserved` and `reconciliation_required` reservations. A reconciliation-required reservation represents an uncertain provider outcome. Releasing it without a verified provider result could return credits even though a generation completed and incurred cost.

**Recommendation:** change the state machine so an ambiguous reservation cannot be released by the ordinary release RPC. It must remain reserved until an explicit, privileged reconciliation operation records verified provider outcome and then settles or releases it. Add tests for every transition and for repeated requests. Do not apply any migration until the live schema and migration ledger have been reconciled.

### C2 — Wallet RPCs trust the server-role caller to choose the user UUID (high priority)

The RPC functions are executable only by `service_role`, and the adapter obtains the UUID from the verified backend identity. This is a sound server boundary, but a service-role credential can operate on any UUID if a backend route accidentally passes the wrong one.

**Recommendation:** keep all credit RPC calls behind one audited service module; never expose wallet mutation endpoints directly to the browser. Every future route must derive the wallet owner from the verified token and must never accept `user_id` from the request body. Add cross-account route tests before wiring any operation to credits.

### C3 — Credit grant sources are checked in Python but not fully constrained in SQL (medium priority)

The adapter uses a fixed allowlist of grant sources. The SQL function itself accepts any non-empty source string. Because the function is service-role-only, this is not a client bypass, but database-level validation would provide defense in depth.

**Recommendation:** constrain grant source values in the RPC as well, and separately authorize admin adjustments and refunds through explicit trusted workflows.

### C4 — Zero-usage settlements still apply the configured minimum credit charge (medium priority)

The pricing service uses `min_credits` for the final capture. With a rule configured, a successful provider response reporting zero input and output tokens would still capture at least the minimum. This may be intentional for a fixed operation fee, but it should not be assumed to represent token cost.

**Recommendation:** explicitly distinguish fixed operation fees from token-based pricing. Define and approve zero-usage behavior before enabling any pricing rule.

### C5 — AI usage telemetry is not durable (high priority for financial reconciliation)

Current `record_ai_usage` is best-effort. A temporary Supabase outage can lose a successful generation's usage record. The repository contains an outbox design document, but the reviewed live request path does not yet provide durable delivery.

**Recommendation:** add a durable server-side usage outbox with stable request IDs, bounded retries, deduplication, and dead-letter/reconciliation visibility. Do not store prompts or generated content in the outbox.

### C6 — Pricing catalog is deliberately empty (correct safety gate)

No DeepSeek rates, credit conversion factor, provider cost multiplier, plan allowance, or operation price is enabled. The existing cost telemetry label `litellm_response_cost` is a calculated estimate, not an invoice-confirmed provider charge.

**Recommendation:** keep all paid/credit-backed generation disabled until verified provider pricing, infrastructure overhead, exchange-rate policy (if needed), free-tier allowances, and a user-facing price estimate are approved.

## Required tests before integration

- Concurrent reservation attempts cannot overspend one wallet.
- Same idempotency key and same parameters replay the same reservation; changed parameters are rejected.
- A reservation cannot be settled or released twice with inconsistent results.
- An ambiguous provider result cannot be refunded by ordinary release.
- A verified reconciliation can settle or release exactly once.
- A failed generation releases credits only when the provider outcome is definitively known to be no work/no charge.
- A/B users cannot read or mutate each other's wallet, reservation, or ledger through any API route.
- Client payloads cannot choose owner ID, credit amount, price, pricing version, grant source, or settlement amount.
- Ledger events and wallet deltas remain consistent under concurrent operations.
- Usage outbox retries are idempotent and never store user prompts or generated content.

## Explicit non-actions

- No credit pricing was enabled.
- No credit wallet or payment endpoint was connected to generation routes.
- No wallet balance, credit, or ledger entry was created or changed.
- No payment provider, subscription, or billing flow was activated.
- No SQL or migration was executed.
- No production deployment or PR merge was performed.
