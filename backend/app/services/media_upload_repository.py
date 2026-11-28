"""Server-only database boundary for character-reference upload reservations."""
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_access import canonical_uuid


def _rpc(settings: Settings, function_name: str, payload: dict):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Media metadata storage is not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # sb_secret keys are apikey-only; legacy service-role JWTs also use Bearer.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function_name}",
            headers=headers, json=payload, timeout=15.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 409, 422):
            raise HTTPException(status_code=409, detail="Media upload reservation could not be created.") from exc
        raise HTTPException(status_code=502, detail="Media metadata storage rejected the operation.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Media metadata storage is temporarily unavailable.") from exc


def get_owned_character_for_media_upload(
    settings: Settings, character_id: str, authenticated_owner_id: str
) -> dict:
    character = canonical_uuid(character_id, "character")
    owner = canonical_uuid(authenticated_owner_id, "owner")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Media metadata storage is not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Accept": "application/json",
    }
    # sb_secret keys are apikey-only; legacy service-role JWTs also use Bearer.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
    try:
        response = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/characters",
            headers=headers,
            params={"select": "id,owner_id", "id": f"eq.{character}",
                    "owner_id": f"eq.{owner}", "limit": "1"},
            timeout=12.0,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            raise HTTPException(status_code=404, detail="Character not found.")
        row = rows[0]
        # Defense in depth: never trust a PostgREST response that does not
        # exactly match both identifiers used in the owner-scoped query.
        if (not isinstance(row, dict) or row.get("id") != character
                or row.get("owner_id") != owner):
            raise HTTPException(status_code=404, detail="Character not found.")
        return row
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="Character ownership lookup failed.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Character metadata is temporarily unavailable.") from exc


def reserve_character_reference_upload(settings: Settings, plan) -> dict:
    result = _rpc(settings, "pwa_reserve_character_reference_upload", {
        "p_owner_id": plan.owner_id,
        "p_character_id": plan.character_id,
        "p_asset_id": plan.asset_id,
        "p_operation_id": plan.outbox_event.id,
        "p_event_id": plan.outbox_event.id,
        "p_idempotency_key": plan.outbox_event.idempotency_key,
        "p_file_name": plan.file_name,
        "p_file_type": plan.file_type,
        "p_bucket": plan.bucket,
        "p_storage_path": plan.storage_path,
        "p_size_bytes": plan.size_bytes,
        "p_content_sha256": plan.content_sha256,
        "p_width": plan.width,
        "p_height": plan.height,
    })
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or result.get("id") != plan.asset_id:
        raise HTTPException(status_code=502, detail="Media upload reservation returned an invalid result.")
    return result


def mark_character_reference_object_uploaded(settings: Settings, plan) -> dict:
    result = _rpc(settings, "pwa_mark_character_reference_object_uploaded", {
        "p_owner_id": plan.owner_id,
        "p_asset_id": plan.asset_id,
        "p_operation_id": plan.outbox_event.id,
    })
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or result.get("id") != plan.asset_id:
        raise HTTPException(status_code=502, detail="Media upload status returned an invalid result.")
    return result
