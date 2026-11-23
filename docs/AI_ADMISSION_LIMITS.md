# AI request admission limits

These limits are server-side operational safety ceilings for authenticated synchronous AI endpoints. They are not subscription entitlements, credit balances, provider-dollar budgets, or a promise of monthly included usage.

## Current default ceilings

- 10 requests per user per minute.
- 2 concurrent requests per user.
- 16 concurrent requests globally.
- 100 requests per user in a rolling 24-hour window.
- 2,000 requests globally in a rolling 24-hour window.
- 1,200 requests per user in a rolling 30-day window.

The limits are controlled by backend environment settings. The monthly setting is `AI_MAX_REQUESTS_PER_MONTH_PER_USER`; it defaults to 1,200. Lower or higher values must be chosen with provider capacity and cost controls in mind.

## Counting and retention

The admission reservation is created before the provider request. Every admitted attempt counts toward the rolling daily and monthly ceilings, including attempts later marked released after an error. This is intentionally conservative and prevents retries from bypassing cost controls. The 30-day counter is rolling, not calendar-month based.

Admission history is retained for up to 32 days so the rolling 30-day count can be enforced. Minute-window aggregates are still pruned after two days. The reservation table contains user UUID, endpoint, state, and timestamps; it does not store prompts or generated content.

## Important distinction

Customer Free/Creator/Studio Pro plan quotas still require a separate entitlement-resolution layer and must not be inferred from these global operational ceilings. Credit balances remain governed by the append-only credit ledger and atomic holds. Provider USD budget reservations remain a separate control. Guest access is not enabled by this change.

The new PostgreSQL RPC accepts the monthly ceiling as a server-supplied parameter and checks it under the existing per-user/global transaction locks before admitting a provider request. If the database admission check is unavailable, the AI request must fail closed.
