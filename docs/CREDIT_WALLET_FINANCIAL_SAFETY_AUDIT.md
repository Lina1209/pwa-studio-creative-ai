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


## Follow-up review — 2026-11-25

Audited the current branch after adding migration 0015 and the disposable PostgreSQL gate. This remains a source-only review; no live Supabase or payment account was accessed.

### Updated finding status

| Finding | Current status | Evidence / remaining gate |
|---|---|---|
| C1 ambiguous provider result could be released | **Source-level mitigation added** | Forward-only migration 0015 makes ordinary settle/release reject ambiguous state and adds a service-role-only explicit provider-outcome resolver. Disposable PostgreSQL tests cover confirmed success/failure, replay, conflicting outcomes and direct-transition rejection. Still not live-applied; backend must only invoke resolver after authoritative provider evidence. |
| C2 RPC caller supplies user UUID | **Backend boundary still required** | Wallet adapter is internal and current public API has no wallet mutation route. Any future route must derive user UUID from verified StudioUser, never request JSON. Add route isolation tests before connecting generation. |
| C3 SQL grant source allowlist | **Source-level mitigation added** | Forward-only migration 0016 constrains grant sources in SQL to the same five-value allowlist as the Python adapter; disposable PostgreSQL test rejects an arbitrary source. Admin/payment authorization workflows remain separate and are not implemented. |
| C4 zero-token minimum capture | **Policy decision required** | min_credits applies even when measured token usage is zero. Distinguish fixed operation fee from token pricing; do not activate a rule until zero-usage behavior is approved and disclosed. |
| C5 usage telemetry durability | **Open** | record_ai_usage remains best-effort. The current /api/chat and /api/prompts paths do not persist a durable outbox before returning. Provider cost/usage can be lost during a storage outage. |
| C6 production pricing catalog | **Safely disabled** | AI_PRICING_CATALOG remains empty. No paid operation can obtain a quote through the production catalog. |

### Grants, admin adjustments, refunds and duplicate payment protection

- The SQL grant RPC is service-role-only and serializes on the user's wallet row. Its ledger unique index makes a repeated (user_id, source, source_reference) grant idempotent; reuse with a different amount is rejected.
- The Python adapter restricts grant sources, but the SQL function itself currently accepts arbitrary non-empty source strings. A future migration should enforce the same allowlist in SQL.
- No admin credit-grant API route, payment checkout, signed payment webhook, subscription lifecycle handler, or refund workflow was found in the reviewed backend routes. This is a useful fail-closed state, not a missing feature to activate prematurely.
- refund is currently an allowed adapter source label, not evidence of a verified payment refund. Do not call it from a client or treat it as payment authorization.
- A payment webhook must verify provider signature, event/account identity, currency and amount, then persist a unique provider event ID and map it to one grant reference. Duplicate, delayed, reordered, or replayed webhooks must not create extra credits.
- Admin adjustments need a separate audited operation with authenticated admin identity, mandatory reason, bounded amount, immutable audit record, and a distinct idempotency reference. Do not reuse a generic public grant route.
- A ledger grant is not itself proof of revenue. Revenue, refunds, provider fees, taxes, currency conversion and wallet credit issuance must be reported separately.

### Provider cost and balance reconciliation

- AI cost telemetry remains best-effort and records cost_source=litellm_response_cost when available. Treat this as LiteLLM-reported per-request cost, not invoice-confirmed settlement.
- Missing cost is NULL/unknown, never zero. Token totals alone do not represent image, video, music, voice, storage, egress or worker costs.
- There is no verified durable usage outbox, provider invoice import, global provider spend ceiling, or automated reconciliation dashboard in the current request path.
- Do not use the current ai_usage table as a financial ledger. Keep provider costs separate from customer credits and payment revenue.

### Release gates before any real money or credit activation

1. Reconcile live Supabase migration history, wallet tables, function definitions, RLS, ACLs and storage schema read-only.
2. Add SQL-side grant-source allowlist and a separate admin adjustment audit workflow in a forward-only migration; test it in disposable PostgreSQL.
3. Implement durable provider usage outbox with unique request/event IDs, bounded retries and dead-letter visibility.
4. Implement payment event inbox with signature verification, unique provider event IDs, replay/order handling and refund lifecycle before accepting checkout.
5. Define and approve daily/monthly pools, expiry, consumption order, currency conversion, taxes/fees, refund rules and zero-token pricing behavior.
6. Keep the production pricing catalog empty and wallet disconnected from generation until the above gates pass.
7. Run A/B account isolation, duplicate webhook, concurrent grant, duplicate refund, timeout, provider retry and ledger/balance reconciliation tests.
8. Only then present a separate release decision for live migration, billing activation and production deployment.

### Explicit non-actions in this follow-up

No live balance or ledger was changed. No credits were granted. No admin grant endpoint or payment webhook was added. No payment provider was connected. No pricing rule was enabled. No SQL was executed against Supabase, and no production deployment or PR merge was performed.
