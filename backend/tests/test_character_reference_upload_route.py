"""Authenticated character-reference upload route tests; external services mocked."""
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "22222222-2222-4222-8222-222222222222"


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (4, 3), "white").save(output, format="PNG")
    return output.getvalue()


class CharacterReferenceUploadRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(
            user_id=OWNER, email="creator@example.test", role="creator"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.main.mark_character_reference_object_uploaded", return_value={"id": "asset", "status": "object_uploaded"})
    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload", side_effect=lambda _settings, plan: {"id": plan.asset_id, "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_valid_image_uses_owner_scoped_plan_and_returns_pending_verification(
        self, character_lookup, reserve, upload, mark
    ):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0001"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["asset"]["character_id"], CHARACTER)
        self.assertEqual(body["asset"]["status"], "object_uploaded")
        self.assertEqual(body["verification"], "pending")
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        self.assertNotIn("storage_path", body["asset"])
        self.assertNotIn("bucket", body["asset"])
        self.assertNotIn("owner_id", body["asset"])
        character_lookup.assert_called_once()
        reserve.assert_called_once()
        upload.assert_called_once()
        mark.assert_called_once()

    @patch("app.main.mark_character_reference_object_uploaded")
    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload")
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_same_idempotency_key_reuses_same_asset_and_does_not_reupload_completed_object(
        self, lookup, reserve, upload, mark
    ):
        reserve.side_effect = [
            {"id": "asset", "status": "pending_upload"},
            {"id": "asset", "status": "object_uploaded"},
        ]
        mark.return_value = {"id": "asset", "status": "object_uploaded"}
        headers = {"Idempotency-Key": "test-character-upload-repeat"}
        files = {"file": ("portrait.png", png_bytes(), "image/png")}
        first = self.client.post(f"/api/characters/{CHARACTER}/references", headers=headers, files=files)
        second = self.client.post(f"/api/characters/{CHARACTER}/references", headers=headers, files=files)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["asset"]["id"], second.json()["asset"]["id"])
        upload.assert_called_once()
        mark.assert_called_once()

    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload")
    @patch("app.main.get_owned_character_for_media_upload", side_effect=HTTPException(status_code=404, detail="Character not found."))
    def test_foreign_or_missing_character_is_rejected_before_reservation(self, lookup, reserve, upload):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0002"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 404)
        reserve.assert_not_called()
        upload.assert_not_called()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_oversized_file_is_rejected_before_character_lookup(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0003"},
            files={"file": ("large.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
        )
        self.assertEqual(response.status_code, 413)
        lookup.assert_not_called()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_invalid_mime_or_image_is_rejected_before_reservation(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0004"},
            files={"file": ("fake.png", b"not an image", "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        lookup.assert_called_once()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_idempotency_key_is_required(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        lookup.assert_not_called()

    @patch("app.services.auth.get_settings")
    def test_missing_authentication_is_rejected(self, get_settings):
        from app.core.config import Settings
        get_settings.return_value = Settings(supabase_url="https://auth.example.test")
        app.dependency_overrides.clear()
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0005"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
