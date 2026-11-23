import re
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.core.config import Settings


def _request(settings: Settings, method: str, *, params=None, payload=None, prefer="return=representation"):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Profile storage is not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    try:
        response = httpx.request(
            method, f"{settings.supabase_url.rstrip('/')}/rest/v1/user_profiles",
            headers=headers, params=params, json=payload, timeout=12.0,
        )
        response.raise_for_status()
        return response.json() if response.content else []
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409 or (exc.response.status_code == 400 and "23505" in exc.response.text):
            raise HTTPException(status_code=409, detail="This username is already in use.") from exc
        raise HTTPException(status_code=502, detail="Profile storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Profile storage is temporarily unavailable.") from exc


def _valid_user_id(user_id: str) -> str:
    try:
        return str(UUID(user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="A valid account ID is required.") from exc


def _public(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "bio": row.get("bio") or "",
        "avatar_path": row.get("avatar_path"),
        "updated_at": row.get("updated_at"),
    }


def get_own_profile(settings: Settings, user_id: str) -> dict:
    uid = _valid_user_id(user_id)
    rows = _request(settings, "GET", params={
        "select": "user_id,username,display_name,bio,visibility,show_in_directory,avatar_path,updated_at",
        "user_id": f"eq.{uid}", "limit": "1",
    })
    if rows:
        return rows[0]
    username = "user_" + uid.replace("-", "")[:12]
    rows = _request(settings, "POST", payload={
        "user_id": uid, "username": username, "display_name": "Новый участник",
        "bio": "", "visibility": "public", "show_in_directory": True,
    })
    if rows:
        return rows[0]
    raise HTTPException(status_code=502, detail="Could not initialize your profile.")


def update_own_profile(settings: Settings, user_id: str, changes: dict) -> dict:
    uid = _valid_user_id(user_id)
    get_own_profile(settings, uid)
    payload = dict(changes)
    if "username" in payload:
        payload["username"] = str(payload["username"]).strip().lower()
        if not re.fullmatch(r"[a-z0-9_.]{3,24}", payload["username"]):
            raise HTTPException(status_code=422, detail="Username must be 3–24 characters: a-z, 0-9, underscore or dot.")
    if "display_name" in payload:
        payload["display_name"] = str(payload["display_name"]).strip()
        if not 2 <= len(payload["display_name"]) <= 40:
            raise HTTPException(status_code=422, detail="Display name must contain 2–40 characters.")
    if "bio" in payload:
        payload["bio"] = str(payload["bio"]).strip()
        if len(payload["bio"]) > 500:
            raise HTTPException(status_code=422, detail="Bio must be no longer than 500 characters.")
    if "visibility" in payload and payload["visibility"] not in {"public", "private"}:
        raise HTTPException(status_code=422, detail="Invalid profile visibility.")
    if "show_in_directory" in payload and not isinstance(payload["show_in_directory"], bool):
        raise HTTPException(status_code=422, detail="Directory visibility must be true or false.")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        rows = _request(settings, "PATCH", params={
            "user_id": f"eq.{uid}",
            "select": "user_id,username,display_name,bio,visibility,show_in_directory,avatar_path,updated_at",
        }, payload=payload)
    except HTTPException as exc:
        if exc.status_code == 502 and "rejected" in str(exc.detail).lower():
            raise HTTPException(status_code=409, detail="This username may already be in use.") from exc
        raise
    if not rows:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return rows[0]


def search_public_profiles(settings: Settings, query: str, current_user_id: str) -> list[dict]:
    uid = _valid_user_id(current_user_id)
    term = query.strip().lower()
    if len(term) < 2:
        raise HTTPException(status_code=422, detail="Enter at least 2 characters to search.")
    if len(term) > 40 or not re.fullmatch(r"[a-z0-9а-яё_. -]+", term, flags=re.IGNORECASE):
        raise HTTPException(status_code=422, detail="Search contains unsupported characters.")
    # Search only fields explicitly intended for public discovery.
    safe = term.replace("%", "").replace("*", "")
    rows = _request(settings, "GET", params={
        "select": "user_id,username,display_name,bio,avatar_path,updated_at",
        "visibility": "eq.public", "show_in_directory": "eq.true",
        "or": f"(username.ilike.*{safe}*,display_name.ilike.*{safe}*)",
        "user_id": f"neq.{uid}", "order": "username.asc", "limit": "30",
    })
    return [_public(row) for row in rows]


def get_public_profile(settings: Settings, target_user_id: str, current_user_id: str) -> dict:
    target = _valid_user_id(target_user_id)
    current = _valid_user_id(current_user_id)
    if target == current:
        return get_own_profile(settings, current)
    rows = _request(settings, "GET", params={
        "select": "user_id,username,display_name,bio,avatar_path,updated_at",
        "user_id": f"eq.{target}", "visibility": "eq.public",
        "show_in_directory": "eq.true", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Profile not found or not publicly available.")
    return _public(rows[0])
