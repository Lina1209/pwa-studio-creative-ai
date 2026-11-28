"""Tests for the server-only media verification RPC adapter."""
import hashlib
import unittest
from unittest.mock import Mock, patch

from app.core.config import Settings
from app.services.image_reference_validation import ValidatedReference
from app.services.media_verification_repository import (
    claim_media_upload_verification,
    complete_media_upload_verification,
    retry_media_upload_verification,
)

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
EVENT = "33333333-3333-4333-8333-333333333333"
TOKEN = "44444444-4444-4444-8444-444444444444"
CONTENT = b"checked-image-bytes"


def settings():
    return Settings(supabase_url="https://example.supabase.co",
                    supabase_service_role_key="server-secret")


def response(body):
    item = Mock()
    item.status_code = 200
    item.json.return_value = body
    item.raise_for_status.return_value = None
    return item


class MediaVerificationRepositoryTests(unittest.TestCase):
    @patch("app.services.media_verification_repository.httpx.post", return_value=response(None))
    def test_empty_queue_is_none(self, post):
        self.assertIsNone(claim_media_upload_verification(settings(), TOKEN))
        self.assertIn("/rpc/pwa_claim_media_upload_verification", post.call_args.args[0])

    @patch("app.services.media_verification_repository.httpx.post", return_value=response({
        "event_id": EVENT, "owner_id": OWNER, "asset_id": ASSET, "claim_token": TOKEN,
        "bucket": "studio-media", "storage_path": "private/path.png",
        "file_name": "image.png", "file_type": "image/png", "size_bytes": 18,
        "content_sha256": hashlib.sha256(CONTENT).hexdigest(),
        "width": 2, "height": 3, "attempts": 1, "max_attempts": 8,
    }))
    def test_claim_requires_complete_server_payload(self, _post):
        result = claim_media_upload_verification(settings(), TOKEN)
        self.assertEqual(result["asset_id"], ASSET)


    @patch("app.services.media_verification_repository.httpx.post", return_value=response({
        "event_id": EVENT, "owner_id": OWNER, "asset_id": ASSET,
        "claim_token": "77777777-7777-4777-8777-777777777777",
        "bucket": "studio-media", "storage_path": "private/path.png",
        "file_name": "image.png", "file_type": "image/png", "size_bytes": 18,
        "content_sha256": hashlib.sha256(CONTENT).hexdigest(),
        "width": 2, "height": 3, "attempts": 1, "max_attempts": 8,
    }))
    def test_claim_rejects_mismatched_fencing_token(self, _post):
        with self.assertRaises(RuntimeError):
            claim_media_upload_verification(settings(), TOKEN)

    @patch("app.services.media_verification_repository.httpx.post", return_value=response({
        "id": ASSET, "status": "ready", "version": 3,
    }))
    def test_completion_sends_verified_digest_and_fencing_token(self, post):
        image = ValidatedReference(
            content=CONTENT, mime_type="image/png", safe_filename="image.png",
            size_bytes=len(CONTENT), width=2, height=3, frame_count=1,
        )
        event = {"owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN}
        result = complete_media_upload_verification(settings(), event, image)
        self.assertEqual(result["status"], "ready")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["p_content_sha256"], hashlib.sha256(CONTENT).hexdigest())
        self.assertEqual(payload["p_claim_token"], TOKEN)

    @patch("app.services.media_verification_repository.httpx.post", return_value=response({
        "event_status": "pending", "asset_status": "object_uploaded",
    }))
    def test_retry_is_fenced_and_bounded_by_rpc_contract(self, post):
        event = {"owner_id": OWNER, "asset_id": ASSET, "event_id": EVENT, "claim_token": TOKEN}
        result = retry_media_upload_verification(settings(), event, 60)
        self.assertEqual(result["event_status"], "pending")
        self.assertEqual(post.call_args.kwargs["json"]["p_retry_delay_seconds"], 60)

    def test_missing_service_credentials_fails_closed(self):
        with self.assertRaises(RuntimeError):
            claim_media_upload_verification(Settings(), TOKEN)


if __name__ == "__main__":
    unittest.main()
