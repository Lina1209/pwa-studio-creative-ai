"""Tests for complete, owner-scoped character media deletion planning."""
import unittest

from app.services.character_media_cleanup import plan_character_media_cleanup

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CHARACTER = "33333333-3333-4333-8333-333333333333"
ASSET_A = "44444444-4444-4444-8444-444444444444"
ASSET_B = "55555555-5555-4555-8555-555555555555"


def media(asset_id, *, owner=OWNER, character=CHARACTER, status="ready", path_id=None):
    object_id = path_id or asset_id
    return {
        "id": asset_id,
        "owner_id": owner,
        "character_id": character,
        "status": status,
        "bucket": "studio-media",
        "storage_path": f"{owner}/characters/{CHARACTER}/{object_id}.png",
    }


class CharacterMediaCleanupTests(unittest.TestCase):
    def test_plans_all_owned_character_assets(self):
        result = plan_character_media_cleanup(
            authenticated_owner_id=OWNER,
            character={"id": CHARACTER, "owner_id": OWNER},
            assets=[media(ASSET_A), media(ASSET_B)],
            referenced_object_keys=set(),
        )
        self.assertEqual(result.owner_id, OWNER)
        self.assertEqual(result.character_id, CHARACTER)
        self.assertEqual({item.asset_id for item in result.media}, {ASSET_A, ASSET_B})
        self.assertTrue(all(item.final_status.value == "deleted" for item in result.media))

    def test_rejects_foreign_character(self):
        with self.assertRaises(ValueError):
            plan_character_media_cleanup(
                authenticated_owner_id=OWNER,
                character={"id": CHARACTER, "owner_id": OTHER},
                assets=[], referenced_object_keys=set(),
            )

    def test_rejects_foreign_or_misassociated_asset(self):
        for row in (media(ASSET_A, owner=OTHER), media(ASSET_A, character=ASSET_B)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                plan_character_media_cleanup(
                    authenticated_owner_id=OWNER,
                    character={"id": CHARACTER, "owner_id": OWNER},
                    assets=[row], referenced_object_keys=set(),
                )

    def test_rejects_any_exact_object_reference(self):
        row = media(ASSET_A)
        with self.assertRaises(ValueError):
            plan_character_media_cleanup(
                authenticated_owner_id=OWNER,
                character={"id": CHARACTER, "owner_id": OWNER},
                assets=[row],
                referenced_object_keys={(row["bucket"], row["storage_path"])},
            )

    def test_rejects_duplicate_asset_or_object_key(self):
        first = media(ASSET_A)
        duplicate_asset = dict(first)
        duplicate_asset["status"] = "cleanup_pending"
        with self.assertRaises(ValueError):
            plan_character_media_cleanup(
                authenticated_owner_id=OWNER,
                character={"id": CHARACTER, "owner_id": OWNER},
                assets=[first, duplicate_asset], referenced_object_keys=set(),
            )
        second = media(ASSET_B, path_id=ASSET_A)
        with self.assertRaises(ValueError):
            plan_character_media_cleanup(
                authenticated_owner_id=OWNER,
                character={"id": CHARACTER, "owner_id": OWNER},
                assets=[first, second], referenced_object_keys=set(),
            )

    def test_rejects_unsupported_lifecycle_state(self):
        with self.assertRaises(ValueError):
            plan_character_media_cleanup(
                authenticated_owner_id=OWNER,
                character={"id": CHARACTER, "owner_id": OWNER},
                assets=[media(ASSET_A, status="deleted")],
                referenced_object_keys=set(),
            )

    def test_rejects_in_flight_upload_states(self):
        for status in ("pending_upload", "object_uploaded"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                plan_character_media_cleanup(
                    authenticated_owner_id=OWNER,
                    character={"id": CHARACTER, "owner_id": OWNER},
                    assets=[media(ASSET_A, status=status)],
                    referenced_object_keys=set(),
                )

    def test_empty_asset_set_is_valid(self):
        result = plan_character_media_cleanup(
            authenticated_owner_id=OWNER,
            character={"id": CHARACTER, "owner_id": OWNER},
            assets=[], referenced_object_keys=set(),
        )
        self.assertEqual(result.media, ())


if __name__ == "__main__":
    unittest.main()
