import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.schemas import ProfileUpdateRequest
from app.services import profile_service


class ProfileAvatarCatalogTests(unittest.TestCase):
    def test_profile_schema_accepts_catalog_selection(self):
        payload = ProfileUpdateRequest(avatar_catalog_id="forest-elf", avatar_representation="2d")
        self.assertEqual(payload.avatar_catalog_id, "forest-elf")
        self.assertEqual(payload.avatar_representation, "2d")

    def test_profile_schema_rejects_malformed_catalog_id(self):
        with self.assertRaises(Exception):
            ProfileUpdateRequest(avatar_catalog_id="../private/file.svg")

    def test_public_profile_projection_exposes_catalog_id_not_storage_internals(self):
        result = profile_service._public({
            "user_id": "11111111-1111-4111-8111-111111111111",
            "username": "creator_1",
            "display_name": "Creator",
            "bio": "",
            "avatar_path": "private/user/secret.png",
            "avatar_catalog_id": "forest-elf",
            "avatar_representation": "2d",
            "storage_path": "private/internal/object",
            "owner_id": "22222222-2222-4222-8222-222222222222",
        })
        self.assertEqual(result["avatar_catalog_id"], "forest-elf")
        self.assertEqual(result["avatar_representation"], "2d")
        self.assertNotIn("avatar_path", result)
        self.assertNotIn("storage_path", result)
        self.assertNotIn("owner_id", result)

    def test_unknown_catalog_id_is_rejected_before_profile_patch(self):
        existing = {"user_id": "11111111-1111-4111-8111-111111111111"}
        with patch.object(profile_service, "_request", return_value=[existing]) as request:
            with self.assertRaises(HTTPException) as raised:
                profile_service.update_own_profile(object(), existing["user_id"], {"avatar_catalog_id": "unpublished-avatar"})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(request.call_count, 1)  # only the owner-scoped profile read

    def test_3d_is_not_misrepresented_as_available(self):
        existing = {"user_id": "11111111-1111-4111-8111-111111111111"}
        with patch.object(profile_service, "_request", return_value=[existing]) as request:
            with self.assertRaises(HTTPException) as raised:
                profile_service.update_own_profile(object(), existing["user_id"], {"avatar_catalog_id": "forest-elf", "avatar_representation": "3d"})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(request.call_count, 1)

    def test_valid_catalog_choice_is_persisted_by_authenticated_owner(self):
        uid = "11111111-1111-4111-8111-111111111111"
        existing = {"user_id": uid}
        saved = {"user_id": uid, "avatar_catalog_id": "forest-elf", "avatar_representation": "2d"}
        with patch.object(profile_service, "_request", side_effect=[[existing], [saved]]) as request:
            result = profile_service.update_own_profile(object(), uid, {"avatar_catalog_id": "forest-elf", "avatar_representation": "2d"})
        self.assertEqual(result["avatar_catalog_id"], "forest-elf")
        self.assertEqual(request.call_args_list[1].kwargs["params"]["user_id"], "eq." + uid)
        payload = request.call_args_list[1].kwargs["payload"]
        self.assertEqual(payload["avatar_representation"], "2d")
        self.assertIn("avatar_updated_at", payload)


if __name__ == "__main__":
    unittest.main()
