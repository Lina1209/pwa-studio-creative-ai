"""Tests for the owner-scoped media cleanup safety gate."""
import unittest

from app.services.media_cleanup import plan_media_cleanup

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ASSET = "33333333-3333-4333-8333-333333333333"
PATH = f"{OWNER}/characters/{ASSET}/{ASSET}.png"


def row(**changes):
    result = {
        "id": ASSET, "owner_id": OWNER, "status": "cleanup_pending",
        "bucket": "studio-media", "storage_path": PATH,
    }
    result.update(changes)
    return result


class MediaCleanupTests(unittest.TestCase):
    def test_owned_unreferenced_tombstone_can_be_planned(self):
        plan = plan_media_cleanup(
            authenticated_owner_id=OWNER, asset=row(), exact_object_is_referenced=False
        )
        self.assertEqual(plan.owner_id, OWNER)
        self.assertEqual(plan.asset_id, ASSET)
        self.assertEqual(plan.storage_path, PATH)
        self.assertEqual(plan.bucket, "studio-media")

    def test_referenced_object_is_never_deleted(self):
        with self.assertRaises(ValueError):
            plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(),
                               exact_object_is_referenced=True)

    def test_only_cleanup_pending_can_be_deleted(self):
        for status in ("ready", "pending_upload", "object_uploaded", "upload_failed", "deleted"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(status=status),
                                   exact_object_is_referenced=False)

    def test_foreign_owner_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(owner_id=OTHER),
                               exact_object_is_referenced=False)

    def test_unknown_bucket_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(bucket="public"),
                               exact_object_is_referenced=False)

    def test_path_must_be_owned_and_well_formed(self):
        for path in (f"{OTHER}/characters/{ASSET}/{ASSET}.png",
                     f"{OWNER}/../secret/{ASSET}.png",
                     f"/{PATH}", PATH.replace("/", "\\")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(storage_path=path),
                                   exact_object_is_referenced=False)

    def test_invalid_asset_id_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_media_cleanup(authenticated_owner_id=OWNER, asset=row(id="nope"),
                               exact_object_is_referenced=False)


    def test_object_key_requires_exact_server_generated_shape(self):
        invalid_paths = (
            f"{OWNER}/unknown/{ASSET}/{ASSET}.png",
            f"{OWNER}/characters/not-a-uuid/{ASSET}.png",
            f"{OWNER}/characters/{ASSET}/not-a-uuid.png",
            f"{OWNER}/characters/{ASSET}/{ASSET}.svg",
            f"{OWNER}/characters/{ASSET}/{ASSET}.png/extra",
        )
        for path in invalid_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                plan_media_cleanup(
                    authenticated_owner_id=OWNER, asset=row(storage_path=path),
                    exact_object_is_referenced=False,
                )


if __name__ == "__main__":
    unittest.main()
