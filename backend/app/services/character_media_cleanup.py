"""Pure orchestration plan for deleting a character with its private media.

This planner is intentionally side-effect free. A persistence layer must load the
complete owner-scoped asset set in one transaction, mark every asset
cleanup_pending, enqueue cleanup work atomically, and only then remove the
character after all objects have been reconciled.
"""
from dataclasses import dataclass

from app.services.media_cleanup import MediaCleanupPlan, plan_media_cleanup


@dataclass(frozen=True)
class CharacterMediaCleanupPlan:
    owner_id: str
    character_id: str
    media: tuple[MediaCleanupPlan, ...]


def plan_character_media_cleanup(
    *,
    authenticated_owner_id: str,
    character: dict,
    assets: list[dict],
    referenced_object_keys: set[tuple[str, str]],
) -> CharacterMediaCleanupPlan:
    """Plan cleanup only when every supplied asset belongs to this character.

    `assets` must be the complete server-loaded result for the character, not a
    caller-provided subset. Each object is checked against exact (bucket, path)
    references gathered across all media rows and character passport metadata.
    """
    from uuid import UUID

    try:
        owner = str(UUID(str(authenticated_owner_id)))
        character_id = str(UUID(str(character.get("id"))))
        character_owner = str(UUID(str(character.get("owner_id"))))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("A valid owned character record is required.") from exc
    if owner != character_owner:
        raise ValueError("Character resource not found.")
    if not isinstance(assets, list) or not isinstance(referenced_object_keys, set):
        raise ValueError("Complete server-loaded media references are required.")

    plans = []
    seen_assets: set[str] = set()
    seen_objects: set[tuple[str, str]] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Invalid character media record.")
        if asset.get("owner_id") != owner or asset.get("character_id") != character_id:
            raise ValueError("Character media ownership or association mismatch.")
        asset_id = str(asset.get("id"))
        if asset_id in seen_assets:
            raise ValueError("Duplicate character media record.")
        seen_assets.add(asset_id)

        bucket, path = asset.get("bucket"), asset.get("storage_path")
        if not isinstance(bucket, str) or not isinstance(path, str):
            raise ValueError("Character media object key is invalid.")
        object_key = (bucket, path)
        if object_key in seen_objects:
            raise ValueError("Duplicate object key in character media records.")
        seen_objects.add(object_key)
        if object_key in referenced_object_keys:
            raise ValueError("A character media object is still referenced.")
        if asset.get("status") not in {
            "ready", "pending_upload", "object_uploaded", "upload_failed", "cleanup_pending"
        }:
            raise ValueError("Character media is in an unsupported lifecycle state.")

        cleanup_asset = dict(asset, status="cleanup_pending")
        plans.append(plan_media_cleanup(
            authenticated_owner_id=owner,
            asset=cleanup_asset,
            exact_object_is_referenced=False,
        ))

    return CharacterMediaCleanupPlan(
        owner_id=owner,
        character_id=character_id,
        media=tuple(plans),
    )
