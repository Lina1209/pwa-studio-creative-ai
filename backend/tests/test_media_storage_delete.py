"""Tests for the private Storage delete primitive."""
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_cleanup import MediaCleanupPlan
from app.services.media_storage_delete import delete_private_media_object

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
OBJECT = "33333333-3333-4333-8333-333333333333"
PATH = f"{OWNER}/characters/{ASSET}/{OBJECT}.png"


def settings():
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="server-secret")


def plan(**changes):
    values = dict(owner_id=OWNER, asset_id=ASSET, bucket="studio-media", storage_path=PATH)
    values.update(changes)
    return MediaCleanupPlan(**values)


class MediaStorageDeleteTests(unittest.TestCase):
    @patch("app.services.media_storage_delete.httpx.delete")
    def test_deletes_exact_server_planned_private_object(self, delete):
        delete.return_value = Mock(status_code=200)
        delete_private_media_object(settings(), plan())
        args, kwargs = delete.call_args
        self.assertEqual(args[0], f"https://example.supabase.co/storage/v1/object/studio-media/{PATH}")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer server-secret")

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_missing_object_is_idempotent_success(self, delete):
        delete.return_value = Mock(status_code=404)
        self.assertIsNone(delete_private_media_object(settings(), plan()))

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_rejects_forged_bucket_or_path_before_network(self, delete):
        for forged in (plan(bucket="public"), plan(storage_path=f"{OWNER}/../../secret.png")):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                delete_private_media_object(settings(), forged)
        delete.assert_not_called()

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_storage_timeout_is_retryable_service_unavailable(self, delete):
        import httpx
        delete.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(settings(), plan())
        self.assertEqual(raised.exception.status_code, 503)

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_permanent_storage_rejection_is_gateway_error(self, delete):
        import httpx
        response = Mock(status_code=403)
        request = httpx.Request("DELETE", "https://example.supabase.co/storage/v1/object/studio-media/test")
        delete.return_value = response
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "forbidden", request=request, response=httpx.Response(403, request=request)
        )
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(settings(), plan())
        self.assertEqual(raised.exception.status_code, 502)

    @patch("app.services.media_storage_delete.httpx.delete")
    def test_requires_server_credentials(self, delete):
        with self.assertRaises(HTTPException) as raised:
            delete_private_media_object(Settings(), plan())
        self.assertEqual(raised.exception.status_code, 503)
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
