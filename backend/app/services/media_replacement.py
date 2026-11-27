"""Pure replacement planning for immutable private media objects.

This module does not perform Storage writes or database transactions. A future
service must upload/verify the new object first, then persist the pointer switch
and both status changes in ONE database transaction.
"""
from dataclasses import dataclass
from uuid import UUID

from app.services.media_lifecycle import MediaStatus


@dataclass(frozen=True)
class ReplacementPlan:
    owner_id: str
    old_asset_id: str
    new_asset_id: str
    new_status: MediaStatus
    old_status: MediaStatus


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"A valid {label} UUID is required.") from exc


def plan_media_replacement(
    *,
    authenticated_owner_id: str,
    old_asset: dict,
    new_asset: dict,
) -> ReplacementPlan:
    """Plan an atomic pointer switch without mutating either supplied record."""
    owner = _uuid(authenticated_owner_id, "owner")
    if not isinstance(old_asset, dict) or not isinstance(new_asset, dict):
        raise ValueError("Both media asset records are required.")

    old_owner = _uuid(old_asset.get("owner_id"), "old asset owner")
    new_owner = _uuid(new_asset.get("owner_id"), "new asset owner")
    old_id = _uuid(old_asset.get("id"), "old asset")
    new_id = _uuid(new_asset.get("id"), "new asset")

    if old_owner != owner or new_owner != owner:
        raise ValueError("Media asset not found.")
    if old_id == new_id:
        raise ValueError("Replacement must use a new immutable asset ID.")
    if old_asset.get("status") != MediaStatus.READY.value:
        raise ValueError("The previous asset must be ready before replacement.")
    if new_asset.get("status") != MediaStatus.OBJECT_UPLOADED.value:
        raise ValueError("The new object must be uploaded and verified before replacement.")

    return ReplacementPlan(
        owner_id=owner,
        old_asset_id=old_id,
        new_asset_id=new_id,
        new_status=MediaStatus.READY,
        old_status=MediaStatus.CLEANUP_PENDING,
    )
