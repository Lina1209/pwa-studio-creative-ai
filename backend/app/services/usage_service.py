import logging
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.ai_service import AIResult
from app.services.supabase_rest import supabase_headers

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
    headers = supabase_headers(settings, prefer="return=minimal")
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        # Do not log request/response bodies, user content, or secret values.
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        logger.warning(
            "AI usage telemetry write failed: error_type=%s status_code=%s",
            type(exc).__name__,
            status_code,
        )



def list_admin_ai_usage(
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 50,
    user_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
):
    """Return bounded, metadata-only AI usage events for the admin workspace."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="AI usage storage is not configured.")

    params = {
        "select": "request_id,user_id,endpoint,provider,model,input_tokens,output_tokens,total_tokens,cost_usd,cost_source,created_at",
        "order": "created_at.desc,request_id.desc",
        "offset": str((page - 1) * page_size),
        "limit": str(page_size + 1),
    }
    if user_id:
        params["user_id"] = f"eq.{user_id}"
    if provider:
        params["provider"] = f"eq.{provider}"
    if endpoint:
        params["endpoint"] = f"eq.{endpoint}"

    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/ai_usage"
    headers = supabase_headers(settings)
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            rows = response.json()
    except httpx.HTTPStatusError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="AI usage storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="AI usage storage is temporarily unavailable.") from exc

    has_more = len(rows) > page_size
    return {
        "items": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "summary_scope": "current_page",
        "summary": {
            "requests": len(rows[:page_size]),
            "input_tokens": sum(row.get("input_tokens") or 0 for row in rows[:page_size]),
            "output_tokens": sum(row.get("output_tokens") or 0 for row in rows[:page_size]),
            "total_tokens": sum(row.get("total_tokens") or 0 for row in rows[:page_size]),
            "known_cost_usd": str(sum(
                (Decimal(str(row["cost_usd"])) for row in rows[:page_size] if row.get("cost_usd") is not None),
                Decimal("0"),
            )),
            "unknown_cost_requests": sum(1 for row in rows[:page_size] if row.get("cost_usd") is None),
        },
    }
