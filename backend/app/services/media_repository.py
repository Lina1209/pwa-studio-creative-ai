"""Server-side, owner-filtered metadata access for private media assets.

This module deliberately does not expose Storage URLs or accept storage paths.
All selectors are UUIDs; the authenticated subject is supplied by the route.
"""
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_access import canonical_uuid, require_owned_row, require_same_owner


def _rest_get(settings: Settings, table: str, params: dict) -> list[dict]:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Media metadata storage is not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Accept": "application/json",
    }
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


def get_owned_media_asset(settings: Settings, asset_id: str, authenticated_owner_id: str) -> dict:
    """Load a media row by both its UUID and the verified JWT subject."""
    asset = canonical_uuid(asset_id, "media asset")
    owner = canonical_uuid(authenticated_owner_id, "owner")
    rows = _rest_get(settings, "media_assets", {
        "select": "id,owner_id,project_id,character_id,file_name,file_type,storage_path,metadata,created_at",
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
