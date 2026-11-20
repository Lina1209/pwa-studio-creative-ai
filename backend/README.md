# PWA Studio API

FastAPI backend for PWA Studio — Creative AI.

## Current endpoints

- `GET /` — service status
- `GET /api/health` — safe health/configuration status (never returns secrets)
- `GET /api/auth/me` — validates a Supabase access token and returns the user's server-assigned role
- `GET /api/admin/me` — owner-only authorization check
- `POST /api/chat` — Studio AI Companion
- `POST /api/prompts` — AI prompt generation

## Accounts and database foundation

The account system uses **Supabase Auth + PostgreSQL**. Supabase handles sign-up, sign-in, email verification and password recovery; this API validates Supabase JWTs using the project's public JWKS endpoint. The owner role is assigned on the server only when the verified account email exactly matches `OWNER_EMAIL`. A visitor cannot request or set the admin role.

1. Create a Supabase project.
2. In Supabase SQL Editor, run `supabase/migrations/0001_initial_schema.sql`.
3. In Render environment settings, add `SUPABASE_URL` (Project URL) and `OWNER_EMAIL` (the email used by the platform owner account).
4. Keep Supabase service-role keys private. They must never be added to GitHub Pages or browser JavaScript.

The initial database includes profiles, projects, characters, scenes and media metadata. Row Level Security ensures authenticated users can access only rows whose `user_id` is their own. Actual browser sign-up/sign-in screens and persistent project APIs are the next integration step; the current static frontend has not yet been switched to account-required mode.

## Local setup

Python 3.11+ is recommended.

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On Windows, copy `.env.example` to `.env` manually if `cp` is unavailable.

## AI configuration

Set `AI_PROVIDER`, `AI_MODEL` and the matching provider secret in the host's environment settings. Supported initial providers: `openai`, `deepseek`, `anthropic` and `ollama`. Never expose provider keys in frontend code or health responses.

## Security status

The authentication verification endpoints and database/RLS schema are now prepared. The existing chat and prompt endpoints remain in their compatibility mode until the frontend registration/login flow is integrated; do not treat the app as ready for public multi-user launch yet.
