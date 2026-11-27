"""Service-role RPC boundary for durable private media cleanup."""
import httpx

from app.core.config import Settings

_ALLOWED_RPC_FUNCTIONS = frozenset({
    "pwa_request_character_media_cleanup",
    "pwa_claim_media_cleanup",
    "pwa_complete_media_cleanup",
    "pwa_retry_media_cleanup",
    "pwa_finalize_character_media_cleanup",
})


def _call(settings: Settings, function_name: str, payload: dict, *, timeout: float = 15.0):
    if function_name not in _ALLOWED_RPC_FUNCTIONS:
        raise ValueError("Unsupported media cleanup RPC function.")
    if not isinstance(payload, dict):
        raise ValueError("Media cleanup RPC payload must be an object.")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Media cleanup database credentials are not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function_name}",
            headers=headers, json=payload, timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Media cleanup RPC {function_name} failed.") from exc


def _object_result(result, label: str):
    if isinstance(result, list):
        if len(result) > 1:
            raise RuntimeError(f"{label} returned multiple rows.")
        result = result[0] if result else None
    if result is not None and not isinstance(result, dict):
        raise RuntimeError(f"{label} returned an invalid result.")
    return result


def request_character_media_cleanup(settings: Settings, owner_id: str, character_id: str, operation_id: str):
    result = _object_result(_call(settings, "pwa_request_character_media_cleanup", {
        "p_owner_id": owner_id,
        "p_character_id": character_id,
        "p_operation_id": operation_id,
    }), "Character media cleanup reservation")
    required = {"owner_id", "character_id", "operation_id", "assets_enqueued", "status"}
    if not isinstance(result, dict) or not required.issubset(result):
        raise RuntimeError("Character media cleanup reservation returned an invalid result.")
    return result


def claim_media_cleanup(settings: Settings, claim_token: str, lease_seconds: int = 120):
    result = _object_result(_call(settings, "pwa_claim_media_cleanup", {
        "p_claim_token": claim_token,
        "p_lease_seconds": lease_seconds,
    }), "Media cleanup claim")
    if result is None:
        return None
    required = {
        "event_id", "owner_id", "asset_id", "character_id", "claim_token", "bucket",
        "storage_path", "attempts", "max_attempts",
    }
    if not required.issubset(result):
        raise RuntimeError("Media cleanup claim returned an invalid payload.")
    return result


def complete_media_cleanup(settings: Settings, event: dict):
    result = _object_result(_call(settings, "pwa_complete_media_cleanup", {
        "p_owner_id": event["owner_id"],
        "p_asset_id": event["asset_id"],
        "p_event_id": event["event_id"],
        "p_claim_token": event["claim_token"],
    }), "Media cleanup completion")
    if not isinstance(result, dict) or result.get("id") != event["asset_id"] or result.get("status") != "deleted":
        raise RuntimeError("Media cleanup completion returned an invalid result.")
    return result


def retry_media_cleanup(settings: Settings, event: dict, retry_delay_seconds: int):
    result = _object_result(_call(settings, "pwa_retry_media_cleanup", {
        "p_owner_id": event["owner_id"],
        "p_asset_id": event["asset_id"],
        "p_event_id": event["event_id"],
        "p_claim_token": event["claim_token"],
        "p_retry_delay_seconds": retry_delay_seconds,
    }), "Media cleanup retry")
    if not isinstance(result, dict) or result.get("event_status") not in {"pending", "dead_letter"}:
        raise RuntimeError("Media cleanup retry returned an invalid result.")
    return result


def finalize_character_media_cleanup(settings: Settings, owner_id: str, character_id: str):
    result = _object_result(_call(settings, "pwa_finalize_character_media_cleanup", {
        "p_owner_id": owner_id,
        "p_character_id": character_id,
    }), "Character media cleanup finalization")
    if not isinstance(result, dict) or result.get("character_id") != character_id or result.get("status") != "deleted":
        raise RuntimeError("Character media cleanup finalization returned an invalid result.")
    return result
