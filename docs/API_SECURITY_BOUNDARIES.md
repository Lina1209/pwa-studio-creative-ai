# Backend API security boundaries

Last reviewed: 2026-11-23  
Scope: source-level review of the FastAPI backend. This document does not claim a production deployment or external penetration test.

## Authentication

Protected endpoints use Supabase JWT verification in `backend/app/services/auth.py`:

- Tokens are verified against the project's Supabase JWKS endpoint.
- Accepted signing algorithms are ES256 and RS256.
- Audience must be `authenticated`; issuer must match the configured Supabase Auth issuer.
- `exp`, `sub`, `iss`, and `aud` are required.
- The JWT role must be exactly `authenticated`; service-role, anon, and other project tokens are rejected.
- The subject must be a valid UUID before it becomes a `StudioUser`.
- Admin access is separately checked by `require_admin`.

The current owner mapping is based on a server-side `OWNER_EMAIL` comparison with the signed email claim. Keep this value server-only and protected. A future hardening step should prefer a stable owner UUID allowlist, because email addresses can change.

## Endpoint-level input bounds

Pydantic request models reject unknown fields and apply explicit bounds:

| Endpoint | Input bounds |
| --- | --- |
| `POST /api/chat` | message: 1–12,000 characters |
| `POST /api/prompts` | idea: 1–8,000; purpose: max 80; language: max 40; style: max 300 |
| `POST /api/scenes/{scene_id}/image-jobs` | prompt: max 8,000; negative prompt: max 2,000; dimensions: 256–2,048 and multiples of 64 |
| `POST /api/pricing/quotes` | identity fields bounded; quantity 1–10,000; JSON request snapshot max 32 KiB |

Pricing quote snapshots are serialized with strict JSON handling before canonical hashing. Non-finite numeric values and payloads larger than 32 KiB are rejected.

## Account isolation and privileged operations

- Generation job status lookup is scoped by both the authenticated user UUID and job UUID.
- A missing or another user's job returns the same 404 response.
- Admin analytics and financial reporting use the separate `require_admin` dependency.
- Service-role credentials remain server-side; the frontend must never receive them.
- Generation submission remains fail-closed unless both the feature flag and worker readiness flag are enabled.

## Resource protection: current limits and remaining work

Implemented:
- AI provider calls use a bounded in-process semaphore, a bounded queue wait, provider timeout, a small retry ceiling, and a configurable maximum output-token limit (`AI_MAX_OUTPUT_TOKENS`, default 2,048; allowed range 1–8,192).
- `chat` and `prompts` also reserve capacity through PostgreSQL before contacting the AI provider. Limits are per authenticated user: 10 admitted requests/minute and 2 concurrent requests by default; operators can tune them through `AI_MAX_REQUESTS_PER_MINUTE_PER_USER` (1–120) and `AI_MAX_CONCURRENT_REQUESTS_PER_USER` (1–16). A shared global concurrency ceiling defaults to 16 across all accounts and replicas (`AI_MAX_GLOBAL_CONCURRENT_REQUESTS`, 1–128).
- Admission is shared across backend replicas, uses service-role-only RPCs, and fails closed if Supabase admission storage is unavailable. Reservations are finalized on success/failure; stale reservations stop counting toward concurrency after ten minutes.
- Overload returns HTTP 503 with `Retry-After`.
- Analytics has database-side per-token event limits and deduplication.

Not yet implemented:
- The in-process AI semaphore remains a second, per-process safety layer; the PostgreSQL gate supplies distributed per-user request/concurrency limits for chat and prompt generation.
- There is not yet a shared per-IP/CDN limit for chat and prompt generation.
- AI usage telemetry is best-effort. It is reporting, not a billing ledger or quota enforcement mechanism.
- The application does not yet enforce free/paid plan entitlements at every AI endpoint.

Before public AI launch, extend admission to plan-based monthly credit/usage entitlements with atomic ledger reservations and reconciliation, and add edge/CDN request limits and bot filtering as a second layer. The current per-minute gate is not a subscription quota or a billing ledger. Do not treat frontend quotas as security controls.

## Validation status

The PostgreSQL integration workflow run #1017 completed successfully for commit `7acd42740ab44597b4608d0f4c834c397aac0ab8`. It included the site analytics SQL test and the existing migration/concurrency checks.

Authentication role/UUID tests and pricing payload-size tests were added in later commits. Their CI result must be checked separately; run #1017 does not validate those later changes.

Migration `0029_ai_request_admission.sql` must be applied before deploying backend code that depends on it; until both are installed, AI routes fail closed with HTTP 503. The migration is included in the disposable PostgreSQL integration harness. No production migrations, deployments, billing activation, or merge to `main` are performed as part of this review.
