"""Privacy-aware creator profile persistence through server-only Supabase credentials."""
import re
from uuid import UUID

import httpx
from app.core.config import Settings


class ProfileUnavailable(RuntimeError):
    pass


def _headers(settings: Settings, *, representation: bool = False):
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise ProfileUnavailable("Profile storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    if representation:
        headers["Prefer"] = "return=representation"
    return headers


def _request(settings: Settings, method: str, *, params=None, payload=None, representation=False):
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.request(
                method, f"{settings.supabase_url.rstrip('/')}/rest/v1/profiles",
                params=params, json=payload,
                headers=_headers(settings, representation=representation),
            )
            response.raise_for_status()
            return response.json() if response.content else []
    except ProfileUnavailable:
        raise
    except Exception as exc:
        raise ProfileUnavailable("Creator profiles are temporarily unavailable.") from exc


PROFILE_FIELDS = "id,username,display_name,bio,avatar_url,profile_visibility,discoverable,allow_direct_messages,created_at,updated_at"


def get_my_profile(settings: Settings, user_id: UUID):
    rows = _request(settings, "GET", params={"select": PROFILE_FIELDS, "id": f"eq.{user_id}", "limit": "1"})
    return rows[0] if isinstance(rows, list) and rows else None


def update_my_profile(settings: Settings, user_id: UUID, values: dict):
    allowed = {"username", "display_name", "bio", "profile_visibility", "discoverable", "allow_direct_messages"}
    payload = {key: value for key, value in values.items() if key in allowed}
    if not payload:
        raise ValueError("No profile fields to update.")
    if "username" in payload:
        payload["username"] = payload["username"].strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,24}", payload["username"]):
            raise ValueError("Username must contain 3–24 lowercase Latin letters, digits or underscores.")
    if "display_name" in payload:
        payload["display_name"] = payload["display_name"].strip()
        if not 2 <= len(payload["display_name"]) <= 40:
            raise ValueError("Display name must contain 2–40 characters.")
    if "bio" in payload:
        payload["bio"] = payload["bio"].strip()
        if len(payload["bio"]) > 160:
            raise ValueError("Bio must be at most 160 characters.")
    if "profile_visibility" in payload and payload["profile_visibility"] not in {"public", "private"}:
        raise ValueError("Invalid profile visibility.")
    rows = _request(settings, "PATCH", params={"id": f"eq.{user_id}", "select": PROFILE_FIELDS},
                    payload=payload, representation=True)
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def search_public_profiles(settings: Settings, actor_id: UUID, query: str, *, limit: int = 20):
    needle = query.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{2,24}", needle):
        return []
    rows = _request(settings, "GET", params={
        "select": "id,username,display_name,bio,avatar_url",
        "username": f"ilike.{needle}%",
        "profile_visibility": "eq.public",
        "discoverable": "eq.true",
        "id": f"neq.{actor_id}",
        "order": "username.asc",
        "limit": str(max(1, min(limit, 30))),
    })
    return rows if isinstance(rows, list) else []


def get_public_profile(settings: Settings, username: str):
    rows = _request(settings, "GET", params={
        "select": "id,username,display_name,bio,avatar_url,created_at",
        "username": f"ilike.{username.lower()}",
        "profile_visibility": "eq.public",
        "discoverable": "eq.true",
        "limit": "1",
    })
    return rows[0] if isinstance(rows, list) else None
