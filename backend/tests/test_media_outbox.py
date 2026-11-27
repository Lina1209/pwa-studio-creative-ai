"""Tests for the pure media outbox lifecycle."""
import unittest
from datetime import datetime, timedelta, timezone

from app.services.media_outbox import (
    MediaOutboxEvent, OutboxStatus, acknowledge_media_event,
    claim_media_event, recover_expired_media_claim, retry_media_event,
)

OWNER = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
EVENT = "33333333-3333-4333-8333-333333333333"
TOKEN = "44444444-4444-4444-8444-444444444444"
OTHER_TOKEN = "55555555-5555-4555-8555-555555555555"
NOW = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


def event(**changes):
    values = dict(id=EVENT, owner_id=OWNER, asset_id=ASSET,
                  event_type="media_cleanup_requested", idempotency_key="media-cleanup-0001", available_at=NOW)
    values.update(changes)
    return MediaOutboxEvent(**values)


class MediaOutboxTests(unittest.TestCase):
    def test_claim_and_acknowledge(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN)
        self.assertEqual(claimed.status, OutboxStatus.CLAIMED)
        self.assertEqual(claimed.attempts, 1)
        done = acknowledge_media_event(claimed, claim_token=TOKEN, now=NOW)
        self.assertEqual(done.status, OutboxStatus.DELIVERED)
        self.assertIsNone(done.claim_token)

    def test_wrong_worker_cannot_acknowledge(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN)
        with self.assertRaises(ValueError):
            acknowledge_media_event(claimed, claim_token=OTHER_TOKEN, now=NOW)

    def test_expired_claim_cannot_acknowledge(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN, lease_seconds=10)
        with self.assertRaises(ValueError):
            acknowledge_media_event(claimed, claim_token=TOKEN, now=NOW + timedelta(seconds=10))

    def test_retry_releases_claim_and_delays_next_attempt(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN)
        retried = retry_media_event(claimed, claim_token=TOKEN, now=NOW, retry_delay_seconds=45)
        self.assertEqual(retried.status, OutboxStatus.PENDING)
        self.assertEqual(retried.available_at, NOW + timedelta(seconds=45))
        self.assertIsNone(retried.claim_token)

    def test_expired_claim_can_be_recovered(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN, lease_seconds=10)
        recovered = recover_expired_media_claim(claimed, now=NOW + timedelta(seconds=10))
        self.assertEqual(recovered.status, OutboxStatus.PENDING)
        self.assertIsNone(recovered.claim_token)

    def test_attempt_limit_moves_event_to_dead_letter(self):
        claimed = claim_media_event(event(attempts=7, max_attempts=8), now=NOW, claim_token=TOKEN)
        failed = retry_media_event(claimed, claim_token=TOKEN, now=NOW)
        self.assertEqual(failed.status, OutboxStatus.DEAD_LETTER)

    def test_not_yet_available_event_cannot_be_claimed(self):
        with self.assertRaises(ValueError):
            claim_media_event(event(available_at=NOW + timedelta(seconds=1)),
                              now=NOW, claim_token=TOKEN)

    def test_claimed_event_cannot_be_claimed_twice(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN)
        with self.assertRaises(ValueError):
            claim_media_event(claimed, now=NOW, claim_token=OTHER_TOKEN)

    def test_idempotency_key_is_required_and_bounded(self):
        with self.assertRaises(ValueError):
            event(idempotency_key="short")
        with self.assertRaises(ValueError):
            event(idempotency_key="bad key value")

    def test_unknown_event_type_is_rejected(self):
        with self.assertRaises(ValueError):
            event(event_type="arbitrary_task")

    def test_claim_token_is_required_to_acknowledge(self):
        claimed = claim_media_event(event(), now=NOW, claim_token=TOKEN)
        with self.assertRaises(ValueError):
            acknowledge_media_event(claimed, claim_token=OTHER_TOKEN, now=NOW)


if __name__ == "__main__":
    unittest.main()
