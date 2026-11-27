"""Tests for the service-role media cleanup RPC repository."""
import unittest
from unittest.mock import Mock, patch

from app.core.config import Settings
from app.services.media_cleanup_repository import (
    claim_media_cleanup,
    complete_media_cleanup,
    finalize_character_media_cleanup,
    request_character_media_cleanup,
    retry_media_cleanup,
)

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "22222222-2222-4222-8222-222222222222"
ASSET = "33333333-3333-4333-8333-333333333333"
EVENT = "44444444-4444-4444-8444-444444444444"
TOKEN = "55555555-5555-4555-8555-555555555555"


def settings():
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="service-secret")


class MediaCleanupRepositoryTests(unittest.TestCase):
    @patch("app.services.media_cleanup_repository._call")
    def test_reserves_character_cleanup(self, call):
        expected = {"owner_id": OWNER, "character_id": CHARACTER, "operation_id": TOKEN, "assets_enqueued": 1, "status": "cleanup_pending"}
        call.return_value = expected
        self.assertEqual(request_character_media_cleanup(settings(), OWNER, CHARACTER, TOKEN), expected)
        self.assertEqual(call.call_args.args[1], "pwa_request_character_media_cleanup")

    @patch("app.services.media_cleanup_repository._call")
    def test_claim_validates_required_payload(self, call):
        event = {
            "owner_id": OWNER, "asset_id": ASSET, "character_id": CHARACTER, "event_id": EVENT,
            "claim_token": TOKEN, "bucket": "studio-media",
            "storage_path": f"{OWNER}/characters/{CHARACTER}/{ASSET}.png",
            "attempts": 1, "max_attempts": 8,
        }
        call.return_value = [event]
        self.assertEqual(claim_media_cleanup(settings(), TOKEN), event)
        call.return_value = {"owner_id": OWNER}
        with self.assertRaises(RuntimeError):
            claim_media_cleanup(settings(), TOKEN)

    @patch("app.services.media_cleanup_repository._call")
    def test_complete_retry_and_finalize(self, call):
        call.return_value = {"id": ASSET, "status": "deleted"}
        self.assertEqual(complete_media_cleanup(settings(), {
            "owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN
        })["status"], "deleted")
        call.return_value = {"event_status": "pending"}
        self.assertEqual(retry_media_cleanup(settings(), {
            "owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN
        }, 60)["event_status"], "pending")
        call.return_value = {"character_id": CHARACTER, "status": "deleted"}
        self.assertEqual(finalize_character_media_cleanup(settings(), OWNER, CHARACTER)["status"], "deleted")

    def test_requires_service_credentials(self):
        with self.assertRaises(RuntimeError):
            claim_media_cleanup(Settings(), TOKEN)


if __name__ == "__main__":
    unittest.main()
