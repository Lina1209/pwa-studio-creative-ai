"""Unit tests for media ownership guards; no Supabase or Storage calls."""
import unittest
from fastapi import HTTPException

from app.services.media_access import (
    build_storage_object_key,
    canonical_uuid,
    require_owned_row,
    require_private_bucket,
    require_same_owner,
)

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
RESOURCE = "33333333-3333-4333-8333-333333333333"
OBJECT = "44444444-4444-4444-8444-444444444444"


class MediaAccessGuardTests(unittest.TestCase):
    def test_canonical_uuid_rejects_malformed_identifier(self):
        with self.assertRaises(HTTPException) as caught:
            canonical_uuid("../../other-user")
        self.assertEqual(caught.exception.status_code, 422)

    def test_missing_and_foreign_rows_return_same_not_found(self):
        for row in (None, {"id": RESOURCE, "owner_id": OTHER}):
            with self.subTest(row=row), self.assertRaises(HTTPException) as caught:
                require_owned_row(row, OWNER)
            self.assertEqual(caught.exception.status_code, 404)
            self.assertEqual(caught.exception.detail, "Media resource not found.")

    def test_owned_row_is_returned(self):
        row = {"id": RESOURCE, "owner_id": OWNER}
        self.assertIs(require_owned_row(row, OWNER), row)

    def test_cross_owner_project_or_character_association_is_hidden(self):
        with self.assertRaises(HTTPException) as caught:
            require_same_owner(OWNER, {"owner_id": OWNER}, {"owner_id": OTHER})
        self.assertEqual(caught.exception.status_code, 404)

    def test_object_key_is_server_structured_and_immutable(self):
        key = build_storage_object_key(OWNER, "characters", RESOURCE, OBJECT, ".png")
        self.assertEqual(key, f"{OWNER}/characters/{RESOURCE}/{OBJECT}.png")
        self.assertNotIn("filename", key)

    def test_object_key_rejects_unapproved_resource_and_extension(self):
        for kind, extension in (("../bucket", "png"), ("projects", "svg")):
            with self.subTest(kind=kind, extension=extension), self.assertRaises(HTTPException):
                build_storage_object_key(OWNER, kind, RESOURCE, OBJECT, extension)

    def test_only_known_private_buckets_are_allowed(self):
        self.assertEqual(require_private_bucket("studio-media"), "studio-media")
        self.assertEqual(require_private_bucket("studio-exports"), "studio-exports")
        with self.assertRaises(HTTPException) as caught:
            require_private_bucket("public")
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
