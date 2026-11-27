"""Pure orchestration plan for safe immutable media replacement.

No database pointer switch or Storage deletion occurs here. The caller must
compare-and-swap the character's current reference in the same transaction that
promotes the new asset, tombstones the old asset, and inserts this cleanup event.
"""
from dataclasses import dataclass
from uuid import UUID

from app.services.media_access import ALLOWED_EXTENSIONS, canonical_uuid, require_private_bucket
from app.services.media_lifecycle import MediaStatus
from app.services.media_outbox import MediaOutboxEvent, OutboxStatus
from app.services.media_replacement import ReplacementPlan, plan_media_replacement


@dataclass(frozen=True)
class CharacterReferenceReplacementPlan:
    character_id: str
    expected_current_asset_id: str
    replacement: ReplacementPlan
    cleanup_event: MediaOutboxEvent


def plan_character_reference_replacement(
    *,
    authenticated_owner_id: str,
    character: dict,
    current_reference_asset_id: str,
    old_asset: dict,
    new_asset: dict,
    cleanup_event_id: str,
    cleanup_idempotency_key: str,
) -> CharacterReferenceReplacementPlan:
    """Prepare a CAS-safe reference switch and durable cleanup request."""
    if not isinstance(character, dict):
        raise ValueError("Character record is required.")
    try:
        owner_id = str(UUID(str(authenticated_owner_id)))
        character_owner_id = str(UUID(str(character.get("owner_id"))))
        character_id = str(UUID(str(character.get("id"))))
        current_asset_id = str(UUID(str(current_reference_asset_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Character ownership and reference IDs must be valid UUIDs.") from exc
    if character_owner_id != owner_id:
        raise ValueError("Character not found.")
    replacement = plan_media_replacement(
        authenticated_owner_id=owner_id,
        old_asset=old_asset,
        new_asset=new_asset,
    )
    if current_asset_id != replacement.old_asset_id:
        raise ValueError("Character reference changed; reload before replacing.")
    if old_asset.get("character_id") != character_id:
        raise ValueError("Previous media asset is not attached to this character.")
    if new_asset.get("character_id") != character_id:
        raise ValueError("Replacement media asset is not attached to this character.")
    old_bucket = require_private_bucket(old_asset.get("bucket"))
    new_bucket = require_private_bucket(new_asset.get("bucket"))
    owner = replacement.owner_id
    character_id = canonical_uuid(character_id, "character")
    for row, bucket in ((old_asset, old_bucket), (new_asset, new_bucket)):
        if row.get("bucket") != bucket:
            raise ValueError("Media bucket metadata is invalid.")
        path = row.get("storage_path")
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise ValueError("Server-stored media object key is required.")
        segments = path.split("/")
        if len(segments) != 4 or segments[:3] != [owner, "characters", character_id]:
            raise ValueError("Media object key does not belong to this character.")
        filename = segments[3]
        if filename.count(".") != 1:
            raise ValueError("Invalid media object filename.")
        object_id, extension = filename.rsplit(".", 1)
        canonical_uuid(object_id, "storage object")
        if extension.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError("Unsupported media object extension.")
    cleanup_event = MediaOutboxEvent(
        id=cleanup_event_id,
        owner_id=replacement.owner_id,
        asset_id=replacement.old_asset_id,
        event_type="media_cleanup_requested",
        idempotency_key=cleanup_idempotency_key,
        status=OutboxStatus.PENDING,
    )
    return CharacterReferenceReplacementPlan(
        character_id=character_id,
        expected_current_asset_id=replacement.old_asset_id,
        replacement=replacement,
        cleanup_event=cleanup_event,
    )
