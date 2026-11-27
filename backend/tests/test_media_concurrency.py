"""Tests for optimistic concurrency and fencing guards."""
import unittest

from app.services.media_concurrency import authorize_media_mutation

OP = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class MediaConcurrencyTests(unittest.TestCase):
    def test_current_version_and_fence_are_accepted(self):
        permit = authorize_media_mutation(
            operation_id=OP, expected_version=4, current_version=4,
            supplied_fencing_token=12, current_fencing_token=12,
        )
        self.assertEqual(permit.expected_version, 4)
        self.assertEqual(permit.next_version, 5)
        self.assertEqual(permit.fencing_token, 12)

    def test_stale_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            authorize_media_mutation(
                operation_id=OP, expected_version=3, current_version=4,
                supplied_fencing_token=12, current_fencing_token=12,
            )

    def test_stale_worker_fence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            authorize_media_mutation(
                operation_id=OP, expected_version=4, current_version=4,
                supplied_fencing_token=11, current_fencing_token=12,
            )

    def test_future_fence_is_also_rejected(self):
        with self.assertRaises(ValueError):
            authorize_media_mutation(
                operation_id=OP, expected_version=4, current_version=4,
                supplied_fencing_token=13, current_fencing_token=12,
            )

    def test_invalid_operation_id_is_rejected(self):
        with self.assertRaises(ValueError):
            authorize_media_mutation(
                operation_id="bad", expected_version=1, current_version=1,
                supplied_fencing_token=1, current_fencing_token=1,
            )

    def test_zero_negative_bool_and_non_integer_counters_are_rejected(self):
        for bad in (0, -1, True, "4", 1.5):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                authorize_media_mutation(
                    operation_id=OP, expected_version=bad, current_version=1,
                    supplied_fencing_token=1, current_fencing_token=1,
                )

    def test_counter_overflow_not_silently_wrapped(self):
        permit = authorize_media_mutation(
            operation_id=OP, expected_version=2**63 - 1,
            current_version=2**63 - 1, supplied_fencing_token=2,
            current_fencing_token=2,
        )
        self.assertEqual(permit.next_version, 2**63)


if __name__ == "__main__":
    unittest.main()
