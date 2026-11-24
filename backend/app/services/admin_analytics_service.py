from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


MAX_ANALYTICS_WINDOW = timedelta(days=31)


def get_admin_analytics_summary(
    settings: Settings,
    *,
    start_at: datetime,
    end_at: datetime,
) -> dict:
    """Return aggregate-only operational counts from the trusted database RPC."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Admin analytics storage is not configured.")
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Analytics dates must include a timezone.")
    start_utc = start_at.astimezone(timezone.utc)
    end_utc = end_at.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if start_utc >= end_utc or end_utc > now + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="The analytics date range is invalid.")
    if end_utc - start_utc > MAX_ANALYTICS_WINDOW:
        raise HTTPException(status_code=422, detail="The analytics date range cannot exceed 31 days.")

    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/admin_analytics_summary"
    payload = {
        "p_start_at": start_utc.isoformat(),
        "p_end_at": end_utc.isoformat(),
    }
    try:
        response = httpx.post(url, json=payload, headers=supabase_headers(settings), timeout=10.0)
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {404, 400, 401, 403}:
            raise HTTPException(
                status_code=503,
                detail="Admin analytics database function is not installed or is not available to the server.",
            ) from exc
        raise HTTPException(status_code=502, detail="Admin analytics storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Admin analytics storage is temporarily unavailable.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Admin analytics storage returned an invalid response.") from exc

    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Admin analytics storage returned an invalid response.")
    expected = {"registered_accounts", "accounts_with_project_updates", "accounts_with_successful_ai_usage"}
    if not expected.issubset(result) or any(
        not isinstance(result.get(key), int) or result[key] < 0 for key in expected
    ):
        raise HTTPException(status_code=502, detail="Admin analytics storage returned an invalid summary.")
    return {
        "period": {"start_at": start_utc.isoformat(), "end_at": end_utc.isoformat()},
        "metrics": {
            "registered_accounts": result["registered_accounts"],
            "accounts_with_project_updates": result["accounts_with_project_updates"],
            "accounts_with_successful_ai_usage": result["accounts_with_successful_ai_usage"],
        },
        "definitions": {
            "registered_accounts": "Профили, созданные в выбранном периоде; полнота зависит от триггера регистрации.",
            "accounts_with_project_updates": "Уникальные владельцы проектов, обновлённых в периоде; это не все активные аккаунты.",
            "accounts_with_successful_ai_usage": "Уникальные аккаунты с записанными успешными AI-запросами; телеметрия может быть неполной.",
        },
        "data_quality": {
            "scope": "aggregate_only",
            "profile_completeness_verified": False,
            "ai_telemetry_is_best_effort": True,
            "visitors_and_sessions_included": False,
            "note": "Это не счётчик посетителей и не полный показатель активности. Live-схема и полнота данных требуют отдельной проверки.",
        },
    }
