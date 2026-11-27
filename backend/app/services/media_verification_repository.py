"""Service-role RPC boundary for durable media verification work."""
import httpx
from fastapi import HTTPException

from app.core.config import Settings


def _call(settings: Settings, function_name: str, payload: dict, *, timeout: float = 15.0):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Media verification database credentials are not configured.")
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
        raise RuntimeError(f"Media verification RPC {function_name} failed.") from exc


def claim_media_upload_verification(settings: Settings, claim_token: str, lease_seconds: int = 120):
    result = _call(settings, "pwa_claim_media_upload_verification", {
        "p_claim_token": claim_token,
        "p_lease_seconds": lease_seconds,
    })
    if result is None:
        return None
    if isinstance(result, list):
        result = result[0] if result else None
    if result is None:
        return None
    required = {
        "event_id", "owner_id", "asset_id", "claim_token", "bucket",
        "storage_path", "file_name", "file_type", "size_bytes",
        "content_sha256", "width", "height", "attempts", "max_attempts",
    }
    if not isinstance(result, dict) or not required.issubset(result):
        raise RuntimeError("Media verification claim returned an invalid payload.")
    return result


def complete_media_upload_verification(settings: Settings, event: dict, verified):
    result = _call(settings, "pwa_complete_media_upload_verification", {
        "p_owner_id": event["owner_id"],
        "p_asset_id": event["asset_id"],
        "p_event_id": event["event_id"],
        "p_claim_token": event["claim_token"],
        "p_content_sha256": verified.content_sha256,
        "p_size_bytes": verified.size_bytes,
        "p_file_type": verified.mime_type,
        "p_width": verified.width,
        "p_height": verified.height,
    })
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or result.get("id") != event["asset_id"] or result.get("status") != "ready":
        raise RuntimeError("Media verification completion returned an invalid result.")
    return result


def retry_media_upload_verification(settings: Settings, event: dict, retry_delay_seconds: int):
    result = _call(settings, "pwa_retry_media_upload_verification", {
        "p_owner_id": event["owner_id"],
        "p_asset_id": event["asset_id"],
        "p_event_id": event["event_id"],
        "p_claim_token": event["claim_token"],
        "p_retry_delay_seconds": retry_delay_seconds,
    })
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or result.get("event_status") not in {"pending", "dead_letter"}:
        raise RuntimeError("Media verification retry returned an invalid result.")
    return result
