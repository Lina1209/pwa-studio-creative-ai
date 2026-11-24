# Subscription, daily/monthly allowances, pricing, and rights — implementation checklist

Last reviewed: 2026-11-24  
Status: engineering readiness checklist; design/source review only. No live billing, pricing, quota, credit deduction, migration, or production behavior is enabled by this document.

## 1. Verified current state

| Capability | Evidence in the current branch | Actual status |
|---|---|---|
| Unified account wallet | `backend/app/services/credit_service.py`; `supabase/migrations/0013_unified_credit_wallet.sql`; credit-service tests | Backend adapter and source-only SQL foundation exist. Migration is not confirmed applied; application endpoints do not call the wallet. |
| Server-side price calculation | `backend/app/services/pricing_service.py`; `backend/tests/test_pricing_service.py` | Versioned Decimal-based quote/settlement engine exists. |
| Production operation prices | `AI_PRICING_CATALOG = {}` in `pricing_service.py` | Deliberately empty. No operation has an approved live price. |
| Reservation before generation | Credit-service orchestration helpers | Foundation exists; no verified user generation route is wired to it. |
| Daily allowance | Subscription design docs only | Not implemented. |
| Monthly allowance | Subscription design docs only | Not implemented. |
| Automatic allowance refresh | No verified scheduler/webhook/grant path for daily/monthly pools | Not implemented. |
| Payment/subscription checkout | No verified payment provider, checkout, verified webhook or subscription lifecycle | Not connected. |
| Plan-based quality limits | Entitlement design only; no complete server-side enforcement matrix | Not implemented end-to-end. |
| Rights and licensing | Product requirements/design notes only | No complete user-facing rights grant/consent/ledger workflow verified. |

The backend test suite currently covers the wallet adapter and pricing engine in isolation, including the intentionally empty production catalog. Passing those tests does not mean a wallet, payment, or quota system is live.

## 2. Architecture rules — keep these separate

1. **Plan entitlement** decides whether the account may use a feature and under which resource ceilings.
2. **Daily allowance** is a time-bounded included pool replenished on a defined daily schedule.
3. **Monthly allowance** is a separate included pool replenished on the plan's monthly cycle.
4. **Purchased credits** are a separate balance with an explicit expiry/refund policy.
5. **Promotional credits** are separately identified grants with a published expiry and restrictions.
6. **Reservations** temporarily hold estimated maximum cost while a job is running.
7. **Provider-cost telemetry** measures PWA Studio's cost; it is not the user's credit balance.
8. **Hard resource limits and abuse rate limits** protect infrastructure independently of all balances.

Do not collapse these into one number or let the browser choose a plan, balance, price, allowance, or usage result.

## 3. Daily and monthly pool policy to decide before coding

The product must approve the following policy values before activation:

- daily allowance amount per plan and eligible operation families;
- monthly allowance amount per plan;
- reset timezone and exact reset time;
- monthly cycle anchor (subscription anniversary vs calendar month);
- consumption order between daily, monthly, purchased, and promotional balances;
- whether unused daily/monthly allowance expires or rolls over, and any rollover cap;
- behavior on plan upgrade, downgrade, pause, cancellation, expiry, and failed payment;
- treatment of a job that was accepted before the allowance period ended;
- whether the allowance can be used for all creative branches or has branch-specific sub-limits;
- guest access and guest abuse budgets, separate from registered-user balances.

Recommended safety defaults for the eventual implementation (not activated policy): store all period boundaries as UTC instants with the account's declared billing timezone recorded; calculate boundaries server-side; never reset by client clock; use unique grant references so retries cannot double-credit; do not claw back a reservation for a job already accepted; and never silently move expired allowance into a paid-credit pool.

## 4. Price calculation and generation lifecycle

Required sequence for every metered operation:

1. Authenticate the account and derive the user ID server-side.
2. Resolve the immutable plan version and evaluate feature/resource entitlements.
3. Resolve the exact operation code, provider, model, quality preset and pricing version from server-owned configuration.
4. Estimate a conservative maximum cost from provider rates and bounded inputs (tokens, seconds, resolution, duration, concurrency, etc.).
5. Show the user the expected credit range and maximum reservation before a costly operation; obtain explicit confirmation where required.
6. Atomically reserve credits with an idempotency key before calling/enqueueing the provider.
7. Persist a durable job/request reference and provider reference.
8. On confirmed success, settle using trusted provider usage; release unused reserved credits.
9. On confirmed failure before billable work, release the reservation.
10. If provider outcome or usage is ambiguous, mark reconciliation required; do not guess, double-charge, or auto-refund before checking provider state.
11. Record a separate provider-cost telemetry event with source/quality (invoice-confirmed, provider-reported, or estimate).

A retry must reuse the same idempotency identity for the same logical request. A new user-requested generation is a new operation.

## 5. Plan quality matrix — implement only after provider capability audit

Plan tiers should describe actual supported service levels, not promises the current providers cannot meet. For each branch, define and enforce server-side:

- feature availability (text, image, video, music, voice, editing, export);
- model/provider choices that are approved for the tier;
- maximum input/output size and duration;
- video resolution/frame rate and image dimensions;
- audio sample rate/bitrate/channels and export formats;
- number of variants per generation;
- queue priority and concurrent job count;
- storage quota and retention;
- export watermark policy, if any;
- availability of advanced controls.

The free tier must retain a genuinely useful baseline and standard export. A paid tier may raise limits or unlock verified capabilities, but must not lock users out of their own original files or project drafts. UI labels are informational only: the backend must enforce every entitlement.

## 6. Rights, provenance, and consent

Keep these concepts distinct in data and UI:

- user-supplied source material and its ownership/permission;
- human-authored lyrics, scripts, prompts, recordings and edits;
- AI-generated output and the provider/model terms applicable at generation time;
- platform license and any commercial-use permission granted by the selected plan;
- copyright eligibility/protection, which is not guaranteed by a commercial-use license;
- publication permission and community visibility, which are always separate and opt-in.

For every generation, preserve provider, model, timestamp, accepted terms version, plan/entitlement version, source references and provenance metadata where available. Voice cloning or use of a recognizable person's voice requires documented consent and a safe revocation/deletion workflow. Do not claim exclusive ownership or copyright protection unless supported by the applicable law and provider contract. Terms need legal review before launch.

## 7. Required implementation work, in dependency order

### Gate A — reconcile data model (read-only first)
- Inspect live Supabase migration ledger, schema, RLS, grants, functions and existing credit-related objects.
- Compare the source-only `0013_unified_credit_wallet.sql` with the live state; do not apply it blindly.
- Resolve the duplicate migration prefix `0005` in the repository's migration history before future migration automation.
- Confirm service-role-only mutation paths and browser-role denial with disposable test accounts/database.

### Gate B — finish the wallet safely
- Add/verify transactional period pools and a ledger event for allowance grants, expiry and adjustments.
- Add atomic, idempotent daily/monthly grant functions and concurrency tests.
- Add reconciliation tooling for provider jobs with ambiguous outcomes.
- Add immutable plan/version and subscription records with server-side entitlement evaluation.
- Keep wallet endpoints unavailable until live schema and security tests pass.

### Gate C — connect one low-risk operation
- Start with a bounded text/prompt operation, not expensive video/music generation.
- Add endpoint-level entitlement → quote → reserve → provider → settle/release flow.
- Add idempotency, durable operation state, abuse limits and audit events.
- Verify failed calls, timeouts, retries, duplicate requests, provider mismatch and missing usage.

### Gate D — allowance and account experience
- Add separate daily/monthly balances, next refresh timestamps, expiry notices and operation cost preview.
- Add a clear history showing grants, reservations, captures, releases and expiry.
- Explain why an operation is unavailable and when it becomes available again.
- Do not interrupt an accepted in-flight job merely because a daily allowance resets or runs out.

### Gate E — billing and rights (last)
- Select a payment provider only after jurisdiction, currencies, fees, tax/refund rules and business requirements are reviewed.
- Verify webhook signatures, event ordering, replay protection and idempotent subscription changes.
- Do not activate checkout or real charges until legal, security, reconciliation and support procedures are approved.
- Publish plan terms, cancellation/refund rules, rights matrix and accepted-terms records before sale.

## 8. Minimum release test matrix

- A user cannot read or change another user's plan, allowances, wallet, ledger or reservations.
- Browser-supplied price, credit amount, plan code, quality, provider and usage are ignored/rejected.
- Two concurrent requests cannot spend the same available balance twice.
- Repeated daily/monthly grant events create exactly one grant.
- Timezone/DST/month-boundary tests do not grant early or twice.
- Upgrade/downgrade/cancel/failed-payment transitions follow the approved policy.
- A reservation cannot settle twice, exceed its reserved amount, or be settled with a different provider/model/pricing version.
- Confirmed failure releases the reservation; ambiguous outcome remains held for reconciliation.
- A completed job remains available after an allowance period ends.
- Provider cost and user credits remain separately auditable.
- Free-tier export and access to user originals work without paid entitlement.
- Rights and voice-consent terms are recorded against the generation that used them.

## 9. Explicit non-activation boundary

This checklist does not authorize or perform a live migration, database/RLS/grant change, payment-provider connection, checkout, real charge, credit grant/deduction, pricing activation, user publication, or production deployment. Those steps require a separate reviewed release decision after the preceding gates pass.
