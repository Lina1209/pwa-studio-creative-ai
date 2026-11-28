"""Pure safety gate for private media cleanup.

Call only after a server-side query has checked references by exact bucket and
object path. Never pass a client-supplied path into this planner.
"""
from dataclasses import dataclass
from uuid import UUID

from app.services.media_access import ALLOWED_BUCKETS, ALLOWED_EXTENSIONS, ALLOWED_RESOURCE_KINDS
from app.services.media_lifecycle import MediaStatus


@dataclass(frozen=True)
class MediaCleanupPlan:
    owner_id: str
    asset_id: str
    bucket: str
    storage_path: str
    final_status: MediaStatus = MediaStatus.DELETED


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"A valid {label} UUID is required.") from exc


def plan_media_cleanup(
    *,
    authenticated_owner_id: str,
    asset: dict,
    exact_object_is_referenced: bool,
) -> MediaCleanupPlan:
    """Authorize a cleanup plan only for an owned, unreferenced tombstone."""
    owner = _uuid(authenticated_owner_id, "owner")
    if not isinstance(asset, dict):
        raise ValueError("Media asset record is required.")
    asset_owner = _uuid(asset.get("owner_id"), "asset owner")
    asset_id = _uuid(asset.get("id"), "asset")
    if asset_owner != owner:
        raise ValueError("Media resource not found.")
    if asset.get("status") != MediaStatus.CLEANUP_PENDING.value:
        raise ValueError("Only cleanup-pending assets may be deleted.")
    bucket = asset.get("bucket")
    if bucket not in ALLOWED_BUCKETS:
        raise ValueError("Unsupported private media bucket.")
    path = asset.get("storage_path")
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise ValueError("Invalid server-stored media object key.")
    segments = path.split("/")
    if len(segments) != 4 or any(part in ("", ".", "..") for part in segments):
        raise ValueError("Invalid server-stored media object key.")
    if segments[0] != owner:
        raise ValueError("Media object key owner mismatch.")
    if segments[1] not in ALLOWED_RESOURCE_KINDS:
        raise ValueError("Unsupported media resource kind in object key.")
    resource_id = _uuid(segments[2], "object resource")
    filename = segments[3]
    if filename.count(".") != 1:
        raise ValueError("Invalid media object filename.")
    object_id, extension = filename.rsplit(".", 1)
    storage_object_id = _uuid(object_id, "storage object")
    if resource_id != segments[2] or storage_object_id != object_id:
        raise ValueError("Media object key must use canonical lowercase UUIDs.")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported media object extension.")
    if exact_object_is_referenced:
        raise ValueError("Media object is still referenced and cannot be deleted.")
    return MediaCleanupPlan(
        owner_id=owner,
        asset_id=asset_id,
        bucket=bucket,
        storage_path=path,
    )
