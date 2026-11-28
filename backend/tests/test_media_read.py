"""Tests for the private media read authorization gate."""
import unittest

from app.services.media_read import plan_private_media_read

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ASSET = "33333333-3333-4333-8333-333333333333"
RESOURCE = "44444444-4444-4444-8444-444444444444"
OBJECT = "55555555-5555-4555-8555-555555555555"


def asset(**overrides):
    row = {
        "id": ASSET, "owner_id": OWNER, "status": "ready",
        "character_id": RESOURCE,
        "bucket": "studio-media",
        "storage_path": f"{OWNER}/characters/{RESOURCE}/{OBJECT}.png",
    }
    row.update(overrides)
    return row


class MediaReadTests(unittest.TestCase):
    def test_owned_ready_private_asset_is_eligible(self):
        plan = plan_private_media_read(authenticated_owner_id=OWNER, asset=asset())
        self.assertEqual(plan.owner_id, OWNER)
        self.assertEqual(plan.asset_id, ASSET)
        self.assertEqual(plan.bucket, "studio-media")

    def test_non_ready_states_are_never_readable(self):
        for status in ("pending_upload", "object_uploaded", "upload_failed", "cleanup_pending", "deleted"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                plan_private_media_read(authenticated_owner_id=OWNER, asset=asset(status=status))

    def test_foreign_owner_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_private_media_read(authenticated_owner_id=OWNER, asset=asset(owner_id=OTHER))

    def test_public_or_unknown_bucket_is_rejected(self):
        for bucket in ("public", "unknown"):
            with self.subTest(bucket=bucket), self.assertRaises(ValueError):
                plan_private_media_read(authenticated_owner_id=OWNER, asset=asset(bucket=bucket))

    def test_malformed_or_foreign_path_is_rejected(self):
        paths = (
            f"{OTHER}/characters/{RESOURCE}/{OBJECT}.png",
            f"{OWNER}/../{RESOURCE}/{OBJECT}.png",
            f"{OWNER}/characters/{RESOURCE}/../../secret.png",
            f"{OWNER}/characters/{RESOURCE}/{OBJECT}.svg",
            f"/{OWNER}/characters/{RESOURCE}/{OBJECT}.png",
        )
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                plan_private_media_read(authenticated_owner_id=OWNER, asset=asset(storage_path=path))

    def test_storage_path_must_match_linked_character_or_project(self):
        with self.assertRaises(ValueError):
            plan_private_media_read(
                authenticated_owner_id=OWNER,
                asset=asset(character_id=OTHER),
            )
        with self.assertRaises(ValueError):
            plan_private_media_read(
                authenticated_owner_id=OWNER,
                asset=asset(character_id=None),
            )

    def test_project_path_must_match_linked_project(self):
        path = f"{OWNER}/projects/{RESOURCE}/{OBJECT}.png"
        plan = plan_private_media_read(
            authenticated_owner_id=OWNER,
            asset=asset(storage_path=path, character_id=None, project_id=RESOURCE),
        )
        self.assertEqual(plan.storage_path, path)

    def test_invalid_asset_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_private_media_read(authenticated_owner_id=OWNER, asset=asset(id="not-a-uuid"))


if __name__ == "__main__":
    unittest.main()
