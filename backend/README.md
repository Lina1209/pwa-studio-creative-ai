# PWA Studio API

FastAPI backend for Studio AI Companion and Prompt Studio. The frontend remains a static PWA on GitHub Pages; this API must run on a separate Python host.

## Requirements

- Python 3.11+
- An API key for the selected AI provider (unless using a reachable local Ollama instance)

## Local setup

```bash
cd backend
python -m venv .venv
```

Activate the environment:

- Windows PowerShell: `.venv\\Scripts\\Activate.ps1`
- macOS/Linux: `source .venv/bin/activate`

Install and configure:

```bash
pip install -r requirements.txt
cp .env.example .env
```

On Windows, copy `.env.example` to `.env` manually if `cp` is unavailable. Edit `.env` locally and add your provider key. Never commit `.env`.

Run the API from the `backend` directory:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## Endpoints

- `GET /` — service status
- `GET /api/health` — safe health/configuration status (never returns secrets)
- `POST /api/chat` — Studio AI Companion
- `POST /api/prompts` — AI prompt generation

## Configuration

Copy `.env.example` to `.env`. Configure `AI_PROVIDER`, `AI_MODEL`, and the matching provider key. Supported provider values in this initial adapter: `openai`, `deepseek`, `anthropic` and `ollama`.

For production, set `CORS_ORIGINS` to the exact frontend origin(s), use HTTPS, configure secrets in the hosting provider's environment settings, and add authentication/rate limiting before opening the API to public use. Do not expose provider keys in frontend code or health responses.

## Current scope

This is the first backend foundation. It does not yet include video rendering, uploads, task queues, persistent projects or user accounts.
