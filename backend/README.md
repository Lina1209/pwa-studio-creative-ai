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

Supabase Auth handles sign-up, sign-in, email verification and password recovery. The API validates Supabase JWTs against the project's JWKS endpoint. The owner role is assigned server-side only when the verified account email exactly matches `OWNER_EMAIL`; other signed-in accounts receive the creator role. The browser cannot request an admin role.

Guests can browse public studio pages and create temporary local drafts. Signed-in users have local-first Mini Movie Studio drafts synchronized directly with Supabase `public.projects` under owner-scoped RLS; this is not a FastAPI project CRUD API. Cross-device, conflict, and deletion behavior still require end-to-end verification.

## Supabase database and storage

- `supabase/migrations/0001_initial_schema.sql` is the original schema draft.
- `supabase/migrations/0002_storage_and_moderation.sql` creates private Storage buckets and per-user object-path policies only. It does **not** create moderation reports, bans, appeals, or an admin audit log.

The second migration expects the existing `public.is_admin()` helper used by the current Supabase project. Review the migration against the live schema before running it. Storage object paths must begin with the authenticated user's UUID, for example `<user-uuid>/projects/<project-id>/...`.

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
