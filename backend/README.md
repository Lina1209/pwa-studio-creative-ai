# PWA Studio API

FastAPI backend for PWA Studio — Creative AI.

## Current endpoints

- `GET /` — service status
- `GET /api/health` — safe health/configuration status (never returns secrets)
- `GET /api/auth/me` — validates a Supabase access token and returns the server-assigned role
- `GET /api/admin/me` — owner-only authorization check
- `POST /api/chat` — authenticated Studio AI Companion; text safety checks run before provider calls
- `POST /api/prompts` — authenticated prompt generation; text safety checks run before provider calls
- `POST /api/vision/analyze` — authenticated image analysis; disabled unless both `VISION_INPUT_ENABLED=true` and `VISION_PRIVACY_REVIEW_APPROVED=true` are explicitly configured

## Accounts and roles

Supabase Auth handles sign-up, sign-in, email verification and password recovery. The API validates Supabase JWTs against the project's JWKS endpoint and requires `role=authenticated` plus a UUID `sub`. Administrator access is granted only when that verified immutable Supabase Auth user UUID is present in the server-only comma-separated `OWNER_USER_IDS` environment variable. Email is display/contact data only and never grants administrator access. A missing or malformed allowlist grants no admin access. Do not put this setting in frontend code. Obtain the owner UUID from Supabase Authentication → Users and verify the account before adding it to the backend host's secret environment settings. Other signed-in users receive the creator role; the browser cannot request an admin role.

Guests can browse public studio pages and create temporary local drafts. Signed-in users have local-first Mini Movie Studio drafts synchronized directly with Supabase `public.projects` under owner-scoped RLS; this is not a FastAPI project CRUD API. Cross-device, conflict, and deletion behavior still require end-to-end verification.

## Supabase database and storage

- `supabase/migrations/0001_initial_schema.sql` is the original schema draft.
- `supabase/migrations/0002_storage_and_moderation.sql` creates private Storage buckets and per-user object-path policies only. It does **not** create moderation reports, bans, appeals, or an admin audit log.

Migration 0002 does not require an `is_admin()` helper: its Storage policies authorize access by checking that the first object-path segment equals `auth.uid()`. Review the migration against the live schema before running it. Storage object paths must begin with the authenticated user's UUID, for example `<user-uuid>/projects/<project-id>/...`.

Never put a Supabase service-role key or AI provider key in browser code. Only the public publishable key belongs in `supabase-config.js`.

## Safety status

The backend now requires authentication for AI chat and prompt generation and applies a first-layer text pattern guard. This is not a complete moderation system. It does not inspect generated images/video, detect every unsafe request, process reports, suspend accounts, or handle appeals. Those capabilities require dedicated moderation services, admin workflows, audit logging and testing before public launch.

## Local setup

Python 3.11+ is recommended.

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## AI configuration

Set `AI_PROVIDER`, `AI_MODEL` and the matching server-side secret. Only DeepSeek is supported. Google Gemini and all automatic provider fallback are disabled. Never expose provider keys in frontend code or health responses.

## AI usage metering and atomic USD admission

Synchronous `/api/chat`, `/api/prompts`, and Mini Movie Studio AI endpoints record token counts and a conservative server-side cost estimate in the private `public.ai_usage` table. Prompt and response text are never stored. When provider token usage is missing, the cost remains unknown.

Every synchronous AI call first reserves a worst-case USD amount in PostgreSQL. The global and per-provider daily limits are serialized in one transaction across backend replicas. The reservation estimate uses UTF-8 input bytes as a conservative input-token ceiling, the configured maximum output tokens, current server-maintained peak paid-tier prices, and a 25% safety margin. After a response, it settles from provider-reported token counts. If the request times out or usage is missing, the full reservation stays locked for operator reconciliation; it is never automatically released.

Initial limits seeded by `supabase/migrations/0050_sync_ai_provider_cost_reservations.sql`:
- DeepSeek: $1.00 per UTC day.
- Combined daily budget: $2.00 (the existing database policy retains an unused Gemini reservation row; the application no longer admits Gemini requests).
- Maximum outstanding reservations: $0.50.

The owner-only `GET /api/admin/ai/budget` endpoint and admin panel show settled estimates, outstanding reserves, unknown outcomes and remaining limits. This is not invoice-level billing reconciliation or a guaranteed provider billing cap. Keep separate spending limits in the DeepSeek console. Price assumptions must be updated when provider pricing changes. The estimator uses paid-tier rates even when a model is listed as Free Tier eligible; project eligibility is never assumed.

Before enabling this in production:

1. Review and manually apply migrations `0003_ai_usage_metering.sql` and `0050_sync_ai_provider_cost_reservations.sql` in the intended Supabase project, after checking the current migration history.
2. In Render, set `SUPABASE_SERVICE_ROLE_KEY` as a secret environment variable alongside `SUPABASE_URL`. Use the server-side service-role key from Supabase; never place it in frontend files, GitHub, or a client request.
3. If the cost tables or RPCs are unavailable, synchronous AI requests fail closed before contacting a provider. Verify the owner-only budget panel after applying the migration.
4. Reconcile actual invoices in provider consoles. Unknown reservations require an audited operator resolution; do not infer no-charge from a timeout or generic provider error.

The reservation ledger is separate from customer credits. It does not charge users, deduct credits, create revenue, or change subscription plans. RLS is enabled and no client policies are granted.


### Administrator authorization boundary

The current administrator model is a server-side owner UUID allowlist, not a general role-management system. It supports one or more explicitly configured owner UUIDs, but does not yet provide delegated finance operators, permission scopes, two-person approval, or an administrator audit trail for financial adjustments. Service-role database RPCs remain server-only. Do not build a customer-facing credit-compensation or cash-refund action on top of `require_admin` until scoped financial permissions, immutable operator audit records, approval rules, and the selected credit-lot restoration/expiry policy are implemented and tested.


## Durable generation worker runtime

The single-job executor and separately deployable polling loop are implemented as dependency-injected components:
- `app.services.generation_worker.GenerationWorker` processes one claimed image job.
- `app.services.generation_worker_runner.run_generation_worker_loop` claims durable work, applies idle polling/error backoff, and supports graceful process shutdown.
- `app.services.supabase_generation_worker_repository.SupabaseGenerationJobRepository` owns the service-role RPC boundary.

The runner does not construct or register providers, storage clients, or credentials. No real image-generation provider is registered yet. DeepSeek remains the only AI provider: its current API supports image input for vision analysis, but its model output modality is text, so it is not an image-generation API. The health endpoint reports image generation as unavailable until a real output-capable adapter is registered.

Keep `GENERATION_JOBS_ENABLED`, `GENERATION_JOB_WORKER_READY`, and `GENERATION_WORKER_RUNTIME_ENABLED` false until the provider, private storage adapter, dedicated worker entrypoint, deployment controls, and spend limits have passed separate review. See [generation worker runtime](../docs/architecture/generation-worker-runtime.md).


## Vision privacy release gate

Vision is off by default. The independent `VISION_PRIVACY_REVIEW_APPROVED` setting must remain `false` until the operator has verified the DeepSeek API-specific terms, processing/storage regions, retention and deletion commitments, published the approved PWA Studio privacy notice, implemented approved consent and withdrawal handling, and completed a legal review for every launch market (including Kazakhstan cross-border transfer and local-storage requirements where applicable). Setting `VISION_INPUT_ENABLED=true` alone is rejected by configuration validation. See `docs/privacy/PRIVACY_POLICY_DRAFT.md` and `docs/privacy/VISION_CONSENT_AND_DATA_FLOW.md`; both are internal drafts/specifications, not public legal notices.

## Privacy governance API

Authenticated endpoints:
- `POST /api/privacy/consent` — append a versioned consent acceptance/withdrawal event. The client cannot choose policy versions; the server supplies the configured published versions.
- `GET /api/privacy/consent` — returns the latest status per consent scope for the signed-in account.
- `POST /api/privacy/requests` — idempotently submits an access, export, correction or deletion request.
- `GET /api/privacy/requests` — lists only the signed-in account's request metadata.

The privacy request endpoints are **intake and status only**. They do not yet generate exports, erase accounts/files, purge provider data, or fulfill a legal request. Do not tell users that a request is completed until a separately reviewed operator fulfillment workflow actually performs and verifies it.

Every synchronous external AI request first writes a metadata-only `attempted` event to the append-only `ai_data_transfer_events` journal. The outcome is then recorded as `succeeded` or `unknown`; a journal outage before the provider call fails closed. The journal never stores prompt text, image bytes, data URLs, provider payloads, signed URLs or credentials. Vision attempts require the current accepted `vision_deepseek` consent event and a correlation ID.

Consent and transfer events are append-only. Retention periods and deletion/anonymization procedures for these records are not yet configured; do not claim that the audit metadata is automatically purged. See `docs/privacy/PRIVACY_POLICY_DRAFT.md` and `docs/privacy/VISION_CONSENT_AND_DATA_FLOW.md`.
