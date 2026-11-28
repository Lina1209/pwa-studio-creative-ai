"""Reusable ownership guards for future private media endpoints.

These helpers do not access Supabase or Storage. Call them only after loading
rows server-side; always filter database queries by both resource ID and owner.
"""
from uuid import UUID
import re

from fastapi import HTTPException


ALLOWED_BUCKETS = frozenset({"studio-media", "studio-exports"})
ALLOWED_RESOURCE_KINDS = frozenset({"characters", "projects", "exports"})
ALLOWED_EXTENSIONS = frozenset({"png", "jpg", "webp"})


def canonical_uuid(value: str, label: str = "resource") -> str:
    """Parse an untrusted identifier and return its canonical UUID form."""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"A valid {label} ID is required.") from exc


def canonical_local_reference_id(value: str) -> str:
    """Validate a UUID or the stable legacy <character-UUID>-<reference-UUID> key."""
    candidate = str(value) if value is not None else ""
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    if re.fullmatch(uuid_pattern, candidate):
        return candidate
    if re.fullmatch(uuid_pattern + "-" + uuid_pattern, candidate):
        return candidate
    raise HTTPException(status_code=422, detail="A valid local reference ID is required.")


def require_owned_row(row: dict | None, owner_id: str) -> dict:
    """Hide both absent and foreign-owned rows behind the same 404 response."""
    if not isinstance(row, dict) or row.get("owner_id") != owner_id:
        raise HTTPException(status_code=404, detail="Media resource not found.")
    return row


def require_same_owner(owner_id: str, *related_rows: dict | None) -> None:
    """Reject a project/character association unless every row belongs to owner."""
    if any(not isinstance(row, dict) or row.get("owner_id") != owner_id
           for row in related_rows):
        raise HTTPException(status_code=404, detail="Media resource not found.")


def build_storage_object_key(
    owner_id: str,
    resource_kind: str,
    resource_id: str,
    object_id: str,
    extension: str,
) -> str:
    """Build an immutable key; never accept a client-supplied Storage path."""
    owner = canonical_uuid(owner_id, "owner")
    resource = canonical_uuid(resource_id, "resource")
    object_uuid = canonical_uuid(object_id, "object")
    kind = str(resource_kind).lower()
    suffix = str(extension).lower().lstrip(".")
    if kind not in ALLOWED_RESOURCE_KINDS or suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Unsupported media resource type.")
    return f"{owner}/{kind}/{resource}/{object_uuid}.{suffix}"


def require_private_bucket(bucket: str) -> str:
    """Restrict server operations to the two explicitly provisioned private buckets."""
    if bucket not in ALLOWED_BUCKETS:
        raise HTTPException(status_code=422, detail="Unsupported media storage bucket.")
    return bucket

PUBLIC_MEDIA_FIELDS = frozenset({
    "id", "project_id", "character_id", "file_name", "file_type", "created_at",
})


def media_asset_public_view(row: dict) -> dict:
    """Return an explicit browser-safe allowlist; never expose owner, bucket, path, or metadata."""
    if not isinstance(row, dict):
        raise HTTPException(status_code=404, detail="Media resource not found.")
    return {key: row[key] for key in PUBLIC_MEDIA_FIELDS if key in row}
