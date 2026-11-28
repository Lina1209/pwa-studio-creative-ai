import httpx
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException

from app.core.config import Settings


def _request(settings: Settings, method: str, table: str, *, params=None, payload=None):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Moderation storage is not configured.")
    base = settings.supabase_url.rstrip("/")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    # Legacy service-role JWTs are also bearer tokens. New sb_secret keys are
    # valid as apikey but are not JWTs and must not be sent as Authorization.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
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


def _validated_uuid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"A valid {label} ID is required.") from exc


def create_user_report(settings: Settings, reporter_user_id: str, payload):
    reported_user_id = (
        _validated_uuid(payload.reported_user_id, "reported user")
        if payload.reported_user_id else None
    )
    rows = _request(
        settings,
        "POST",
        "user_reports",
        params={"select": "id,status,created_at"},
        payload={
            "reporter_user_id": reporter_user_id,
            "reported_user_id": reported_user_id,
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
            "select": "id,reporter_user_id,reported_user_id,category,description,content_reference,status,moderator_note,created_at",
            "order": "created_at.desc",
            "limit": "100",
        },
    )


def review_user_report(settings: Settings, report_id: str, moderator_id: str, payload):
    report_id = _validated_uuid(report_id, "report")
    result = _request(settings, "POST", "rpc/pwa_review_user_report",
        payload={"p_report_id": report_id, "p_moderator_id": moderator_id,
                 "p_status": payload.status, "p_moderator_note": payload.moderator_note})
    if not result:
        raise HTTPException(status_code=404, detail="Report not found.")
    return result


def create_suspension(settings: Settings, moderator_id: str, payload):
    target_user_id = _validated_uuid(payload.user_id, "user")
    result = _request(settings, "POST", "rpc/pwa_create_user_suspension",
        payload={"p_user_id": target_user_id, "p_moderator_id": moderator_id,
                 "p_reason": payload.reason, "p_scope": payload.scope,
                 "p_expires_at": payload.expires_at})
    if not result:
        raise HTTPException(status_code=502, detail="The restriction could not be created.")
    return result


def list_suspensions(settings: Settings):
    return _request(settings, "GET", "user_suspensions",
        params={"select": "id,user_id,reason,scope,created_by,expires_at,revoked_at,created_at",
                "order": "created_at.desc", "limit": "100"})


def revoke_suspension(settings: Settings, moderator_id: str, suspension_id: str):
    suspension_id = _validated_uuid(suspension_id, "suspension")
    result = _request(settings, "POST", "rpc/pwa_revoke_user_suspension",
        payload={"p_suspension_id": suspension_id, "p_moderator_id": moderator_id})
    if not result:
        raise HTTPException(status_code=404, detail="Active restriction not found.")
    return {"success": True, "id": suspension_id}


def ensure_user_not_suspended(settings: Settings, user_id: str, scope: str):
    # Both values feed directly into a PostgREST filter. Keep the scope closed
    # to the platform's known capabilities and canonicalize the signed user ID.
    if scope not in {"platform", "assistant", "community"}:
        raise HTTPException(status_code=500, detail="Suspension scope configuration is invalid.")
    user_id = _validated_uuid(user_id, "user")
    now = datetime.now(timezone.utc).isoformat()
    scope_filter = "eq.platform" if scope == "platform" else f"in.(platform,{scope})"
    rows = _request(settings, "GET", "user_suspensions",
        params={"select": "id,reason,expires_at",
                "user_id": f"eq.{user_id}",
                "scope": scope_filter,
                "revoked_at": "is.null",
                "or": f"(expires_at.is.null,expires_at.gt.{now})",
                "limit": "1"})
    if rows:
        raise HTTPException(status_code=403, detail="This account is temporarily restricted from using this feature.")
