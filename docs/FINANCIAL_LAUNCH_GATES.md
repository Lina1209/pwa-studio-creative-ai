# Financial protection and paid-launch gates

**Status: paid launch is blocked.** This document records the verified implementation boundary for the review branch. It is not evidence that production Supabase, Render, or provider accounts have been configured.

## Existing controls verified in source

- Server-owned pricing rules and signed, user-bound, expiring quotes. The browser does not choose the credit amount or provider-cost ceiling.
- Durable generation jobs, idempotency keys, provider-operation journal, and retry/recovery rules that defer ambiguous operations rather than blindly resubmitting.
- Credit ledger, credit holds, lot-aware allocation, source-separated grants, and wallet reconciliation RPCs.
- Provider-cost event ledger and per-job USD ceiling.
- Global provider daily budget and outstanding-exposure reservation in migration 0026. The policy is created disabled with both limits unset. Provider admission therefore fails closed until an operator configures real limits.
- AI request admission and daily limits for the existing synchronous AI endpoints.
- Append-only admin audit journal and scoped, expiring finance roles; compensation/refund actions use a request/approval workflow rather than directly mutating balances from a browser.
- Service-role credentials are used only by backend services; financial RPCs are not exposed to anon/authenticated roles.

## Important boundary: no customer payment rail

The repository currently has no verified production payment processor integration, checkout session lifecycle, signed payment webhook receiver, provider event deduplication, subscription renewal/cancellation integration, or provider-backed refund execution. The finance request workflow is an approval queue, not a payment gateway.

Consequences:
- Do not advertise paid checkout, automatic renewal, card payments, or instant refunds as available.
- Do not grant purchased credits based on a browser redirect, query parameter, client callback, screenshot, or user-submitted receipt.
- Do not enable subscription entitlements until a trusted server-side payment event is verified and durably deduplicated.
- Do not execute refunds until the payment provider confirms the original transaction and the refund operation is idempotently recorded.
- Keep paid generation disabled until real provider budget limits and the production database migration set are deliberately configured.

## Required financial invariants

1. A credit grant must have a trusted source, unique operation key, actor/system identity, and append-only ledger evidence.
2. A credit hold must be reserved atomically with job admission. A failed job may release only the user's credit hold according to the terminal-state policy; it must not erase provider-cost evidence.
3. A provider call must have a valid signed quote, immutable model/provider identity, a per-job USD ceiling, and a global budget reservation before the billable call.
4. Unknown provider charges retain their full reservation until operator reconciliation. Lease expiry, timeout, missing usage, or client disconnect are not proof of no charge.
5. Payment webhook handling (when implemented) must verify provider signature against the raw request body, enforce timestamp/replay limits, persist the provider event ID under a unique constraint, and update payment/entitlement/credit state in one database transaction or recoverable outbox workflow.
6. A duplicate webhook must be a no-op. Out-of-order events must not reactivate expired/cancelled entitlements or double-credit a wallet.
7. Refunds and manual credit compensation require separation of duties, explicit reason, approval, execution evidence, and reconciliation against the original transaction.
8. User-visible currency conversion is a quote/display feature until the payment provider confirms the actual settlement currency and amount. Internal credits are not cash, a deposit, or a redeemable monetary balance.
9. If the pricing catalog, wallet, audit journal, provider budget, or payment verification dependency is unavailable, the corresponding paid operation must fail closed.
10. Financial reporting must label estimated provider cost separately from invoice-reconciled actual cost. Never present estimates as provider invoices or net profit.

## Production rollout checklist

- [ ] Review and apply all migrations using the approved Supabase migration process; verify the live migration history and RLS/RPC grants.
- [ ] Configure global provider daily USD budget and outstanding exposure using real billing limits and the owner's explicitly approved risk amount. Never infer these amounts from subscription prices.
- [ ] Configure and verify provider-side spending caps/alerts in DeepSeek and Google consoles; application limits are not a substitute for provider billing controls.
- [ ] Reconcile controlled test calls against actual provider invoices, including retries, timeouts, unknown usage, and UTC day rollover.
- [ ] Approve a server-owned pricing catalog only after measured unit economics include provider, storage, compute, payment fees, FX, tax, refund, and support costs.
- [ ] Select a payment processor only after confirming merchant-country eligibility, KZT and foreign-currency settlement, fees, chargebacks, webhook signature scheme, refund support, and subscription support.
- [ ] Implement payment intent/order records, raw-body signature verification, unique provider event IDs, idempotent credit grants, subscription lifecycle, refund execution, and reconciliation.
- [ ] Add integration tests for forged signatures, replay, duplicate/out-of-order webhooks, partial refunds, chargebacks, renewal failures, cancellation, and concurrent wallet updates.
- [ ] Run a closed pilot with hard limits and reconcile every payment and provider cost daily before public paid launch.
- [ ] Obtain jurisdiction-specific review of consumer disclosures, tax, privacy, refund, and recurring-payment rules for each launch market.

## Current validation boundary

The latest source-reviewed branch head is `f8e9c6adc8d14162d933cd5f0b030ec1b2163a7d`. GitHub Actions runs 45080139912 and 45080134535 both completed successfully for that SHA, including backend tests and PostgreSQL migration/concurrency integration checks.

These are CI results against disposable test infrastructure. They do not prove that migrations were applied to live Supabase, that production budgets were configured, that provider invoices were reconciled, that payment processing exists, or that Render deployed this branch. The review branch remains separate from `main`.
