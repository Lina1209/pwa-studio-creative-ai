import httpx
from datetime import datetime, timezone
from fastapi import HTTPException

from app.core.config import Settings


def _request(settings: Settings, method: str, *, params=None, payload=None):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Notification storage is not configured.")
    base = settings.supabase_url.rstrip("/")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    try:
        response = httpx.request(method, f"{base}/rest/v1/user_notifications",
            headers=headers, params=params, json=payload, timeout=10.0)
        response.raise_for_status()
        return response.json() if response.content else []
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="Notification storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Notification storage is temporarily unavailable.") from exc


def create_notification(settings: Settings, user_id: str, notification_type: str,
                        title: str, body: str, data: dict | None = None):
    rows = _request(settings, "POST", params={"select": "id,user_id,type,title,body,data,read_at,created_at"},
        payload={"user_id": user_id, "type": notification_type, "title": title,
                 "body": body, "data": data or {}})
    if not rows:
        raise HTTPException(status_code=502, detail="Notification could not be created.")
    return rows[0]


def list_notifications(settings: Settings, user_id: str):
    return _request(settings, "GET", params={
        "select": "id,type,title,body,data,read_at,created_at",
        "user_id": f"eq.{user_id}", "order": "created_at.desc", "limit": "50"})


def mark_notification_read(settings: Settings, user_id: str, notification_id: str):
    rows = _request(settings, "PATCH", params={
        "id": f"eq.{notification_id}", "user_id": f"eq.{user_id}",
        "select": "id,read_at"},
        payload={"read_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return rows[0]


def mark_all_notifications_read(settings: Settings, user_id: str):
    rows = _request(settings, "PATCH", params={
        "user_id": f"eq.{user_id}", "read_at": "is.null", "select": "id"},
        payload={"read_at": datetime.now(timezone.utc).isoformat()})
    return {"updated": len(rows)}
