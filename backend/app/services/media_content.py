"""Authenticated image proxy for private media.

Every request must pass owner/status authorization before this service is called.
The proxy bounds the download, verifies decoded image bytes, and never issues a
bearer URL. Responses should use no-store headers at the API boundary.
"""
import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.image_reference_validation import (
    MAX_REFERENCE_BYTES,
    ValidatedReference,
    validate_reference_image,
)
from app.services.media_read import MediaReadPlan

ALLOWED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


def download_private_media_image(
    settings: Settings,
    plan: MediaReadPlan,
    *,
    file_name: str,
    expected_mime_type: str,
) -> ValidatedReference:
    """Fetch at most 8 MiB from the server-selected private object and fully decode it."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Private media storage is not configured.")
    if expected_mime_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=404, detail="Media resource not found.")

    endpoint = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{plan.bucket}/{plan.storage_path}"
    )
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Accept": expected_mime_type,
    }
    try:
        chunks = bytearray()
        with httpx.stream("GET", endpoint, headers=headers, timeout=15.0) as response:
            response.raise_for_status()
            declared_length = response.headers.get("content-length")
            if declared_length:
                try:
                    if int(declared_length) > MAX_REFERENCE_BYTES:
                        raise HTTPException(status_code=413, detail="Image exceeds the 8 MiB limit.")
                except ValueError:
                    raise HTTPException(status_code=502, detail="Private media service returned invalid content.")
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                chunks.extend(chunk)
                if len(chunks) > MAX_REFERENCE_BYTES:
                    raise HTTPException(status_code=413, detail="Image exceeds the 8 MiB limit.")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Media resource not found.") from exc
        raise HTTPException(status_code=503, detail="Private media access is temporarily unavailable.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Private media access is temporarily unavailable.") from exc

    try:
        return validate_reference_image(
            bytes(chunks),
            file_name,
            declared_mime_type=expected_mime_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stored image failed integrity validation.") from exc
