"""Server-only private Storage upload primitive.

Call only after an atomic media-row + outbox reservation has committed. This
module never accepts a bucket/path from the browser and never marks an asset
ready; a separate verifier must confirm the stored object first.
"""
import hashlib
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_workflow import CharacterReferenceUploadPlan


def upload_character_reference_object(
    settings: Settings,
    plan: CharacterReferenceUploadPlan,
    content: bytes,
) -> None:
    """Upload validated bytes to the immutable server-planned private object key."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Private media storage is not configured.")
    if (not isinstance(content, bytes) or len(content) != plan.size_bytes
            or hashlib.sha256(content).hexdigest() != plan.content_sha256):
        raise HTTPException(status_code=400, detail="Image upload does not match its validated fingerprint.")
    endpoint = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{plan.bucket}/{plan.storage_path}"
    )
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Content-Type": plan.file_type,
        "Cache-Control": "no-store",
        "x-upsert": "false",
 
    # sb_secret keys are apikey-only; legacy service-role JWTs also use Bearer.
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"   }
    try:
        response = httpx.post(endpoint, headers=headers, content=content, timeout=30.0)
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail="This media object already exists.")
        response.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        # Avoid exposing upstream Storage response bodies or credentials.
        raise HTTPException(status_code=502, detail="Private image upload was rejected by storage.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Private image storage is temporarily unavailable.") from exc
