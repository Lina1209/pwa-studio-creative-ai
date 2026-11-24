# Subscription, entitlement, and usage-metering foundation

Status: design-only. This document defines the next backend layer for PWA Studio. It does not activate subscriptions, prices, quotas, payment processing, or credit deductions.

## 1. Product principles

- One account has one subscription state and one shared credit wallet across all creative branches.
- A plan controls access and limits; credits pay for eligible metered operations. These are separate decisions.
- Provider cost telemetry measures what PWA Studio spends. It is not the user's credit balance.
- The backend is authoritative. The browser may display estimates and plan descriptions but cannot choose its plan, entitlement, price, balance, or final usage.
- Guest demo access is a separate, tightly bounded path and does not create a registered-user wallet.
- No plan or operation price is activated until real provider and infrastructure costs have been measured and approved.

## 2. Core concepts

### Plan definition

A versioned, immutable plan definition should contain:

- `plan_code` and `plan_version`;
- display name and public description;
- billing cadence (for example weekly or monthly), if applicable;
- feature entitlements;
- hard resource limits;
- included credit allowance and grant cadence, once approved;
- publication state and effective dates.

Publishing a changed plan creates a new version. Existing subscriptions retain the exact version they accepted.

### Subscription

A subscription record should contain:

- user ID derived from verified Supabase Auth;
- plan code and version;
- status: trialing, active, past_due, canceled, expired;
- billing-period start/end;
- cancellation/effective timestamps;
- nullable external customer/subscription references until a payment provider is selected;
- timestamps and an audit reference.

A browser request must never be able to set subscription status or assign a plan.

### Entitlements

Entitlements are server-evaluated capabilities, not merely UI switches. Initial categories:

- feature access: video, image, music, voice, advanced export, collaboration;
- resource ceilings: duration, resolution, file size, number of scenes, output length;
- concurrency: simultaneous renders/jobs;
- request limits: frequency and daily/monthly operation caps;
- storage limits: retained bytes and project count.

Each operation checks both feature access and resource ceilings before reserving credits or calling a provider. A plan may allow a feature while credits or usage limits still restrict the operation.

### Usage event

A usage event is an operational record, not a financial ledger entry. It should distinguish:

1. request received and authenticated;
2. entitlement and hard limits checked;
3. operation accepted or rejected;
4. provider/job reference created;
5. provider usage reported (tokens, seconds, images, audio duration, etc.);
6. measured or estimated provider cost and its source;
7. terminal state and reconciliation state.

Store safe metadata only. Do not store prompts, generated content, credentials, or unnecessary personal data in telemetry.

## 3. Proposed data model (not a migration)

### `plan_catalog`

Suggested fields: `plan_code`, `version`, `display_name`, `description`, `billing_period`, `entitlements` JSONB, `included_credits`, `grant_cadence`, `active`, `effective_from`, `effective_until`, timestamps.

Published versions should be immutable. Validate entitlement JSON against a server-owned schema before publishing.

### `user_subscriptions`

Suggested fields: `id`, `user_id`, `plan_code`, `plan_version`, `status`, `current_period_start`, `current_period_end`, `cancel_at_period_end`, `canceled_at`, nullable external payment references, timestamps.

Use a uniqueness/idempotency strategy appropriate to the chosen payment provider. Never treat an unverified client redirect as proof of payment.

### `usage_events`

Suggested fields: `id`, `request_id`, `user_id`, `operation_code`, `branch`, `status`, `provider`, `model`, `provider_reference`, `input_units`, `output_units`, `cost_amount`, `cost_currency`, `cost_source`, `reconciliation_status`, safe metadata, timestamps.

Keep this separate from `ai_usage` until a migration audit confirms the existing table's live shape and retention needs. Avoid duplicating data without a clear ownership boundary.

### Existing credit tables

The proposed `credit_wallets`, `credit_reservations`, and `credit_ledger` remain the credit-accounting layer. Subscription allowance grants should call the trusted grant RPC with a stable source reference derived from the subscription and billing period, so webhook retries cannot grant twice.

## 4. Operation decision sequence

1. Authenticate the user from the verified session.
2. Load the active subscription and immutable plan version server-side.
3. Evaluate feature entitlement and resource limits.
4. Apply independent abuse/frequency limits.
5. If the operation is credit-metered, resolve an approved server-owned price and reserve the maximum amount.
6. Record acceptance and a stable operation/request ID.
7. Call or enqueue the provider only after all required checks succeed.
8. Record trusted provider usage and cost telemetry.
9. Settle or release the reservation only when the provider outcome is known; ambiguous outcomes require reconciliation.
10. Return a user-safe result and update usage history.

No user credits are deducted in the current development stage. Build and validate telemetry first.

## 5. Guest demo versus registered users

Guest demo remains outside `user_subscriptions` and `credit_wallets`.

It needs independent server-side controls: short duration/output ceiling, low concurrency, per-session abuse controls, and a global spend budget. Guest identifiers must not be accepted as substitutes for authenticated user IDs. A guest-to-account conversion must not silently duplicate demo allowances.

Registered free users may later receive a defined free plan and allowance. Paid plans may use weekly or monthly billing periods. Exact prices, quotas, included credits, and limits remain undecided until measured economics and product policy are approved.

## 6. Operational and security requirements

- Never trust client-provided plan codes, subscription status, usage totals, provider cost, credit price, or wallet balance.
- Verify payment webhooks cryptographically and make every event idempotent before granting credits.
- Use server-side transactions for subscription-period changes and allowance grants.
- Preserve an audit trail for admin plan changes, manual grants, refunds, and corrections.
- Define expiry and rollover policy explicitly before implementing credit expiry.
- Keep API secrets and payment credentials server-side.
- Add provider budget alerts and global spend ceilings independent of user credits.
- Reconcile late callbacks, worker crashes, provider timeouts, and duplicate jobs.
- Retain only the minimum telemetry needed for billing correctness, support, abuse prevention, and cost analysis.

## 7. Rollout gates

1. Reconcile the duplicate `0005` migration versions, actual Supabase migration ledger, table definitions, RLS, and Storage policies.
2. Review wallet RPCs in disposable PostgreSQL/Supabase with concurrency and idempotency tests.
3. Add passive usage-cost telemetry and verify actual DeepSeek/provider usage reporting without credit deductions.
4. Measure infrastructure and provider cost by operation and branch.
5. Approve plan entitlements, credit conversion, operation pricing, and expiry/rollover policy.
6. Add subscription tables and verified payment integration as separate reviewed migrations.
7. Integrate one low-risk operation end-to-end, initially without charging users.
8. Only after reconciliation and explicit product approval, enable credit reservation and settlement for real operations.

## 8. Current implementation boundary

The repository has a source-only wallet/pricing foundation and best-effort `ai_usage` telemetry. The production pricing catalog is empty. There is no active subscription catalogue, payment provider, subscription webhook, approved plan allowance, or paid credit deduction. The design above is a blueprint, not a claim that these capabilities are already live.


## 9. Separate daily and monthly allowance model (product requirement, not activated)

The product should support two independently visible allowance windows where the selected plan defines both:

- **Daily allowance:** a recurring grant that becomes available at a clearly disclosed reset time.
- **Monthly allowance:** a separate grant tied to the subscription billing period or another explicitly defined calendar period.

Do not model these as one unexplained number. The account usage view should show daily remaining, monthly remaining, purchased/promotional balance (if any), and the next refresh time for each applicable pool. The backend must calculate eligibility and balances; browser clocks and client-supplied plan data are not authoritative.

Before implementation, the product owner must approve:
- which operation types consume the daily pool, monthly pool, or another balance;
- the deterministic consumption order when multiple pools can pay for one operation;
- whether unused daily credits expire at the next daily reset;
- whether unused monthly credits roll over, expire, or remain available after renewal/cancellation;
- the exact reset time and time-zone policy;
- how plan changes, failed payments, refunds, pauses and cancellation affect grants;
- how duplicate payment webhooks and scheduled grant retries are made idempotent.

The UI should warn before a limit is reached and explain which pool is exhausted. If the daily pool is empty but the monthly pool still has an eligible balance, the system should follow the published consumption rule rather than unexpectedly blocking or silently switching pools. Never promise a reset interval or carryover behavior until it is implemented and tested.

This requirement extends the existing independent request-rate limits and credit wallet design. Rate limits remain abuse controls; daily/monthly allowances are product entitlements; credits are spendable units; provider-cost telemetry remains a separate cost ledger.
