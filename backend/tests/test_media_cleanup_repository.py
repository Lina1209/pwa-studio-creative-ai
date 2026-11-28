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
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="eyJserver.secret")


class MediaCleanupRepositoryTests(unittest.TestCase):
    @patch("app.services.media_cleanup_repository._call")
    def test_reserves_character_cleanup(self, call):
        expected = {"owner_id": OWNER, "character_id": CHARACTER, "operation_id": TOKEN, "assets_enqueued": 1, "status": "cleanup_pending"}
        call.return_value = expected
        self.assertEqual(request_character_media_cleanup(settings(), OWNER, CHARACTER, TOKEN), expected)
        self.assertEqual(call.call_args.args[1], "pwa_request_character_media_cleanup")

    @patch("app.services.media_cleanup_repository._call")
    def test_reservation_rejects_mismatched_request_binding(self, call):
        call.return_value = {
            "owner_id": OWNER, "character_id": CHARACTER, "operation_id": EVENT,
            "assets_enqueued": 1, "status": "cleanup_pending",
        }
        with self.assertRaisesRegex(RuntimeError, "mismatched or invalid fields"):
            request_character_media_cleanup(settings(), OWNER, CHARACTER, TOKEN)

    @patch("app.services.media_cleanup_repository._call")
    def test_reservation_rejects_invalid_count_or_status(self, call):
        base = {
            "owner_id": OWNER, "character_id": CHARACTER, "operation_id": TOKEN,
            "assets_enqueued": 1, "status": "cleanup_pending",
        }
        for changes in (
            {"assets_enqueued": True},
            {"assets_enqueued": -1},
            {"status": "deleted"},
            {"assets_enqueued": 0, "status": "cleanup_pending"},
            {"assets_enqueued": 2, "status": "ready_to_finalize"},
        ):
            with self.subTest(changes=changes):
                call.return_value = {**base, **changes}
                with self.assertRaisesRegex(RuntimeError, "mismatched or invalid fields"):
                    request_character_media_cleanup(settings(), OWNER, CHARACTER, TOKEN)

    @patch("app.services.media_cleanup_repository._call")
    def test_claim_rejects_multiple_rpc_rows_as_ambiguous(self, call):
        from app.services.media_cleanup_repository import claim_media_cleanup
        event = {
            "owner_id": OWNER, "asset_id": ASSET, "character_id": CHARACTER, "event_id": EVENT,
            "claim_token": TOKEN, "bucket": "studio-media",
            "storage_path": f"{OWNER}/characters/{CHARACTER}/{ASSET}.png",
            "attempts": 1, "max_attempts": 8,
        }
        call.return_value = [event, event]
        with self.assertRaisesRegex(RuntimeError, "multiple rows"):
            claim_media_cleanup(settings(), TOKEN)

    @patch("app.services.media_cleanup_repository._call")
    def test_claim_rejects_mismatched_fencing_token(self, call):
        event = {
            "owner_id": OWNER, "asset_id": ASSET, "character_id": CHARACTER, "event_id": EVENT,
            "claim_token": "77777777-7777-4777-8777-777777777777", "bucket": "studio-media",
            "storage_path": f"{OWNER}/characters/{CHARACTER}/{ASSET}.png",
            "attempts": 1, "max_attempts": 8,
        }
        call.return_value = event
        with self.assertRaisesRegex(RuntimeError, "mismatched fencing token"):
            claim_media_cleanup(settings(), TOKEN)

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
        call.return_value = {"id": EVENT, "status": "deleted"}
        with self.assertRaisesRegex(RuntimeError, "invalid result"):
            complete_media_cleanup(settings(), {
                "owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN
            })
        call.return_value = {"event_status": "pending", "asset_status": "cleanup_pending"}
        self.assertEqual(retry_media_cleanup(settings(), {
            "owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN
        }, 60)["event_status"], "pending")
        call.return_value = {"event_status": "pending", "asset_status": "deleted"}
        with self.assertRaisesRegex(RuntimeError, "invalid result"):
            retry_media_cleanup(settings(), {
                "owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN
            }, 60)
        call.return_value = {"character_id": CHARACTER, "status": "deleted"}
        self.assertEqual(finalize_character_media_cleanup(settings(), OWNER, CHARACTER)["status"], "deleted")
        call.return_value = {"character_id": OWNER, "status": "deleted"}
        with self.assertRaisesRegex(RuntimeError, "invalid result"):
            finalize_character_media_cleanup(settings(), OWNER, CHARACTER)

    def test_requires_service_credentials(self):
        with self.assertRaises(RuntimeError):
            claim_media_cleanup(Settings(), TOKEN)


    @patch("app.services.media_cleanup_repository.httpx.post")
    def test_rpc_rejects_unlisted_function_before_network(self, post):
        from app.services.media_cleanup_repository import _call
        with self.assertRaises(ValueError):
            _call(settings(), "pwa_claim_media_cleanup/../../admin", {})
        post.assert_not_called()

    @patch("app.services.media_cleanup_repository.httpx.post")
    def test_rpc_requires_object_payload_before_network(self, post):
        from app.services.media_cleanup_repository import _call
        with self.assertRaises(ValueError):
            _call(settings(), "pwa_claim_media_cleanup", [])
        post.assert_not_called()

    @patch("app.services.media_cleanup_repository.httpx.post")
    def test_rpc_uses_service_role_and_exact_function_path(self, post):
        response = Mock()
        response.json.return_value = None
        post.return_value = response
        from app.services.media_cleanup_repository import _call
        _call(settings(), "pwa_claim_media_cleanup", {"p_claim_token": TOKEN})
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://example.supabase.co/rest/v1/rpc/pwa_claim_media_cleanup",
        )
        self.assertEqual(kwargs["headers"]["apikey"], "eyJserver.secret")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJserver.secret")
        self.assertEqual(kwargs["json"], {"p_claim_token": TOKEN})
        self.assertEqual(kwargs["timeout"], 15.0)

    @patch("app.services.media_cleanup_repository.httpx.post")
    def test_rpc_transport_error_is_sanitized(self, post):
        import httpx
        post.side_effect = httpx.TimeoutException("secret response body")
        from app.services.media_cleanup_repository import _call
        with self.assertRaises(RuntimeError) as raised:
            _call(settings(), "pwa_claim_media_cleanup", {"p_claim_token": TOKEN})
        self.assertIn("pwa_claim_media_cleanup", str(raised.exception))
        self.assertNotIn("secret response body", str(raised.exception))
        self.assertNotIn("eyJserver.secret", str(raised.exception))

    @patch("app.services.media_cleanup_repository.httpx.post")
    def test_rpc_http_rejection_is_sanitized(self, post):
        import httpx
        request = httpx.Request("POST", "https://example.supabase.co/rest/v1/rpc/pwa_claim_media_cleanup")
        response = httpx.Response(403, request=request, text="service-secret leaked by upstream")
        post.return_value = Mock()
        post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "upstream rejection", request=request, response=response
        )
        from app.services.media_cleanup_repository import _call
        with self.assertRaises(RuntimeError) as raised:
            _call(settings(), "pwa_claim_media_cleanup", {"p_claim_token": TOKEN})
        self.assertNotIn("eyJserver.secret", str(raised.exception))
        self.assertNotIn("upstream rejection", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
