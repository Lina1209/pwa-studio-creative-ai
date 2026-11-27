"""Pure authorization gate for reading private media.

This planner never downloads bytes or creates a signed URL. Call only after
loading the asset and its linked resources through the owner-filtered repository.
"""
from dataclasses import dataclass
from uuid import UUID

from app.services.media_access import (
    ALLOWED_EXTENSIONS,
    ALLOWED_RESOURCE_KINDS,
    require_private_bucket,
)
from app.services.media_lifecycle import MediaStatus


@dataclass(frozen=True)
class MediaReadPlan:
    owner_id: str
    asset_id: str
    bucket: str
    storage_path: str


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"A valid {label} UUID is required.") from exc


def plan_private_media_read(*, authenticated_owner_id: str, asset: dict) -> MediaReadPlan:
    """Allow read/sign preparation only for an owned, ready, private object."""
    owner = _uuid(authenticated_owner_id, "owner")
    if not isinstance(asset, dict):
        raise ValueError("Media asset record is required.")
    asset_owner = _uuid(asset.get("owner_id"), "asset owner")
    asset_id = _uuid(asset.get("id"), "asset")
    if asset_owner != owner:
        raise ValueError("Media resource not found.")
    if asset.get("status") != MediaStatus.READY.value:
        raise ValueError("Media asset is not available.")
    bucket = asset.get("bucket")
    try:
        require_private_bucket(bucket)
    except Exception as exc:
        raise ValueError("Unsupported private media bucket.") from exc

    path = asset.get("storage_path")
    if not isinstance(path, str) or not path or path.startswith("/") or "\\\\" in path:
        raise ValueError("Invalid server-stored media object key.")
    segments = path.split("/")
    if len(segments) != 4 or any(part in ("", ".", "..") for part in segments):
        raise ValueError("Invalid server-stored media object key.")
    if segments[0] != owner or segments[1] not in ALLOWED_RESOURCE_KINDS:
        raise ValueError("Media object key owner or resource mismatch.")
    _uuid(segments[2], "resource")
    filename = segments[3]
    if filename.count(".") != 1:
        raise ValueError("Invalid media object filename.")
    object_id, extension = filename.rsplit(".", 1)
    _uuid(object_id, "storage object")
    if extension.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported media object extension.")

    return MediaReadPlan(owner_id=owner, asset_id=asset_id, bucket=bucket, storage_path=path)
