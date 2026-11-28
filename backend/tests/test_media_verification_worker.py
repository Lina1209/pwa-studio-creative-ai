"""Private media verification worker tests; all external calls are mocked."""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services.image_reference_validation import ValidatedReference
from app.workers.media_outbox_worker import process_one, verify_claimed_media

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
EVENT = "33333333-3333-4333-8333-333333333333"
TOKEN = "44444444-4444-4444-8444-444444444444"
PNG = b"verified-png-bytes"
DIGEST = hashlib.sha256(PNG).hexdigest()

CLAIM = {
    "event_id": EVENT, "owner_id": OWNER, "asset_id": ASSET,
    "claim_token": TOKEN, "bucket": "studio-media",
    "storage_path": f"{OWNER}/characters/{ASSET}/{EVENT}.png",
    "file_name": "reference.png", "file_type": "image/png",
    "size_bytes": len(PNG), "content_sha256": DIGEST,
    "width": 4, "height": 3, "attempts": 1, "max_attempts": 8,
}


def image(content=PNG, mime="image/png", width=4, height=3):
    return ValidatedReference(
        content=content, mime_type=mime, safe_filename="reference.png",
        size_bytes=len(content), width=width, height=height, frame_count=1,
    )


class MediaVerificationWorkerTests(unittest.TestCase):
    @patch("app.workers.media_outbox_worker.download_private_media_image", return_value=image())
    def test_verifies_exact_bytes_and_reserved_metadata(self, download):
        result = verify_claimed_media(object(), CLAIM)
        self.assertEqual(result.content, PNG)
        plan = download.call_args.args[1]
        self.assertEqual(plan.owner_id, OWNER)
        self.assertEqual(plan.asset_id, ASSET)
        self.assertEqual(plan.bucket, "studio-media")

    @patch("app.workers.media_outbox_worker.download_private_media_image")
    def test_rejects_untrusted_bucket_or_object_key_before_storage_access(self, download):
        invalid = dict(CLAIM, bucket="studio-exports")
        with self.assertRaises(ValueError):
            verify_claimed_media(object(), invalid)
        invalid = dict(CLAIM, storage_path=f"{OWNER}/characters/../../private.png")
        with self.assertRaises(ValueError):
            verify_claimed_media(object(), invalid)
        download.assert_not_called()

    @patch("app.workers.media_outbox_worker.download_private_media_image", return_value=image(content=b"different"))
    def test_rejects_digest_or_size_mismatch(self, _download):
        with self.assertRaises(ValueError):
            verify_claimed_media(object(), CLAIM)

    @patch("app.workers.media_outbox_worker.download_private_media_image")
    def test_rejects_malformed_claim_fields_before_storage_access(self, download):
        malformed_claims = [
            dict(CLAIM, owner_id="not-a-uuid"),
            dict(CLAIM, event_id="not-a-uuid"),
            dict(CLAIM, claim_token="not-a-uuid"),
            dict(CLAIM, storage_path=f"99999999-9999-4999-8999-999999999999/characters/{ASSET}/{EVENT}.png"),
            dict(CLAIM, file_name=""),
            dict(CLAIM, file_type="image/gif"),
            dict(CLAIM, storage_path=f"{OWNER}/characters/{ASSET}/{EVENT}.jpg"),
            dict(CLAIM, size_bytes=True),
            dict(CLAIM, width=True),
            dict(CLAIM, height=0),
            dict(CLAIM, content_sha256=DIGEST.upper()),
            dict(CLAIM, attempts=9),
            dict(CLAIM, max_attempts=7),
        ]
        for invalid in malformed_claims:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    verify_claimed_media(object(), invalid)
        download.assert_not_called()

    @patch("app.workers.media_outbox_worker.retry_media_upload_verification")
    @patch("app.workers.media_outbox_worker.complete_media_upload_verification")
    @patch("app.workers.media_outbox_worker.verify_claimed_media", return_value=image())
    @patch("app.workers.media_outbox_worker.claim_media_upload_verification", return_value=CLAIM)
    def test_success_completes_database_transition(self, claim, verify, complete, retry):
        self.assertTrue(process_one(object()))
        claim.assert_called_once()
        verify.assert_called_once()
        complete.assert_called_once()
        retry.assert_not_called()

    @patch("app.workers.media_outbox_worker.retry_media_upload_verification")
    @patch("app.workers.media_outbox_worker.complete_media_upload_verification")
    @patch("app.workers.media_outbox_worker.verify_claimed_media", side_effect=HTTPException(status_code=404))
    @patch("app.workers.media_outbox_worker.claim_media_upload_verification", return_value=CLAIM)
    def test_missing_object_is_scheduled_for_bounded_retry(self, claim, verify, complete, retry):
        self.assertTrue(process_one(object()))
        complete.assert_not_called()
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[2], 30)

    @patch("app.workers.media_outbox_worker.retry_media_upload_verification")
    @patch("app.workers.media_outbox_worker.verify_claimed_media", side_effect=ValueError("invalid claim"))
    @patch("app.workers.media_outbox_worker.claim_media_upload_verification", return_value=dict(CLAIM, attempts="invalid"))
    def test_malformed_attempt_counter_still_uses_safe_retry_path(self, claim, verify, retry):
        retry.return_value = {"event_status": "pending", "asset_status": "object_uploaded"}
        self.assertTrue(process_one(object()))
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[2], 30)

    @patch("app.workers.media_outbox_worker.claim_media_upload_verification", return_value=None)
    def test_empty_queue_returns_without_processing(self, claim):
        self.assertFalse(process_one(object()))
        claim.assert_called_once()


if __name__ == "__main__":
    unittest.main()
