"""Tests for safe character-reference replacement orchestration."""
import unittest
from uuid import uuid4

from app.services.media_lifecycle import MediaStatus
from app.services.media_outbox import OutboxStatus
from app.services.media_replacement_workflow import plan_character_reference_replacement

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "22222222-2222-4222-8222-222222222222"
OLD = "33333333-3333-4333-8333-333333333333"
NEW = "44444444-4444-4444-8444-444444444444"
OLD_PATH = f"{OWNER}/characters/{CHARACTER}/{OLD}.png"
NEW_PATH = f"{OWNER}/characters/{CHARACTER}/{NEW}.png"


def inputs(**changes):
    values = dict(
        authenticated_owner_id=OWNER,
        character={"id": CHARACTER, "owner_id": OWNER},
        current_reference_asset_id=OLD,
        old_asset={"id": OLD, "owner_id": OWNER, "status": "ready",
                   "character_id": CHARACTER, "bucket": "studio-media", "storage_path": OLD_PATH},
        new_asset={"id": NEW, "owner_id": OWNER, "status": "object_uploaded",
                   "character_id": CHARACTER, "bucket": "studio-media", "storage_path": NEW_PATH},
        cleanup_event_id=str(uuid4()),
        cleanup_idempotency_key="replace-old-reference-0001",
    )
    values.update(changes)
    return values


class CharacterReferenceReplacementTests(unittest.TestCase):
    def test_plan_promotes_new_asset_and_schedules_old_cleanup(self):
        result = plan_character_reference_replacement(**inputs())
        self.assertEqual(result.character_id, CHARACTER)
        self.assertEqual(result.expected_current_asset_id, OLD)
        self.assertEqual(result.replacement.new_status, MediaStatus.READY)
        self.assertEqual(result.replacement.old_status, MediaStatus.CLEANUP_PENDING)
        self.assertEqual(result.cleanup_event.asset_id, OLD)
        self.assertEqual(result.cleanup_event.event_type, "media_cleanup_requested")
        self.assertEqual(result.cleanup_event.status, OutboxStatus.PENDING)

    def test_stale_character_pointer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            plan_character_reference_replacement(**inputs(current_reference_asset_id=NEW))

    def test_foreign_character_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            plan_character_reference_replacement(**inputs(
                character={"id": CHARACTER, "owner_id": "55555555-5555-4555-8555-555555555555"}
            ))

    def test_asset_attached_to_another_character_is_rejected(self):
        other_character = "66666666-6666-4666-8666-666666666666"
        with self.assertRaisesRegex(ValueError, "another character"):
            plan_character_reference_replacement(**inputs(
                new_asset={**inputs()["new_asset"], "character_id": other_character}
            ))

    def test_public_bucket_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_character_reference_replacement(**inputs(
                new_asset={**inputs()["new_asset"], "bucket": "public"}
            ))

    def test_missing_server_storage_path_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_character_reference_replacement(**inputs(
                old_asset={**inputs()["old_asset"], "storage_path": None}
            ))

    def test_cleanup_event_is_bound_to_old_asset(self):
        result = plan_character_reference_replacement(**inputs())
        self.assertEqual(result.cleanup_event.asset_id, result.replacement.old_asset_id)


if __name__ == "__main__":
    unittest.main()
