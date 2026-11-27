"""Tests for private media cleanup worker boundaries."""
import unittest
from unittest.mock import ANY, Mock, patch

from app.services.media_cleanup import MediaCleanupPlan
from app.workers.media_cleanup_worker import _validate_claim, process_one

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
EVENT = "33333333-3333-4333-8333-333333333333"
TOKEN = "44444444-4444-4444-8444-444444444444"
CHARACTER = "55555555-5555-4555-8555-555555555555"
OBJECT = "66666666-6666-4666-8666-666666666666"
PATH = f"{OWNER}/characters/{CHARACTER}/{OBJECT}.png"


def claim(**changes):
    values = {
        "owner_id": OWNER, "asset_id": ASSET, "character_id": CHARACTER, "event_id": EVENT,
        "claim_token": TOKEN, "bucket": "studio-media",
        "storage_path": PATH, "attempts": 1, "max_attempts": 8,
    }
    values.update(changes)
    return values


class MediaCleanupWorkerTests(unittest.TestCase):
    def test_accepts_valid_server_claim(self):
        _validate_claim(claim())

    def test_rejects_noncanonical_or_ambiguous_object_keys(self):
        bad_paths = [
            f"/{PATH}",
            PATH.replace("/", "//", 1),
            PATH.replace("/", "\\\\", 1),
            PATH + "?download=1",
            PATH + "#fragment",
            PATH.replace(f"/{OBJECT}.png", f"/%2e%2e/{OBJECT}.png"),
            PATH.replace(f"/{OBJECT}.png", f"/{OBJECT}.png/extra"),
            PATH.replace(f"/{OBJECT}.png", f"/{OBJECT}.svg"),
        ]
        for bad_path in bad_paths:
            with self.subTest(path=bad_path), self.assertRaises(ValueError):
                _validate_claim(claim(storage_path=bad_path))

    def test_rejects_non_object_claim_before_field_access(self):
        for value in (None, [], "claim", 42):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_claim(value)

    def test_rejects_invalid_ids_bucket_path_and_attempts(self):
        bad_claims = [
            claim(owner_id="not-a-uuid"),
            claim(bucket="public"),
            claim(storage_path=f"{OWNER}/../{OBJECT}.png"),
            claim(storage_path=f"{OWNER}/characters/{CHARACTER}/../../bad.png"),
            claim(storage_path=f"{OWNER}/characters/{ASSET}/{OBJECT}.png"),
            claim(attempts=0),
            claim(max_attempts=9),
        ]
        for item in bad_claims:
            with self.subTest(item=item), self.assertRaises(ValueError):
                _validate_claim(item)

    @patch("app.workers.media_cleanup_worker.retry_media_cleanup")
    @patch("app.workers.media_cleanup_worker.delete_private_media_object")
    @patch("app.workers.media_cleanup_worker.complete_media_cleanup")
    @patch("app.workers.media_cleanup_worker.claim_media_cleanup")
    def test_success_deletes_then_completes_with_claim(
        self, claim_rpc, complete, delete, retry
    ):
        claim_rpc.return_value = claim()
        self.assertTrue(process_one(object()))
        delete.assert_called_once()
        self.assertIsInstance(delete.call_args.args[1], MediaCleanupPlan)
        complete.assert_called_once_with(ANY, claim())
        retry.assert_not_called()

    @patch("app.workers.media_cleanup_worker.retry_media_cleanup")
    @patch("app.workers.media_cleanup_worker.delete_private_media_object")
    @patch("app.workers.media_cleanup_worker.complete_media_cleanup")
    @patch("app.workers.media_cleanup_worker.claim_media_cleanup")
    def test_storage_failure_schedules_retry_without_completion(
        self, claim_rpc, complete, delete, retry
    ):
        claim_rpc.return_value = claim()
        delete.side_effect = RuntimeError("storage timeout")
        retry.return_value = {"event_status": "pending"}
        self.assertTrue(process_one(object()))
        complete.assert_not_called()
        retry.assert_called_once()
        self.assertEqual(retry.call_args.args[2], 30)

    @patch("app.workers.media_cleanup_worker.claim_media_cleanup")
    def test_empty_queue_returns_false(self, claim_rpc):
        claim_rpc.return_value = None
        self.assertFalse(process_one(object()))


    @patch("app.workers.media_cleanup_worker.retry_media_cleanup")
    @patch("app.workers.media_cleanup_worker.delete_private_media_object")
    @patch("app.workers.media_cleanup_worker.complete_media_cleanup")
    @patch("app.workers.media_cleanup_worker.claim_media_cleanup")
    def test_invalid_server_claim_never_reaches_storage(
        self, claim_rpc, complete, delete, retry
    ):
        claim_rpc.return_value = claim(bucket="unexpected-bucket")
        retry.return_value = {"event_status": "dead_letter"}
        self.assertTrue(process_one(object()))
        delete.assert_not_called()
        complete.assert_not_called()
        retry.assert_called_once()


    @patch("app.workers.media_cleanup_worker.retry_media_cleanup")
    @patch("app.workers.media_cleanup_worker.delete_private_media_object")
    @patch("app.workers.media_cleanup_worker.complete_media_cleanup")
    @patch("app.workers.media_cleanup_worker.claim_media_cleanup")
    def test_expired_lease_reclaims_after_storage_delete_and_lost_ack(
        self, claim_rpc, complete, delete, retry
    ):
        first_claim = claim()
        second_claim = claim(claim_token="77777777-7777-4777-8777-777777777777", attempts=2)
        claim_rpc.side_effect = [first_claim, second_claim]
        # The mock claim sequence represents a later poll after the first lease
        # expired: attempt 2 has a fresh fencing token. First DELETE succeeded,
        # but completion and retry RPC responses were lost. The second DELETE
        # is the idempotent already-absent case (HTTP 404 is accepted by client).
        complete.side_effect = [RuntimeError("completion response lost"), None]
        retry.side_effect = RuntimeError("retry RPC unavailable")

        self.assertTrue(process_one(object()))
        self.assertTrue(process_one(object()))

        self.assertEqual(delete.call_count, 2)
        self.assertEqual(complete.call_count, 2)
        self.assertEqual(complete.call_args.args[1], second_claim)
        self.assertEqual(second_claim["attempts"], first_claim["attempts"] + 1)
        self.assertNotEqual(second_claim["claim_token"], first_claim["claim_token"])
        retry.assert_called_once()


if __name__ == "__main__":
    unittest.main()
