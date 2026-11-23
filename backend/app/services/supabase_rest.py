from app.core.config import Settings


def supabase_headers(settings: Settings, *, prefer: str = "return=representation") -> dict[str, str]:
    """Build server-only Supabase REST headers for legacy JWT and new secret API keys."""
    key = settings.supabase_service_role_key
    if not key:
        return {}
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    # Legacy service_role keys are JWTs. New sb_secret_* keys are API keys,
    # not JWTs, and must not be sent as Bearer credentials.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers
