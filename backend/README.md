# PWA Studio API

FastAPI backend for PWA Studio — Creative AI.

## Current endpoints

- `GET /` — service status
- `GET /api/health` — safe health/configuration status (never returns secrets)
- `GET /api/auth/me` — validates a Supabase access token and returns the server-assigned role
- `GET /api/admin/me` — owner-only authorization check
- `POST /api/chat` — authenticated Studio AI Companion; text safety checks run before provider calls
- `POST /api/prompts` — authenticated prompt generation; text safety checks run before provider calls

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

Set `AI_PROVIDER`, `AI_MODEL` and the matching provider secret in the host's environment settings. Supported initial providers: `openai`, `deepseek`, `anthropic` and `ollama`. Never expose provider keys in frontend code or health responses.

## AI usage metering (no credit deductions)

Successful `/api/chat` and `/api/prompts` calls now attempt to record token usage and provider-reported cost in the private `public.ai_usage` table. Prompt and response text are never stored. Cost remains NULL when LiteLLM/provider metadata does not supply a reliable value; no price is guessed. Telemetry is best-effort and does not block an AI response.

Before enabling this in production:

1. Review and manually apply `supabase/migrations/0003_ai_usage_metering.sql` in the intended Supabase project.
2. In Render, set `SUPABASE_SERVICE_ROLE_KEY` as a secret environment variable alongside `SUPABASE_URL`. Use the server-side service-role key from Supabase; never place it in frontend files, GitHub, or a client request.
3. After deployment, check `GET /api/health`. The boolean `usage_telemetry_configured` should be `true`; it does not expose credentials or prove a database write has succeeded.
4. Make one authenticated chat or prompt request, then inspect the new row in Supabase Table Editor. Verify user, endpoint, model, token counts and cost fields.

This phase only measures usage. It does not create wallets, deduct credits, charge users, or change plans. Rows are accessible only to the server-side service role because RLS is enabled and no client policies are granted.


### Administrator authorization boundary

The current administrator model is a server-side owner UUID allowlist, not a general role-management system. It supports one or more explicitly configured owner UUIDs, but does not yet provide delegated finance operators, permission scopes, two-person approval, or an administrator audit trail for financial adjustments. Service-role database RPCs remain server-only. Do not build a customer-facing credit-compensation or cash-refund action on top of `require_admin` until scoped financial permissions, immutable operator audit records, approval rules, and the selected credit-lot restoration/expiry policy are implemented and tested.
