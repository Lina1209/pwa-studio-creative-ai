"""Server-only short-lived signed URL creation for already-authorized media.

This function performs a Storage request only when explicitly called by a future
authenticated route. It never accepts a browser-supplied bucket or object path.
"""
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_read import MediaReadPlan

SIGNED_URL_TTL_SECONDS = 60


def create_private_media_signed_url(settings: Settings, plan: MediaReadPlan) -> str:
    """Create a 60-second URL for a previously authorized private media plan."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Private media storage is not configured.")

    bucket = quote(plan.bucket, safe="")
    path = quote(plan.storage_path, safe="/")
    endpoint = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/sign/"
        f"{bucket}/{path}"
    )
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = httpx.post(
            endpoint,
            headers=headers,
            json={"expiresIn": SIGNED_URL_TTL_SECONDS},
            timeout=12.0,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=503, detail="Private media access is temporarily unavailable.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Private media access is temporarily unavailable.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Private media service returned an invalid response.")
    signed_path = payload.get("signedURL")
    if not isinstance(signed_path, str) or not signed_path.startswith("/") or signed_path.startswith("//"):
        raise HTTPException(status_code=502, detail="Private media service returned an invalid access link.")

    # Supabase returns a relative Storage path. Keep the host pinned to our configured project.
    return f"{settings.supabase_url.rstrip('/')}{signed_path}"
