import httpx
from fastapi import HTTPException

from app.core.config import Settings


def _request(settings: Settings, method: str, table: str, *, params=None, payload=None):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Moderation storage is not configured.")
    base = settings.supabase_url.rstrip("/")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.request(
            method,
            f"{base}/rest/v1/{table}",
            headers=headers,
            params=params,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json() if response.content else []
    except httpx.HTTPStatusError as exc:
        # Do not return upstream details or credentials to the client.
        raise HTTPException(status_code=502, detail="Moderation storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Moderation storage is temporarily unavailable.") from exc


def create_user_report(settings: Settings, reporter_user_id: str, payload):
    rows = _request(
        settings,
        "POST",
        "user_reports",
        params={"select": "id,status,created_at"},
        payload={
            "reporter_user_id": reporter_user_id,
            "reported_user_id": payload.reported_user_id,
            "category": payload.category,
            "description": payload.description,
            "content_reference": payload.content_reference,
        },
    )
    if not rows:
        raise HTTPException(status_code=502, detail="The report could not be saved.")
    return rows[0]


def list_user_reports(settings: Settings):
    return _request(
        settings,
        "GET",
        "user_reports",
        params={
            "select": "id,reporter_user_id,reported_user_id,category,description,content_reference,status,created_at",
            "order": "created_at.desc",
            "limit": "100",
        },
    )
