"""Integration-style tests for the authenticated private media access route.

All repository and Storage boundaries are mocked; no network calls are made.
"""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
RESOURCE = "33333333-3333-4333-8333-333333333333"
OBJECT = "44444444-4444-4444-8444-444444444444"


def owned_ready_asset():
    return {
        "id": ASSET, "owner_id": OWNER, "project_id": None,
        "character_id": RESOURCE, "file_name": "portrait.png",
        "file_type": "image/png", "created_at": "2026-01-01T00:00:00Z",
        "status": "ready", "bucket": "studio-media",
        "storage_path": f"{OWNER}/characters/{RESOURCE}/{OBJECT}.png",
        "metadata": {"must_not_leak": True},
    }


class PrivateMediaRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(
            user_id=OWNER, email="creator@example.test", role="creator"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.main.create_private_media_signed_url", return_value="https://example.supabase.co/signed?token=secret")
    @patch("app.main.get_owned_media_asset", return_value=owned_ready_asset())
    def test_owner_receives_short_lived_url_and_safe_metadata(self, get_asset, sign):
        response = self.client.get(f"/api/media/{ASSET}/access")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["asset"]["id"], ASSET)
        self.assertEqual(body["signed_url"], "https://example.supabase.co/signed?token=secret")
        self.assertEqual(body["expires_in"], 60)
        self.assertNotIn("owner_id", body["asset"])
        self.assertNotIn("bucket", body["asset"])
        self.assertNotIn("storage_path", body["asset"])
        self.assertNotIn("metadata", body["asset"])
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        sign.assert_called_once()

    @patch("app.main.create_private_media_signed_url")
    @patch("app.main.get_owned_media_asset", side_effect=HTTPException(status_code=404, detail="Media resource not found."))
    def test_missing_or_foreign_asset_never_reaches_signer(self, get_asset, sign):
        response = self.client.get(f"/api/media/{ASSET}/access")
        self.assertEqual(response.status_code, 404)
        sign.assert_not_called()

    @patch("app.main.create_private_media_signed_url")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "status": "cleanup_pending"})
    def test_non_ready_asset_never_reaches_signer(self, get_asset, sign):
        response = self.client.get(f"/api/media/{ASSET}/access")
        self.assertEqual(response.status_code, 404)
        sign.assert_not_called()

    def test_missing_bearer_token_is_rejected(self):
        app.dependency_overrides.clear()
        response = self.client.get(f"/api/media/{ASSET}/access")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
