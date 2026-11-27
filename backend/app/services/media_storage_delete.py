"""Server-only deletion of one pre-authorized private media object.

This is a narrow Storage primitive, not a route or cleanup worker. Callers must
first obtain a MediaCleanupPlan from trusted, owner-scoped metadata and perform
the exact-reference check immediately before calling this function.
"""
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_cleanup import MediaCleanupPlan


def delete_private_media_object(settings: Settings, plan: MediaCleanupPlan) -> None:
    """Delete exactly one immutable private object; absence is idempotent success."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Private media storage is not configured.")
    if not isinstance(plan, MediaCleanupPlan):
        raise ValueError("A trusted media cleanup plan is required.")
    endpoint = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{plan.bucket}/{plan.storage_path}"
    )
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    try:
        response = httpx.delete(endpoint, headers=headers, timeout=20.0)
        if response.status_code == 404:
            return
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail="Private media deletion was rejected by storage."
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Private media storage is temporarily unavailable."
        ) from exc
