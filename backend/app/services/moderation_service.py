import httpx
from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


def _request(settings: Settings, method: str, table: str, *, params=None, payload=None):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Moderation storage is not configured.")
    base = settings.supabase_url.rstrip("/")
    headers = supabase_headers(settings)
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


def _validated_uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"A valid {field_name} is required.") from exc


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
            "select": "id,reporter_user_id,reported_user_id,category,description,content_reference,status,moderator_note,created_at",
            "order": "created_at.desc",
            "limit": "100",
        },
    )

def review_user_report(settings: Settings, report_id: str, moderator_id: str, payload):
    report_id = _validated_uuid(report_id, "report ID")
    rows = _request(settings, "PATCH", "user_reports",
        params={"id": f"eq.{report_id}", "select": "id,status,created_at,reporter_user_id,reported_user_id"},
        payload={"status": payload.status, "moderator_note": payload.moderator_note,
                 "reviewed_by": moderator_id, "reviewed_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(status_code=404, detail="Report not found.")
    _write_audit(settings, moderator_id, "report.reviewed", "report", report_id,
                 {"status": payload.status},
                 target_user_id=rows[0].get("reported_user_id"))
    return rows[0]


def create_suspension(settings: Settings, moderator_id: str, payload):
    rows = _request(settings, "POST", "user_suspensions",
        params={"select": "id,user_id,reason,scope,expires_at,created_at"},
        payload={"user_id": payload.user_id, "reason": payload.reason,
                 "scope": payload.scope, "created_by": moderator_id,
                 "expires_at": payload.expires_at})
    if not rows:
        raise HTTPException(status_code=502, detail="The restriction could not be created.")
    row = rows[0]
    _write_audit(settings, moderator_id, "user.suspended", "suspension", row["id"],
                 {"user_id": payload.user_id, "scope": payload.scope},
                 target_user_id=payload.user_id)
    return row


def list_suspensions(settings: Settings):
    return _request(settings, "GET", "user_suspensions",
        params={"select": "id,user_id,reason,scope,created_by,expires_at,revoked_at,created_at",
                "order": "created_at.desc", "limit": "100"})


def revoke_suspension(settings: Settings, moderator_id: str, suspension_id: str):
    suspension_id = _validated_uuid(suspension_id, "suspension ID")
    rows = _request(settings, "PATCH", "user_suspensions",
        params={"id": f"eq.{suspension_id}", "revoked_at": "is.null",
                "select": "id,user_id,scope"},
        payload={"revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_by": moderator_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Active restriction not found.")
    _write_audit(settings, moderator_id, "user.suspension_revoked", "suspension", suspension_id,
                 {"user_id": rows[0]["user_id"], "scope": rows[0]["scope"]},
                 target_user_id=rows[0]["user_id"])
    return {"success": True, "id": suspension_id}


def _write_audit(settings: Settings, actor_id: str, action: str, entity_type: str,
                 entity_id: str, metadata: dict, *, target_user_id: str | None = None):
    _request(settings, "POST", "admin_audit_log",
        payload={"actor_user_id": actor_id, "action": action,
                 "target_user_id": target_user_id,
                 "entity_type": entity_type, "entity_id": entity_id,
                 "metadata": metadata})


def ensure_user_not_suspended(settings: Settings, user_id: str, scope: str):
    now = datetime.now(timezone.utc).isoformat()
    rows = _request(settings, "GET", "user_suspensions",
        params={"select": "id,reason,expires_at",
                "user_id": f"eq.{user_id}",
                "scope": f"in.(platform,{scope})",
                "revoked_at": "is.null",
                "or": f"(expires_at.is.null,expires_at.gt.{now})",
                "limit": "1"})
    if rows:
        raise HTTPException(status_code=403, detail="This account is temporarily restricted from using this feature.")

def list_admin_audit_log(
    settings: Settings,
    *,
    page: int = 1,
    page_size: int = 50,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
):
    """Return a bounded, filtered page of append-only admin audit events."""
    filters = {
        "select": "id,actor_user_id,action,target_user_id,entity_type,entity_id,metadata,created_at",
        "order": "created_at.desc,id.desc",
        "offset": str((page - 1) * page_size),
        "limit": str(page_size + 1),
    }
    if actor_user_id is not None:
        filters["actor_user_id"] = f"eq.{_validated_uuid(actor_user_id, 'actor user ID')}"
    if target_user_id is not None:
        filters["target_user_id"] = f"eq.{_validated_uuid(target_user_id, 'target user ID')}"
    if action is not None:
        filters["action"] = f"eq.{action}"
    if entity_type is not None:
        filters["entity_type"] = f"eq.{entity_type}"

    rows = _request(settings, "GET", "admin_audit_log", params=filters)
    has_more = len(rows) > page_size
    return {
        "items": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }
