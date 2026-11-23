import httpx

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


TABLE_CHECKS = {
    "profiles": ("user_profiles", "user_id"),
    "notifications": ("user_notifications", "id"),
    "conversations": ("conversation_threads", "id"),
    "messages": ("direct_messages", "id"),
    "reports": ("user_reports", "id"),
    "suspensions": ("user_suspensions", "id"),
    "moderation_audit": ("admin_audit_log", "id"),
}


def _key_kind(key: str | None) -> str:
    if not key:
        return "missing"
    return "legacy_jwt" if key.startswith("eyJ") else "sb_secret_or_other"


def inspect_supabase(settings: Settings) -> dict:
    key = settings.supabase_service_role_key
    result = {
        "supabase_configured": bool(settings.supabase_url and key),
        "supabase_key_kind": _key_kind(key),
        "rest_api_reachable": False,
        "tables": {name: "not_checked" for name in TABLE_CHECKS},
    }
    if not settings.supabase_url or not key:
        return result

    base = settings.supabase_url.rstrip("/")
    headers = supabase_headers(settings, prefer="return=minimal")
    try:
        response = httpx.get(
            f"{base}/rest/v1/",
            headers=headers,
            timeout=5.0,
        )
        result["rest_api_reachable"] = response.status_code < 500
    except httpx.HTTPError:
        return result

    for label, (table, column) in TABLE_CHECKS.items():
        try:
            response = httpx.request(
                "HEAD",
                f"{base}/rest/v1/{table}",
                headers=headers,
                params={"select": column, "limit": "0"},
                timeout=5.0,
            )
            if response.status_code < 400:
                result["tables"][label] = "available"
            elif response.status_code == 404:
                result["tables"][label] = "missing_or_not_exposed"
            else:
                result["tables"][label] = "not_accessible"
        except httpx.HTTPError:
            result["tables"][label] = "unreachable"
    return result
