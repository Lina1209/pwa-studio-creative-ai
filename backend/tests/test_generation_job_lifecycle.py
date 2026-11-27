import unittest
from datetime import datetime, timedelta, timezone

from app.services.generation_job_lifecycle import (
    GenerationJob, JobStatus, ProviderSubmissionOutcome, claim_job, mark_failed, mark_succeeded,
    recover_expired_lease, request_cancel,
)

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def new_job(**kwargs):
    return GenerationJob(id="job-1", owner_id="user-1", idempotency_key="idem-1", **kwargs)


class GenerationJobLifecycleTests(unittest.TestCase):
    def test_claim_increments_attempt_and_sets_lease(self):
        job = claim_job(new_job(), NOW, lease_seconds=60)
        self.assertEqual(job.status, JobStatus.PROCESSING)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.lease_expires_at, NOW + timedelta(seconds=60))

    def test_retry_wait_cannot_be_claimed_early(self):
        waiting = new_job(status=JobStatus.RETRY_WAIT, attempt_count=1,
                          next_attempt_at=NOW + timedelta(seconds=30))
        with self.assertRaises(ValueError):
            claim_job(waiting, NOW)

    def test_retryable_failure_schedules_bounded_retry(self):
        running = claim_job(new_job(), NOW)
        waiting = mark_failed(
            running, NOW, "provider_rejected_temporarily", True, 45,
            ProviderSubmissionOutcome.DEFINITELY_REJECTED,
        )
        self.assertEqual(waiting.status, JobStatus.RETRY_WAIT)
        self.assertEqual(waiting.next_attempt_at, NOW + timedelta(seconds=45))

    def test_ambiguous_provider_timeout_does_not_retry(self):
        running = claim_job(new_job(), NOW)
        unresolved = mark_failed(running, NOW, "provider_timeout", True, 45)
        self.assertEqual(unresolved.status, JobStatus.FAILED)
        self.assertIsNone(unresolved.next_attempt_at)

    def test_definitely_unsubmitted_attempt_can_retry(self):
        running = claim_job(new_job(), NOW)
        waiting = mark_failed(
            running, NOW, "connection_failed_before_send", True, 15,
            ProviderSubmissionOutcome.DEFINITELY_NOT_SUBMITTED,
        )
        self.assertEqual(waiting.status, JobStatus.RETRY_WAIT)

    def test_non_retryable_failure_is_terminal(self):
        running = claim_job(new_job(), NOW)
        failed = mark_failed(running, NOW, "policy_rejected", False)
        self.assertEqual(failed.status, JobStatus.FAILED)

    def test_attempt_limit_prevents_further_retry(self):
        running = claim_job(new_job(max_attempts=1), NOW)
        failed = mark_failed(running, NOW, "provider_error", True)
        self.assertEqual(failed.status, JobStatus.FAILED)

    def test_cancel_queued_job_immediately(self):
        self.assertEqual(request_cancel(new_job(), NOW).status, JobStatus.CANCELLED)

    def test_cancel_processing_job_is_cooperative(self):
        running = claim_job(new_job(), NOW)
        requested = request_cancel(running, NOW)
        self.assertEqual(requested.status, JobStatus.CANCEL_REQUESTED)
        cancelled = mark_succeeded(requested, "asset-should-not-be-published")
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertIsNone(cancelled.result_asset_id)

    def test_success_requires_processing_and_asset_id(self):
        running = claim_job(new_job(), NOW)
        self.assertEqual(mark_succeeded(running, "asset-1").status, JobStatus.SUCCEEDED)
        with self.assertRaises(ValueError):
            mark_succeeded(running, "")

    def test_expired_lease_is_recovered_for_retry(self):
        running = claim_job(new_job(), NOW, lease_seconds=10)
        recovered = recover_expired_lease(running, NOW + timedelta(seconds=11))
        self.assertEqual(recovered.status, JobStatus.RETRY_WAIT)
        self.assertEqual(recovered.error_code, "worker_lease_expired")

    def test_expired_cancelled_lease_cannot_publish_result(self):
        running = claim_job(new_job(), NOW, lease_seconds=10)
        requested = request_cancel(running, NOW)
        recovered = recover_expired_lease(requested, NOW + timedelta(seconds=11))
        self.assertEqual(recovered.status, JobStatus.CANCELLED)
        self.assertIsNone(recovered.result_asset_id)

    def test_rejects_naive_timestamps_and_invalid_limits(self):
        with self.assertRaises(ValueError):
            new_job(created_at=datetime(2026, 11, 27))
        with self.assertRaises(ValueError):
            new_job(max_attempts=10)


if __name__ == "__main__":
    unittest.main()
