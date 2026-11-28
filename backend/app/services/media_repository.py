"""Server-side, owner-filtered metadata access for private media assets.

This module deliberately does not expose Storage URLs or accept storage paths.
All selectors are UUIDs; the authenticated subject is supplied by the route.
"""
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_access import canonical_uuid, canonical_local_reference_id, require_owned_row, require_same_owner


def _rest_get(settings: Settings, table: str, params: dict) -> list[dict]:
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
            f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}",
            headers=headers, params=params, timeout=12.0,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise HTTPException(status_code=502, detail="Media metadata returned an invalid response.")
        return data
    except httpx.HTTPStatusError as exc:
        # Do not relay PostgREST details, SQL, keys, or storage paths to callers.
        raise HTTPException(status_code=502, detail="Media metadata lookup failed.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Media metadata is temporarily unavailable.") from exc


def list_owned_character_media_assets_for_characters(
    settings: Settings, character_ids: list[str], authenticated_owner_id: str
) -> list[dict]:
    """Return a bounded owner-scoped media catalog for up to 100 characters."""
    owner = canonical_uuid(authenticated_owner_id, "owner")
    if not isinstance(character_ids, list) or not 1 <= len(character_ids) <= 100:
        raise HTTPException(status_code=422, detail="Between 1 and 100 character IDs are required.")
    normalized = [canonical_uuid(value, "character") for value in character_ids]
    if len(set(normalized)) != len(normalized):
        raise HTTPException(status_code=422, detail="Character IDs must be unique.")
    rows = _rest_get(settings, "media_assets", {
        "select": "id,owner_id,character_id,local_reference_id,file_name,file_type,status,size_bytes,content_sha256,width,height,created_at",
        "owner_id": f"eq.{owner}",
        "character_id": "in.(" + ",".join(normalized) + ")",
        "bucket": "eq.studio-media",
        "order": "character_id.asc,created_at.asc,id.asc",
        "limit": "601",
    })
    if len(rows) > 600:
        raise HTTPException(status_code=502, detail="Character media catalog exceeds the safe limit.")
    allowed_statuses = {"pending_upload", "object_uploaded", "ready", "upload_failed", "cleanup_pending", "deleted"}
    seen_assets = set()
    seen_references = set()
    result = []
    for row in rows:
        if (not isinstance(row, dict) or row.get("owner_id") != owner
                or row.get("character_id") not in set(normalized)):
            raise HTTPException(status_code=404, detail="Media resource not found.")
        asset_id = canonical_uuid(row.get("id"), "media asset")
        if asset_id in seen_assets:
            raise HTTPException(status_code=502, detail="Media catalog contains duplicate asset IDs.")
        seen_assets.add(asset_id)
        local_reference_id = row.get("local_reference_id")
        if local_reference_id is not None:
            local_reference_id = canonical_local_reference_id(local_reference_id)
            mapping_key = (row["character_id"], local_reference_id)
            if mapping_key in seen_references:
                raise HTTPException(status_code=502, detail="Media catalog contains duplicate reference mappings.")
            seen_references.add(mapping_key)
            digest = row.get("content_sha256")
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or row.get("file_type") not in {"image/png", "image/jpeg", "image/webp"}
                    or isinstance(row.get("size_bytes"), bool)
                    or not isinstance(row.get("size_bytes"), int)
                    or not 1 <= row["size_bytes"] <= 8 * 1024 * 1024
                    or isinstance(row.get("width"), bool) or not isinstance(row.get("width"), int)
                    or isinstance(row.get("height"), bool) or not isinstance(row.get("height"), int)
                    or not 1 <= row["width"] <= 8192 or not 1 <= row["height"] <= 8192):
                raise HTTPException(status_code=502, detail="Media identity mapping returned invalid integrity metadata.")
        if row.get("status") not in allowed_statuses:
            raise HTTPException(status_code=502, detail="Media metadata returned an invalid status.")
        result.append({key: row.get(key) for key in (
            "id", "character_id", "local_reference_id", "file_name", "file_type",
            "status", "size_bytes", "content_sha256", "width", "height", "created_at"
        )})
    return result

def get_owned_media_asset(settings: Settings, asset_id: str, authenticated_owner_id: str) -> dict:
    """Load a media row by both its UUID and the verified JWT subject."""
    asset = canonical_uuid(asset_id, "media asset")
    owner = canonical_uuid(authenticated_owner_id, "owner")
    rows = _rest_get(settings, "media_assets", {
        "select": "id,owner_id,project_id,character_id,file_name,file_type,bucket,status,storage_path,metadata,size_bytes,content_sha256,width,height,created_at",
        "id": f"eq.{asset}",
        "owner_id": f"eq.{owner}",
        "limit": "1",
    })
    row = require_owned_row(rows[0] if rows else None, owner)

    # Validate linked resources independently; never trust a client-supplied owner or path.
    project_id = row.get("project_id")
    if project_id:
        project = canonical_uuid(project_id, "project")
        projects = _rest_get(settings, "projects", {
            "select": "id,owner_id",
            "id": f"eq.{project}",
            "owner_id": f"eq.{owner}",
            "limit": "1",
        })
        require_same_owner(owner, projects[0] if projects else None)

    character_id = row.get("character_id")
    if character_id:
        character = canonical_uuid(character_id, "character")
        characters = _rest_get(settings, "characters", {
            "select": "id,owner_id",
            "id": f"eq.{character}",
            "owner_id": f"eq.{owner}",
            "limit": "1",
        })
        require_same_owner(owner, characters[0] if characters else None)

    return row


def list_owned_character_media_assets(settings: Settings, character_id: str, authenticated_owner_id: str) -> list[dict]:
    """Return upload/verification state for one owner character without exposing Storage paths."""
    character = canonical_uuid(character_id, "character")
    owner = canonical_uuid(authenticated_owner_id, "owner")
    rows = _rest_get(settings, "media_assets", {
        "select": "id,owner_id,character_id,local_reference_id,file_name,file_type,status,size_bytes,content_sha256,width,height,created_at",
        "owner_id": f"eq.{owner}", "character_id": f"eq.{character}",
        "bucket": "eq.studio-media", "order": "created_at.asc,id.asc", "limit": "101",
    })
    # Never silently return a truncated identity catalog: callers must not
    # mistake a partial set of references for a complete character backup.
    if len(rows) > 100:
        raise HTTPException(status_code=502, detail="Character media catalog exceeds the safe limit.")
    allowed_statuses = {"pending_upload", "object_uploaded", "ready", "upload_failed", "cleanup_pending", "deleted"}
    result = []
    seen_assets = set()
    seen_references = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("owner_id") != owner or row.get("character_id") != character:
            raise HTTPException(status_code=404, detail="Media resource not found.")
        asset_id = canonical_uuid(row.get("id"), "media asset")
        if asset_id in seen_assets:
            raise HTTPException(status_code=502, detail="Media catalog contains duplicate asset IDs.")
        seen_assets.add(asset_id)
        if row.get("local_reference_id") is not None:
            local_reference_id = canonical_local_reference_id(row.get("local_reference_id"))
            if local_reference_id in seen_references:
                raise HTTPException(status_code=502, detail="Media catalog contains duplicate reference mappings.")
            seen_references.add(local_reference_id)
            digest = row.get("content_sha256")
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or row.get("file_type") not in {"image/png", "image/jpeg", "image/webp"}
                    or isinstance(row.get("size_bytes"), bool)
                    or not isinstance(row.get("size_bytes"), int)
                    or not 1 <= row["size_bytes"] <= 8 * 1024 * 1024
                    or isinstance(row.get("width"), bool) or not isinstance(row.get("width"), int)
                    or isinstance(row.get("height"), bool) or not isinstance(row.get("height"), int)
                    or not 1 <= row["width"] <= 8192 or not 1 <= row["height"] <= 8192):
                raise HTTPException(status_code=502, detail="Media identity mapping returned invalid integrity metadata.")
        if row.get("status") not in allowed_statuses:
            raise HTTPException(status_code=502, detail="Media metadata returned an invalid status.")
        result.append({key: row.get(key) for key in ("id", "character_id", "local_reference_id", "file_name", "file_type", "status", "size_bytes", "content_sha256", "width", "height", "created_at")})
    return result