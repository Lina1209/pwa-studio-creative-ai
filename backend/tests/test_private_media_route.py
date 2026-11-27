"""Integration-style tests for the authenticated private media access route.

All repository and Storage boundaries are mocked; no network calls are made.
"""
import unittest
import hashlib
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user
from app.core.config import Settings
from app.services.image_reference_validation import ValidatedReference

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
        "content_sha256": hashlib.sha256(b"validated-png-bytes").hexdigest(),
        "size_bytes": 19, "width": 1, "height": 1,
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

    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value=owned_ready_asset())
    def test_authenticated_image_proxy_returns_no_store_verified_image(self, get_asset, download):
        download.return_value = ValidatedReference(
            content=b"validated-png-bytes", mime_type="image/png",
            safe_filename="portrait.png", size_bytes=19,
            width=1, height=1, frame_count=1,
        )
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"validated-png-bytes")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-content-sha256"], hashlib.sha256(b"validated-png-bytes").hexdigest())
        self.assertEqual(response.headers["cross-origin-resource-policy"], "same-origin")
        download.assert_called_once()

    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "content_sha256": "0" * 64})
    def test_readback_rejects_content_that_does_not_match_reserved_fingerprint(self, get_asset, download):
        download.return_value = ValidatedReference(content=b"validated-png-bytes", mime_type="image/png", safe_filename="portrait.png", size_bytes=19, width=1, height=1, frame_count=1)
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 502)

    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "status": "deleted"})
    def test_deleted_asset_is_denied_before_storage_download(self, get_asset, download):
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 404)
        download.assert_not_called()

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

    @patch("app.services.auth.get_settings", return_value=Settings(supabase_url="https://example.supabase.co"))
    def test_missing_bearer_token_is_rejected(self, _settings):
        app.dependency_overrides.clear()
        response = self.client.get(f"/api/media/{ASSET}/access")
        self.assertEqual(response.status_code, 401)


    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "size_bytes": 20})
    def test_readback_rejects_size_mismatch(self, get_asset, download):
        download.return_value = ValidatedReference(
            content=b"validated-png-bytes", mime_type="image/png",
            safe_filename="portrait.png", size_bytes=19,
            width=1, height=1, frame_count=1,
        )
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Stored image failed integrity validation.")

    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "width": 2})
    def test_readback_rejects_width_mismatch(self, get_asset, download):
        download.return_value = ValidatedReference(
            content=b"validated-png-bytes", mime_type="image/png",
            safe_filename="portrait.png", size_bytes=19,
            width=1, height=1, frame_count=1,
        )
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Stored image failed integrity validation.")

    @patch("app.main.download_private_media_image")
    @patch("app.main.get_owned_media_asset", return_value={**owned_ready_asset(), "height": 2})
    def test_readback_rejects_height_mismatch(self, get_asset, download):
        download.return_value = ValidatedReference(
            content=b"validated-png-bytes", mime_type="image/png",
            safe_filename="portrait.png", size_bytes=19,
            width=1, height=1, frame_count=1,
        )
        response = self.client.get(f"/api/media/{ASSET}/content")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Stored image failed integrity validation.")


if __name__ == "__main__":
    unittest.main()
