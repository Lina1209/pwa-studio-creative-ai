"""Tests for safe immutable media replacement planning."""
import unittest

from app.services.media_lifecycle import MediaStatus
from app.services.media_replacement import plan_media_replacement

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OLD = "33333333-3333-4333-8333-333333333333"
NEW = "44444444-4444-4444-8444-444444444444"


def records(old_status="ready", new_status="object_uploaded", old_owner=OWNER, new_owner=OWNER):
    return (
        {"id": OLD, "owner_id": old_owner, "status": old_status},
        {"id": NEW, "owner_id": new_owner, "status": new_status},
    )


class MediaReplacementTests(unittest.TestCase):
    def test_plan_switches_new_ready_and_old_to_cleanup(self):
        old, new = records()
        plan = plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)
        self.assertEqual(plan.new_status, MediaStatus.READY)
        self.assertEqual(plan.old_status, MediaStatus.CLEANUP_PENDING)
        self.assertEqual(plan.old_asset_id, OLD)
        self.assertEqual(plan.new_asset_id, NEW)

    def test_previous_asset_must_be_ready(self):
        old, new = records(old_status="pending_upload")
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)

    def test_new_asset_must_be_uploaded_and_verified(self):
        old, new = records(new_status="pending_upload")
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)

    def test_foreign_old_or_new_asset_is_rejected(self):
        old, new = records(old_owner=OTHER)
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)
        old, new = records(new_owner=OTHER)
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)

    def test_same_object_cannot_replace_itself(self):
        old, new = records()
        new["id"] = OLD
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)

    def test_failed_precondition_does_not_mutate_old_asset(self):
        old, new = records(new_status="upload_failed")
        before = dict(old)
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id=OWNER, old_asset=old, new_asset=new)
        self.assertEqual(old, before)

    def test_malformed_owner_or_asset_id_is_rejected(self):
        old, new = records()
        with self.assertRaises(ValueError):
            plan_media_replacement(authenticated_owner_id="bad", old_asset=old, new_asset=new)


if __name__ == "__main__":
    unittest.main()
