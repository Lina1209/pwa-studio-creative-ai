# Privacy-safe visitor analytics design

Status: design only; not deployed. Reviewed 2026-11-24.

## Goals and non-goals

Provide the owner with honest operational counts for visits, sessions, studio opens, and authenticated active accounts. Do not build advertising profiles, behavioral fingerprints, content surveillance, or a billing ledger.

This design does not authorize a production rollout. Before implementation, reconcile the live Supabase migration ledger, RLS, grants, retention capability, and applicable notice/consent requirements.

## Metric definitions

- **Page visit event:** one accepted `page_view` event. This is an event count, not a person count.
- **Session:** one random, first-party session identifier within a defined short lifetime (proposed 30 minutes idle, maximum 24 hours). A session is not proof of a unique human.
- **Unique sessions:** distinct accepted session IDs within the selected period. Report separately from people/accounts.
- **Registered accounts:** distinct Auth user IDs with a valid profile row, subject to verified profile-trigger completeness. Use account creation time, not page views.
- **Active accounts:** distinct authenticated account IDs that performed an allowlisted meaningful event in the period. Exclude passive polling and background health checks.
- **Studio opens:** accepted allowlisted studio-open events; not equivalent to generated media or completed work.

Never label session totals as “unique visitors” or account activity as visits.

## Minimal event contract

Proposed event fields:
- `event_id`: client-generated UUID for retry deduplication; never an identity.
- `session_id`: cryptographically random UUID, first-party and short-lived.
- `event_name`: strict allowlist, initially `page_view`, `studio_open`, `project_open`.
- `occurred_at`: optional client timestamp for diagnostics only; not authoritative.
- `route_key`: allowlisted coarse route enum only (for example `home`, `cinema`, `music`, `prompt_studio`); never arbitrary URL/query/hash.
- `schema_version`: integer.

Server derives authenticated `user_id` from the verified bearer token. Anonymous events have no user ID. Server assigns `received_at` and reporting date. Ignore or reject client-supplied user IDs, role, IP, user-agent, referrer, titles, project IDs, prompt text, message text, media paths, and arbitrary metadata.

## Collection and privacy controls

- Use a random first-party session identifier stored with a short expiration; do not use IP/device fingerprinting or third-party tracking.
- Do not persist IP addresses or full user-agent strings in analytics.
- Do not collect content, prompts, generated outputs, filenames, email addresses, or exact location.
- Publish a clear analytics notice and obtain consent where required before enabling optional anonymous analytics.
- Provide a documented retention period and automated deletion/aggregation policy before launch.
- Apply strict event-name and route-key allowlists, small request/body limits, per-session and per-account rate limits, and server-side timestamping.
- Exclude admin polling, health checks, static assets, retries, and background refresh from visit metrics.
- Never use analytics events to charge credits or determine subscription entitlements.

## Idempotency and storage

A future event table should have a unique constraint on `event_id` and store only the allowlisted fields above. Duplicate retries must return an accepted/duplicate outcome without incrementing aggregates twice. Use server-side daily aggregation keyed by date, event name, coarse route, and—where permitted—pseudonymous session/account identifiers. Raw event retention must be shorter than aggregate retention.

Do not use a browser local counter as a source of truth. Do not expose service-role credentials. Ingestion should use a server-side transaction or RPC that validates identity, event schema, rate limits, and idempotency together.

## Admin reporting

Owner-only endpoint, bounded date range and page size, returning separately:
- accepted event count;
- distinct session count;
- distinct authenticated account count;
- registered-account count from verified profile records;
- studio-open counts;
- data-quality state and coverage window.

Every metric must state its definition and period. Missing event coverage must be shown as “нет данных/неполный период”, never extrapolated into fabricated all-time totals. Use timezone-aware UTC storage and an explicit display timezone.

## Required tests before release

1. Anonymous event cannot set or spoof a user ID.
2. Authenticated event identity comes only from verified token claims.
3. Duplicate event IDs do not increment counts twice, including concurrent retries.
4. Unknown event names, route keys, oversized payloads, invalid UUIDs, and stale timestamps are rejected or safely normalized.
5. Rate limits apply per session and authenticated account.
6. No IP, full user-agent, referrer, content, or arbitrary metadata is persisted.
7. Anonymous and authenticated session counts remain distinct.
8. Admin report returns 401 unauthenticated and 403 for creators; filters and date ranges are bounded.
9. Retention deletion is tested and does not remove permitted aggregates.
10. No analytics request is triggered for background polling, health checks, or static assets.

## Rollout gates

1. Confirm live schema/migration state and privacy notice/consent obligations.
2. Approve exact retention and anonymous analytics behavior.
3. Implement migration and transactional ingestion only on the feature branch.
4. Add unit and integration tests; verify duplicate and concurrent event handling.
5. Add owner-only dashboard labels that distinguish events, sessions, and accounts.
6. Keep feature disabled until production schema review and explicit release approval.

No migration, event collector, cookie/local-storage session tracker, live database query, or production setting change is included in this design document.
