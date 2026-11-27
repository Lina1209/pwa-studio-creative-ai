"""End-to-end planning boundary for one private character-reference upload.

This composes existing pure validators and ownership guards. It does not write
metadata, create outbox rows, upload to Storage, or expose a signed URL.
The caller must persist asset metadata + outbox event in one DB transaction.
"""
from dataclasses import dataclass

from app.services.image_reference_validation import validate_reference_image
from app.services.media_access import (
    build_storage_object_key, require_private_bucket, require_same_owner,
)
from app.services.media_lifecycle import MediaStatus
from app.services.media_outbox import MediaOutboxEvent, OutboxStatus


@dataclass(frozen=True)
class CharacterReferenceUploadPlan:
    owner_id: str
    character_id: str
    asset_id: str
    bucket: str
    storage_path: str
    file_name: str
    file_type: str
    size_bytes: int
    width: int
    height: int
    initial_status: MediaStatus
    outbox_event: MediaOutboxEvent


def plan_character_reference_upload(
    *,
    authenticated_owner_id: str,
    character: dict,
    asset_id: str,
    object_id: str,
    event_id: str,
    idempotency_key: str,
    content: bytes,
    filename: str,
    declared_mime_type: str | None = None,
    bucket: str = "studio-media",
) -> CharacterReferenceUploadPlan:
    """Validate owner + bytes, then produce an immutable server-owned upload plan."""
    if not isinstance(character, dict) or character.get("id") is None:
        raise ValueError("An existing character record is required.")
    owner = str(authenticated_owner_id)
    require_same_owner(owner, character)
    character_id = str(character["id"])
    validated = validate_reference_image(content, filename, declared_mime_type)
    safe_bucket = require_private_bucket(bucket)
    object_key = build_storage_object_key(
        owner, "characters", character_id, object_id,
        validated.mime_type.split("/", 1)[1].replace("jpeg", "jpg"),
    )
    event = MediaOutboxEvent(
        id=event_id,
        owner_id=owner,
        asset_id=asset_id,
        event_type="media_upload_verify_requested",
        idempotency_key=idempotency_key,
        status=OutboxStatus.PENDING,
    )
    return CharacterReferenceUploadPlan(
        owner_id=owner,
        character_id=character_id,
        asset_id=event.asset_id,
        bucket=safe_bucket,
        storage_path=object_key,
        file_name=validated.safe_filename,
        file_type=validated.mime_type,
        size_bytes=validated.size_bytes,
        width=validated.width,
        height=validated.height,
        initial_status=MediaStatus.PENDING_UPLOAD,
        outbox_event=event,
    )
