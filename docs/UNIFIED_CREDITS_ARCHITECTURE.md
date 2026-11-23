# Unified subscriptions and credits architecture

Status: source-only foundation in the open draft PR. No database migration has been applied, no payment integration or production setting has been changed, and no live wallet data exists.

## 1. Product model

PWA Studio uses one account-level entitlement and credit system shared by all creative branches:

- Mini Cinema and Video Studio
- Image Studio
- Music Studio
- Voice and audio tools
- Prompt Studio and AI Companion
- Future creative branches

A user should not need a separate balance for each workshop. Each operation is priced by a server-owned operation code and pricing version. The UI may show estimates, but only the backend decides eligibility, reserves credits, and settles usage.

## 2. Keep three concepts separate

1. Plan — subscription tier and its entitlements (feature access, included allowances, limits, renewal period).
2. Credits — spendable platform units granted by a plan, promotion, or purchase.
3. Provider cost telemetry — actual or estimated infrastructure/provider cost, recorded separately from credits.

Credits are an internal product unit, not a promise that one credit equals a fixed amount of currency. Do not expose provider API keys, raw provider costs, or mutable balances to the client.

## 3. Proposed data model

Names below are proposals; reconcile them with the live Supabase schema and migration ledger before creating or applying SQL.

### plan_catalog
Versioned server-owned plan definitions:
- plan_code, version, display_name, active
- billing_period (for example weekly or monthly)
- entitlements JSONB for feature access and non-credit limits
- included_credits and grant cadence
- timestamps

Published plan versions should be immutable. Editing a plan creates a new version so existing subscriptions retain an auditable agreement.

### user_subscriptions
- user_id, plan_code, plan_version
- status (trialing, active, past_due, canceled, expired)
- billing period start/end and cancellation timestamps
- external payment customer/subscription references, nullable until a payment provider is selected

The backend derives plan access from this record. Never accept a plan code, subscription status, or entitlement assertion from a browser request.

### credit_wallets
One row per user:
- user_id primary key
- available_credits
- reserved_credits
- updated_at

Both balances are non-negative and are changed only inside trusted database RPC transactions. The wallet is a fast transactional projection; the ledger is the audit source.

### credit_ledger
Append-only financial-style audit:
- id, user_id, event_type
- available_delta, reserved_delta
- reservation_id or grant_id, nullable as appropriate
- source and source_reference
- pricing_version, operation code, safe metadata
- created_at

Grant, reserve, capture, release/refund, expiry, and admin adjustment events must be traceable. Do not permit client-role writes or edits/deletes.

### credit_reservations
Idempotent operation lifecycle:
- id, user_id, idempotency_key (unique per user)
- operation_code, pricing_version
- reserved_credits, captured_credits
- status (reserved, settled, released, reconciliation_required)
- provider_request_reference, nullable
- timestamps and safe failure/reconciliation metadata

A reservation must be created before starting a paid provider operation. Repeating the same idempotency key with identical operation, pricing version, and amount returns the existing reservation; reusing it with different parameters is rejected.

### operation_pricing
Server-owned versioned credit prices:
- operation_code, pricing_version, active
- calculation mode and bounded parameters (for example per-second, per-image, per-token band)
- minimum and maximum reservation
- effective dates

Never accept a client-supplied credit price or arbitrary multiplier.

## 4. Atomic operation lifecycle

1. Authenticate the user and check suspension/account status.
2. Resolve plan and feature entitlement server-side.
3. Validate operation parameters and enforce hard resource ceilings.
4. Calculate a conservative maximum credit reservation using the active pricing version.
5. Call one database RPC that atomically checks available balance, moves credits from available to reserved, creates the reservation, and appends the ledger event.
6. Only after reservation succeeds, call the provider or enqueue the render job.
7. On confirmed success, calculate the final charge from trusted provider/job telemetry, capture that amount, and return unused reserved credits to available in one transaction.
8. On confirmed failure before work was accepted, release the full reservation.
9. If provider/job completion is ambiguous (timeout, lost callback, worker crash), keep the reservation in reconciliation_required; do not blindly refund and do not launch a duplicate paid operation.
10. Reconcile the job using provider reference/status and settle or release exactly once. Reconciliation-required reservations remain locked until a trusted outcome is known; they may then be settled or released through the same guarded lifecycle RPCs.

All settlement/release RPCs must be idempotent. A repeated callback must never double-charge or double-refund.

## 5. Important safeguards

- Database RPCs use trusted service_role access; RLS is enabled and browser roles cannot write wallets, ledger, subscriptions, reservations, or pricing.
- Validate the authenticated user UUID in the backend; never trust a user ID in the request body.
- Use unique constraints and transactional row locks for concurrent reservations.
- Enforce non-negative available/reserved balances with database constraints.
- Use stable idempotency keys for client retries and worker callbacks.
- Keep a separate audit trail for administrative grants/adjustments.
- Add daily/monthly operation limits independently of the wallet where product policy requires them.
- Provider timeouts and unknown usage are not zero-cost events.
- Bound input size, output tokens, duration, resolution, retries, and parallel jobs before calling providers.
- Keep the existing AI request-rate limiter as an abuse guard; it is not a substitute for credits or a monetary budget.
- Keep ai_usage as provider-cost/token telemetry. It is not the credit ledger and must not be used as a wallet balance.

## 6. Special handling by workflow

- Synchronous AI text/prompt calls: reserve the maximum allowed output/input band before provider invocation; settle using trusted usage when available. If usage/cost is missing, use the documented conservative pricing fallback or require reconciliation—never assume zero.
- Asynchronous video/image/music jobs: reserve before enqueueing; keep the reservation attached to a durable job ID; settle only after a confirmed terminal result.
- Guest demo: keep it outside the registered-user wallet. Apply strict server-side per-session/IP/device abuse controls, a short output/duration cap, and a global spend budget. Do not let guests create arbitrary paid jobs.
- Subscription allowance: grant included credits once per verified billing period with a unique grant reference. Webhook retries must not duplicate a grant.
- Cancellation/expiry: define whether unused purchased credits persist and whether plan-included credits expire; enforce the published policy through ledger events.

## 7. Rollout sequence

1. Inspect the live Supabase migration ledger, schema, RLS, and existing profile/account relationships. Resolve the duplicate 0005 migration history first. Do not infer applied migrations from filenames.
2. Agree the first plan catalogue and credit rules. Do not invent subscription prices, credit amounts, or module prices in code.
3. Add schema and atomic RPCs as source-only migrations with tests for concurrency, idempotency, insufficient balance, settlement, release, expiry, and ambiguous provider completion.
4. Add backend service functions and tests; retain existing endpoints until reservation/settlement is proven end-to-end.
5. Integrate one low-risk synchronous operation first (Prompt Studio), then AI Companion, then asynchronous media jobs.
6. Add subscription/payment webhooks only after selecting a payment provider and defining verified webhook/idempotency behavior.
7. Build the user-facing wallet, plan comparison, usage history, and admin audit views.
8. Reconcile provider costs and operational budgets before enabling paid traffic.

## 8. Current implementation boundary

The repository currently has:
- private ai_usage telemetry (best-effort writes, no credit debits);
- an atomic per-user/per-endpoint AI request-frequency limiter;
- a server-side AI output-token ceiling;
- a source-only migration draft (0013_unified_credit_wallet.sql) for wallet balances, append-only ledger entries, idempotent reservations, and atomic grant/reserve/settle/release/reconciliation RPCs;
- a backend credit-service adapter with strict UUID/amount/operation validation, a server-side grant-source allowlist, RPC response validation, and fail-closed storage handling; it now has orchestration helpers that reserve from a server-generated pricing quote and settle only a server-calculated capture amount, marking unpriceable/ambiguous usage for reconciliation;
- a server-owned AI pricing calculation engine with versioned rules, Decimal arithmetic, worst-case token-ceiling reservations, rounded-up capture calculations, and fail-closed behavior when a model has no approved price;
- unit tests for the credit adapter, quote-to-reservation orchestration, settlement/reconciliation behavior, and pricing engine. The production pricing catalog is intentionally empty, and neither service is connected to paid AI or media endpoints.

The wallet migration has not been applied, its SQL has not been executed against Supabase, and the RPCs are not yet called by application endpoints. The draft migration includes wallet-first row-lock ordering, parameter-consistent idempotency checks, service-role read-only ledger access (with writes performed by the definer RPCs), and an audited reconciliation-required transition. These are source-level safeguards only until PostgreSQL integration/concurrency tests are completed. Subscription entitlements, payment webhooks, approved production operation rates, persistent operation-pricing rows, frontend wallet views, and end-to-end paid-operation enforcement are not implemented. The pricing engine currently has no active production rules: no credit conversion factor, provider rates, or plan allowances have been invented or enabled. The credit foundation must not be described as active until migration history is reconciled, the SQL is reviewed and applied with authorization, backend integration is tested, and live behavior is verified.

No SQL from this design should be executed against production until the migration history and live schema are reconciled.
