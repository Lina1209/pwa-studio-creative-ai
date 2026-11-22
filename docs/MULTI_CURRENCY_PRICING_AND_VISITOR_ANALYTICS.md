# Multi-currency pricing and privacy-safe visitor analytics

**Status:** design and pricing calculation only. No payment processor, FX feed, analytics endpoint, counter UI, or billing activation is connected by this document.

**Base price list:** existing proposed KZT plans in `docs/PRICING_STRATEGY.md`. KZT remains the accounting/base currency; displayed checkout currencies are derived from the same plan IDs and never create separate plans or credit balances.

## 1. One plan, multiple display currencies

Use the following indicative conversion table for product/design review. It is based on the National Bank of Kazakhstan official rates for 2026-11-23: USD 455.00 KZT, EUR 498.77 KZT, RUB 5.56 KZT. The displayed estimates include a 2% FX safety buffer and are rounded upward to customer-friendly amounts. This 2% is a planning buffer, not a statement of any payment processor's actual conversion fee.

| Plan / pack | KZT base | USD indicative | EUR indicative | RUB indicative |
|---|---:|---:|---:|---:|
| Week Pass | 790 ₸ | $1.80 | €1.70 | ₽150 |
| Starter / month | 1,490 ₸ | $3.40 | €3.10 | ₽280 |
| Creator / month | 3,490 ₸ | $7.90 | €7.20 | ₽650 |
| Studio / month | 7,990 ₸ | $18.00 | €16.50 | ₽1,490 |
| Pro / month | 14,990 ₸ | $33.70 | €30.90 | ₽2,790 |
| Mini Top-up | 990 ₸ | $2.30 | €2.10 | ₽190 |
| Plus Top-up | 2,490 ₸ | $5.70 | €5.20 | ₽470 |
| Power Top-up | 4,990 ₸ | $11.40 | €10.50 | ₽940 |

The indicative prices are not yet final charge amounts. Before checkout is enabled, the selected payment processor must confirm merchant-country eligibility, presentment currencies, settlement currency, recurring-payment support, refund behavior, FX spread, processing fees, chargeback fees, tax handling and restricted-country rules. In particular, do not assume that a payment provider supports a Kazakhstan-based merchant merely because it can display USD/EUR prices. RUB must remain disabled until the chosen provider and legal/compliance review explicitly approve acceptance and settlement for the merchant and customer locations.

## 2. Conversion and price-lock rules

- Store each approved plan's canonical price as integer minor units in KZT and a stable plan/version ID.
- Fetch FX rates server-side from a trusted source. Record source, rate timestamp, base/quote currency, rate and rounding policy.
- Use decimal arithmetic only; never binary floating point for money.
- Conversion formula: `display_amount = round_up_to_price_step(base_kzt / fx_kzt_per_unit × (1 + configured_fx_buffer))`.
- The checkout quote is server-generated, signed, bound to plan/version, currency, amount, expiry and customer/payment session. Browser values are display-only.
- Lock the quoted amount for a short, explicit window (recommended 15 minutes); after expiry, recalculate and ask the user to confirm the changed amount.
- Never change an already confirmed payment amount. Refund using the payment processor's original-transaction refund mechanism and disclose any processor/bank currency behavior.
- If the FX source is stale, unavailable, malformed or inconsistent, do not silently fall back to a hard-coded rate. Show KZT or disable checkout until a valid quote is available.
- Keep customer-facing display currency separate from internal provider-cost currency (USD) and the accounting currency (KZT). Record all three where relevant.
- Reconcile provider invoices and payment settlements independently; FX gains/losses and payment fees must be included in unit economics.
- Do not geo-price by inferred income. Let users choose among currencies the payment processor genuinely supports for their checkout.

## 3. Currency rollout

**Initial:** KZT as canonical price and accounting currency.  
**Next:** USD and EUR presentment after processor eligibility and settlement are verified.  
**Later:** RUB only after legal/compliance and processor approval; then other currencies based on actual customer demand and supported payment methods.

The National Bank's official rate is an accounting/reference rate and is not necessarily the exact card/processor conversion rate. The payment processor's locked checkout quote and settlement report are authoritative for a transaction.

## 4. Visitor counter: what to count

Add a privacy-minimizing aggregate counter, not a public list of people.

Recommended metrics:
- `page_views`: page loads (not unique people);
- `unique_visitors_daily`: approximate unique browser sessions per UTC day, using a rotating, first-party pseudonymous identifier;
- `sessions`: sessions with a 30-minute inactivity timeout;
- optional aggregate `referrer_group`, `country_code` at coarse country level only, and page route category.

Do not collect raw IP addresses, full user-agent strings, precise location, email, auth IDs, prompt text, generated media names, or cross-site identifiers for analytics. Do not fingerprint devices. If a security layer transiently sees an IP address, do not copy it into analytics events; document retention separately for security logs.

### Counting behavior

- Count one page view on a real navigation/page load; avoid counting every SPA component redraw.
- For SPA route changes, emit one route view after successful navigation.
- Deduplicate repeated event delivery with an event UUID and database uniqueness constraint.
- A daily visitor token should rotate at UTC midnight and be stored first-party; avoid long-lived tracking.
- Exclude known health checks, bots/crawlers, preview builds, local development, and administrator/test traffic.
- Treat the number as an estimate, not verified human reach. Explain that cookie/storage restrictions and blockers can reduce counts.
- Show an aggregate total and a selected period (today / 7 days / 30 days) in an owner-only dashboard. Do not expose user-level records publicly.
- Add rate limits and server-side validation. Never accept client-supplied counts or allow a browser to increment arbitrary totals.

### Implementation boundary

The repository currently has no verified analytics ingestion route or live counter. The safe implementation requires a server endpoint plus a database migration with append-only/deduplicated events and aggregate queries, retention/deletion policy, bot filtering, rate limiting and owner-only reporting. Do not add a browser-only `localStorage` counter and call it real visits: it is per-device, trivially editable and cannot provide a trustworthy site-wide count.

## 5. Release checklist

- [ ] Choose a payment processor that onboards the actual merchant country and supports required presentment/settlement currencies.
- [ ] Verify recurring subscriptions, one-time top-ups, refunds, chargebacks, taxes and payout currency in a sandbox.
- [ ] Implement server-side FX provider, cache TTL, stale-rate fail-closed behavior and signed checkout quotes.
- [ ] Test amount rounding and quote expiry at FX boundary changes.
- [ ] Implement privacy notice, consent/legitimate-interest review where applicable, data minimization and retention.
- [ ] Implement visitor event ingestion, deduplication, bot filtering, rate limits and owner-only aggregate dashboard.
- [ ] Run payment sandbox and analytics abuse tests before production.

## Sources

- National Bank of Kazakhstan official exchange rates for 2026-11-23: https://nationalbank.kz/ru/exchangerates/ezhednevnye-oficialnye-rynochnye-kursy-valyut/
- National Bank explanation of official rates and cross-rates: https://nationalbank.kz/en/news/suraqtar
- Stripe Adaptive Pricing explanation (example of processor FX spread and currency presentation; not evidence that Stripe onboards a Kazakhstan merchant): https://support.stripe.com/questions/adaptive-pricing
- Stripe country/availability reference: https://stripe.com/money-management/availability
