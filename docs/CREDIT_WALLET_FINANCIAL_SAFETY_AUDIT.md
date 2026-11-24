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


## Full server-side financial logic audit — 2026-11-25

This section records a source audit of the current backend and migrations. It is not a live Supabase audit and does not establish what has already been deployed.

### 1. Administrator credit grants

- `backend/app/services/credit_service.py` contains an internal `grant_credits` adapter. It validates UUID, positive bounded amount, a fixed source allowlist and reference length, then calls the service-role RPC.
- The adapter is not imported or called by `backend/app/main.py`. There is no `/admin/credits/grant` route, no request schema for an adjustment, and no end-to-end administrator grant workflow.
- `require_admin` is based on verified Supabase JWT identity and prefers configured immutable `OWNER_USER_ID`; it falls back to the email claim if no owner UUID is configured. Any future grant route must use this dependency and take actor identity from the verified `StudioUser`, not the request body.
- The adapter accepts `admin_adjustment` and `refund`, but that only describes accepted provenance labels. It does not authorize an admin or prove a refund happened.
- Existing moderation audit writes are separate REST requests from the primary moderation mutation. Reusing that pattern for money would allow a credit mutation to succeed while its audit write fails. A financial admin adjustment should be a single database transaction that writes both ledger event and immutable actor/reason audit evidence.

**Status: no admin grant endpoint exists; safe-by-absence. Do not expose the internal adapter directly.**

### 2. Ledger integrity and balance model

- `0013_unified_credit_wallet.sql` defines wallet balances, reservations and a credit ledger. Mutations are performed by SECURITY DEFINER RPCs; direct table privileges are revoked from anon/authenticated/service_role and service_role receives SELECT only. RPC execution is service-role-only.
- The ledger has a unique key for a grant `(user_id, source, source_reference)` and the grant RPC locks the wallet row, making same-user duplicate grants idempotent and rejecting a replay with a different amount. Migration 0016 adds a SQL-side source allowlist.
- Reservation idempotency is scoped by `(user_id, idempotency_key)`. Wallet-row locking serializes grants/reservations for one account. The disposable PostgreSQL suite covers concurrency and replay behavior.
- No database trigger currently enforces append-only semantics against privileged table owners. Application roles are denied direct writes by the migration ACLs, but a database owner/superuser can still alter history. This is an operational trust boundary, not cryptographic tamper evidence.
- Both wallet/reservation/ledger records reference `auth.users` with `ON DELETE CASCADE`. Deleting an auth user can therefore remove their wallet, reservations and financial ledger history. Before real-money launch, replace cascade deletion for financial records with retention-safe anonymization/soft deletion or a non-cascading account reference, subject to retention policy and a forward migration.
- The ledger is a credit accounting ledger, not a double-entry cash ledger. It does not represent revenue, payment fees, taxes, foreign exchange or cash refunds.

**Status: useful transactional wallet foundation; not yet production financial accounting.**

### 3. Duplicate payment protection and payment events

- No payment checkout route, provider webhook route, signature-verification code, subscription lifecycle handler, payment-event inbox, or provider transaction table was found in `backend/app/main.py`, backend services, or current migration inventory.
- Current grant idempotency prevents the same `(user_id, source, source_reference)` from being granted twice. It does not replace provider event deduplication, signature validation, event ordering, merchant/account validation, amount/currency verification, or a unique provider event ID.
- The current unique key is user-scoped. A provider event inbox should have a globally unique `(provider, provider_event_id)` constraint and persist the verified payload hash/status before granting credits. The inbox, grant, and event finalization should be transactional or safely recoverable.
- No payment provider has been selected in this code. Do not add provider-specific webhook behavior until the provider is chosen and its authoritative signature/event semantics are documented.

**Status: payment processing is absent and should remain disabled.**

### 4. Refund lifecycle

- There is no payment refund API, provider refund call, signed refund event handler, refund-request state machine, or reconciliation report.
- The wallet supports a source label `refund`, but no code verifies a payment refund or links a refund to an original payment/grant. A generic positive credit grant labelled `refund` is not a money refund and must not be used as one.
- A proper refund flow must preserve original payment/grant linkage, distinguish cash refunds from credit reversals, prevent refund amounts exceeding captured amounts, deduplicate provider refund events, and record partial/full refund states. Credit reversal after consumed credits needs an explicit debt/negative-balance policy rather than silently deleting historical credits.

**Status: no refund workflow exists.**

### 5. DeepSeek cost and usage reconciliation

- `ask_ai` captures provider/model, token counts and LiteLLM `_hidden_params.response_cost` when available. The cost source is explicitly labelled `litellm_response_cost`; it is not provider-invoice-confirmed spend.
- `/api/chat` and `/api/prompts` generate a new UUID only after the provider returns, then call `record_ai_usage`. The write is best-effort and catches failures. There is no durable outbox, pre-call request record, retry queue, dead-letter queue, or reconciliation job. Successful provider spend can therefore be absent from `ai_usage` after a database/network failure.
- `ai_usage.request_id` is unique, but because it is generated after provider completion it is not a durable pre-call idempotency key and cannot reconcile timeouts/retries by itself.
- `/admin/ai-usage` summary is explicitly current-page only. It is not a full-period cost total. `cost_usd IS NULL` is counted as unknown, not zero; preserve that distinction.
- The configured provider is DeepSeek by default in this deployment configuration, but code supports multiple providers. No DeepSeek invoice/billing import, account balance snapshot, top-up/refund reconciliation, provider request-ID join, or spend ceiling is implemented.
- No cost coverage exists for future image/video/music/voice generation, storage, egress or worker compute. Token-based chat telemetry must not be treated as total platform cost.

**Status: useful per-request estimated cost telemetry; not durable or invoice-reconciled provider accounting.**

### 6. Prioritized work before enabling real credits or payments

1. Decide retention/deletion rules and remove cascading deletion of financial ledger history.
2. Add a durable AI request/outbox lifecycle: create request ID before provider call; record pending/started/succeeded/failed/unknown; persist provider response IDs, token/cost data and retry state; reconcile unknown outcomes without double charging.
3. Add admin adjustments only as a dedicated transactional RPC + `require_admin` route, with actor UUID from verified auth, mandatory reason, bounded amount, idempotency key, and a single atomic audit/ledger write.
4. Select a payment provider, then implement a unique provider-event inbox, signature verification, amount/currency/account checks, duplicate/reorder/replay handling and transactional grants.
5. Design refund state machine and distinguish cash refunds from credit reversals.
6. Add provider invoice/balance import and daily reconciliation against LiteLLM request costs; report known cost, unknown cost, provider invoice spend, top-ups, refunds and variance separately.
7. Keep wallet disconnected from generation and production pricing catalog empty until all release gates are tested against reconciled live schema.

### Non-actions

No payment provider was selected or connected. No admin credit route was added. No credits, balances or refunds were changed. No live Supabase schema was read or written. No SQL migration was applied. No deployment or PR merge was performed.


## Financial-history retention mitigation — 2026-11-25

Added source-only forward migration `0017_preserve_credit_history_on_user_delete.sql`. It removes the three default foreign-key cascades from `credit_wallets.user_id`, `credit_reservations.user_id`, and `credit_ledger.user_id` to `auth.users(id)`. Financial rows retain the former account UUID as a pseudonymous reference instead of being automatically deleted when an Auth account is removed.

A disposable PostgreSQL integration test now grants credits, creates a reservation, deletes the corresponding Auth user, and asserts that the wallet balance, reservation and ledger events remain. The test fixture applies migrations 0011–0017 in sequence.

**Important limitations:** this is a preservation safeguard, not a complete retention/privacy policy. The retained UUID may remain personal data when linkable. Before live rollout, approve a retention period, legal basis, anonymization/pseudonymization process, support-access controls, and treatment of pending reservations. Account deletion must not silently destroy financial evidence, but it also must not become indefinite retention by default. Migration 0017 is source-only and has not been applied to live Supabase.


## Durable AI usage journal — 2026-11-25

Added source-only migration `0018_durable_ai_usage_outbox.sql` and wired both `/api/chat` and `/api/prompts` through a metadata-only request lifecycle:

1. Generate a stable UUID before contacting the provider.
2. Insert a `started` outbox row first. If that write fails, return HTTP 503 and do not start provider work.
3. On a completed provider response, persist `succeeded`, token counts and LiteLLM-reported cost metadata.
4. On provider errors/timeouts, persist `unknown` rather than assuming the operation was free.
5. Continue mirroring successful metadata to the legacy `ai_usage` table for existing reporting.

The outbox stores no prompts, generated text, credentials or raw provider error messages. It retains only account UUID, endpoint, provider/model, lifecycle status, token counts, optional cost metadata, safe error class and timestamps. Client roles have no table privileges; service_role receives SELECT/INSERT/UPDATE.

**Known remaining work:** no automated stale-`started` reconciler, retry worker, dead-letter dashboard, provider request-ID join, or invoice reconciliation exists yet. If writing the successful outcome fails after provider completion, the durable row remains `started` and must be reconciled; the user response is not discarded. A timeout remains `unknown` because the provider may have completed the operation. The existing `ai_usage` mirror remains best-effort and is not the authoritative journal.

The disposable PostgreSQL fixture now applies migrations 0011–0018 and tests outbox constraints, client-role isolation, and the account-history retention guard. Unit tests cover start-before-provider fail-closed behavior, successful metadata-only completion, and conservative unknown-state handling. CI results must be checked on the final branch head before calling the change verified.

Migration 0018 has not been applied to live Supabase. No production requests were run and no billing or credit deductions were enabled.


## Durable AI usage journal — reconciliation visibility

- The backend now exposes a read-only administrator endpoint at `GET /api/admin/ai-usage/reconciliation`.
- It lists bounded pages of `started` and `unknown` journal rows, with request/account identifiers, provider/model, timestamps, measured token/cost metadata, and age in seconds. It never returns prompts or generated responses.
- A `started` row older than the configurable `stale_after_minutes` threshold (default 15, maximum 1440) is labeled `stale_started` for manual review only. Age does not prove provider failure or absence of spend.
- Summary values are explicitly scoped to the current page. Known costs are summed separately; NULL costs remain counted as unknown and are never treated as zero.
- The endpoint does not mutate records, retry provider calls, release reservations, or settle charges. No authoritative DeepSeek invoice/request-ID matching is implemented; human/provider-side reconciliation remains required.
- The endpoint is protected by the existing verified `require_admin` dependency. The underlying outbox table must exist from migration 0018 and remain inaccessible to client roles.
- Migration 0018 remains source-only. Do not deploy this code until the live Supabase migration ledger, table definition, RLS and service-role grants have been reconciled and the migration is separately approved/applied.
