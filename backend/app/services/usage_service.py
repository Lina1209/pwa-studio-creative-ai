import logging
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.ai_service import AIResult

logger = logging.getLogger(__name__)


def record_ai_usage(
    settings: Settings,
    *,
    user_id: str,
    request_id: UUID,
    endpoint: str,
    provider: str,
    result: AIResult,
) -> None:
    """Best-effort telemetry. Never stores prompts, replies, or credentials."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.info("AI usage telemetry skipped: server-side Supabase credentials are not configured.")
        return

    payload = {
        "request_id": str(request_id),
        "user_id": user_id,
        "endpoint": endpoint,
        "provider": provider,
        "model": result.actual_model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
        "cost_source": result.cost_source,
    }
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/ai_usage"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        # Do not log request/response bodies, user content, or secret values.
        logger.warning("AI usage telemetry write failed (%s).", type(exc).__name__)
