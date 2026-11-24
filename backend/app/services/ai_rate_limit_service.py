import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


def consume_ai_request(settings: Settings, *, user_id: str, endpoint: str,
                       limit: int = 10, window_seconds: int = 60) -> bool:
    """Atomically consume one per-user AI request slot; fail closed on storage errors."""
    if endpoint not in {"chat", "prompts"}:
        raise ValueError("Unsupported AI endpoint.")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="AI usage protection is not configured.")
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/consume_ai_rate_limit"
    try:
        response = httpx.post(
            url,
            headers=supabase_headers(settings, prefer="return=representation"),
            json={
                "p_user_id": user_id,
                "p_endpoint": endpoint,
                "p_limit": limit,
                "p_window_seconds": window_seconds,
            },
            timeout=8.0,
        )
        response.raise_for_status()
        allowed = response.json()
        if type(allowed) is not bool:
            raise ValueError("AI rate-limit RPC returned an unexpected response.")
        return allowed
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=503, detail="AI usage protection is temporarily unavailable.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="AI usage protection is temporarily unavailable.") from exc
