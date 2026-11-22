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
- Overload returns HTTP 503 with `Retry-After`.
- Analytics has database-side per-token event limits and deduplication.

Not yet implemented:
- The AI semaphore is per process. It is not a distributed concurrency limit and does not enforce a per-user quota across multiple backend replicas.
- There is no shared per-user/per-IP request-rate limiter for chat and prompt generation.
- AI usage telemetry is best-effort. It is reporting, not a billing ledger or quota enforcement mechanism.
- The application does not yet enforce free/paid plan entitlements at every AI endpoint.

Before public AI launch, add shared server-side quota admission keyed by authenticated user and plan, with atomic usage reservation, expiry/reconciliation, and explicit fail-closed behavior when the quota service is unavailable. Add edge/CDN request limits and bot filtering as a second layer. Do not treat frontend quotas or the current in-process semaphore as security controls.

## Validation status

The PostgreSQL integration workflow run #1017 completed successfully for commit `7acd42740ab44597b4608d0f4c834c397aac0ab8`. It included the site analytics SQL test and the existing migration/concurrency checks.

Authentication role/UUID tests and pricing payload-size tests were added in later commits. Their CI result must be checked separately; run #1017 does not validate those later changes.

No production migrations, deployments, billing activation, or merge to `main` are performed as part of this review.
