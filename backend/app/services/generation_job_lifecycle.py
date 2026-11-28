"""Provider-neutral generation job lifecycle primitives.

Inactive contract only: no database, queue, worker, API route, or provider calls.
A future durable repository must persist every transition atomically.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum


class ProviderSubmissionOutcome(str, Enum):
    """Evidence about whether an external provider accepted a billable request."""

    DEFINITELY_NOT_SUBMITTED = "definitely_not_submitted"
    DEFINITELY_REJECTED = "definitely_rejected"
    ACCEPTED = "accepted"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    CANCEL_REQUESTED = "cancel_requested"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass(frozen=True)
class GenerationJob:
    id: str
    owner_id: str
    idempotency_key: str
    status: JobStatus = JobStatus.QUEUED
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: datetime | None = None
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    result_asset_id: str | None = None
    error_code: str | None = None
    provider_submission_outcome: ProviderSubmissionOutcome = ProviderSubmissionOutcome.UNKNOWN

    def __post_init__(self):
        if not self.id or not self.owner_id or not self.idempotency_key:
            raise ValueError("Job id, owner id, and idempotency key are required.")
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5.")
        if self.attempt_count < 0 or self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count is outside the allowed range.")
        for value in (self.created_at, self.next_attempt_at, self.lease_expires_at, self.cancel_requested_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Job timestamps must be timezone-aware.")


def claim_job(job: GenerationJob, now: datetime, lease_seconds: int = 120) -> GenerationJob:
    _validate_now(now)
    if lease_seconds < 10 or lease_seconds > 900:
        raise ValueError("lease_seconds must be between 10 and 900.")
    if job.status not in {JobStatus.QUEUED, JobStatus.RETRY_WAIT}:
        raise ValueError("Only queued or retry-wait jobs can be claimed.")
    if job.next_attempt_at and job.next_attempt_at > now:
        raise ValueError("The retry delay has not elapsed.")
    if job.attempt_count >= job.max_attempts:
        return replace(job, status=JobStatus.FAILED, error_code="attempt_limit_reached")
    return replace(
        job,
        status=JobStatus.PROCESSING,
        attempt_count=job.attempt_count + 1,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        next_attempt_at=None,
        error_code=None,
        provider_submission_outcome=ProviderSubmissionOutcome.UNKNOWN,
    )


def request_cancel(job: GenerationJob, now: datetime) -> GenerationJob:
    _validate_now(now)
    if job.status in TERMINAL_STATUSES:
        return job
    if job.status in {JobStatus.QUEUED, JobStatus.RETRY_WAIT}:
        return replace(job, status=JobStatus.CANCELLED, next_attempt_at=None)
    if job.status == JobStatus.PROCESSING:
        return replace(job, status=JobStatus.CANCEL_REQUESTED, cancel_requested_at=now)
    if job.status == JobStatus.CANCEL_REQUESTED:
        return job
    if job.status == JobStatus.RECONCILIATION_REQUIRED:
        # Preserve the reconciliation hold; cancellation suppresses any later publication
        # but cannot prove that an already-submitted provider operation stopped.
        return replace(job, cancel_requested_at=job.cancel_requested_at or now)
    raise ValueError("Unsupported job state.")


def mark_succeeded(job: GenerationJob, result_asset_id: str) -> GenerationJob:
    if job.status == JobStatus.CANCEL_REQUESTED:
        # A successful provider response is evidence of acceptance, but it must
        # never overwrite an already-recorded contradictory provider outcome.
        if job.provider_submission_outcome not in {
            ProviderSubmissionOutcome.UNKNOWN,
            ProviderSubmissionOutcome.ACCEPTED,
        }:
            raise ValueError("Provider submission evidence cannot be overwritten by contradictory evidence.")
        # Provider completion can still be billable; suppress publication and reconcile usage.
        return replace(
            job, status=JobStatus.RECONCILIATION_REQUIRED, lease_expires_at=None,
            result_asset_id=None, error_code="provider_completed_after_cancel",
            provider_submission_outcome=ProviderSubmissionOutcome.ACCEPTED,
        )
    if job.status != JobStatus.PROCESSING:
        raise ValueError("Only a processing job can succeed.")
    if not result_asset_id:
        raise ValueError("A successful job requires a result asset id.")
    if job.provider_submission_outcome != ProviderSubmissionOutcome.ACCEPTED:
        raise ValueError("A successful job requires accepted provider submission evidence.")
    return replace(job, status=JobStatus.SUCCEEDED, lease_expires_at=None, result_asset_id=result_asset_id)


def mark_failed(
    job: GenerationJob,
    now: datetime,
    error_code: str,
    retryable: bool,
    retry_delay_seconds: int = 30,
    submission_outcome: ProviderSubmissionOutcome | None = None,
) -> GenerationJob:
    _validate_now(now)
    if job.status not in {JobStatus.PROCESSING, JobStatus.CANCEL_REQUESTED}:
        raise ValueError("Only an active job can fail.")
    if not error_code or len(error_code) > 80:
        raise ValueError("A short, non-sensitive error code is required.")
    if retry_delay_seconds < 1 or retry_delay_seconds > 3600:
        raise ValueError("retry_delay_seconds must be between 1 and 3600.")
    if submission_outcome is None:
        submission_outcome = job.provider_submission_outcome
    if not isinstance(submission_outcome, ProviderSubmissionOutcome):
        raise ValueError("submission_outcome must be a ProviderSubmissionOutcome.")
    # A generic timeout/connection error is not proof of non-acceptance.
    # Only conclusive evidence permits a new provider submission.
    if job.provider_submission_outcome not in {ProviderSubmissionOutcome.UNKNOWN, submission_outcome}:
        raise ValueError("Provider submission evidence cannot be overwritten by contradictory evidence.")
    job = replace(job, provider_submission_outcome=submission_outcome)
    safe_to_retry = submission_outcome in {
        ProviderSubmissionOutcome.DEFINITELY_NOT_SUBMITTED,
        ProviderSubmissionOutcome.DEFINITELY_REJECTED,
    }
    if submission_outcome in {ProviderSubmissionOutcome.UNKNOWN, ProviderSubmissionOutcome.ACCEPTED}:
        return replace(
            job, provider_submission_outcome=submission_outcome, status=JobStatus.RECONCILIATION_REQUIRED, lease_expires_at=None,
            next_attempt_at=None, error_code="provider_outcome_unknown",
        )
    if job.status == JobStatus.CANCEL_REQUESTED:
        return replace(job, status=JobStatus.CANCELLED, lease_expires_at=None, result_asset_id=None)
    can_retry = retryable and safe_to_retry and job.attempt_count < job.max_attempts
    return replace(
        job,
        status=JobStatus.RETRY_WAIT if can_retry else JobStatus.FAILED,
        lease_expires_at=None,
        next_attempt_at=now + timedelta(seconds=retry_delay_seconds) if can_retry else None,
        error_code=error_code,
    )


def recover_expired_lease(
    job: GenerationJob,
    now: datetime,
    submission_outcome: ProviderSubmissionOutcome | None = None,
) -> GenerationJob:
    _validate_now(now)
    if job.status not in {JobStatus.PROCESSING, JobStatus.CANCEL_REQUESTED}:
        raise ValueError("Only active jobs have leases to recover.")
    if job.lease_expires_at is None or job.lease_expires_at > now:
        raise ValueError("The job lease has not expired.")
    if submission_outcome is None:
        submission_outcome = job.provider_submission_outcome
    if not isinstance(submission_outcome, ProviderSubmissionOutcome):
        raise ValueError("submission_outcome must be a ProviderSubmissionOutcome.")
    if job.provider_submission_outcome not in {ProviderSubmissionOutcome.UNKNOWN, submission_outcome}:
        raise ValueError("Provider submission evidence cannot be overwritten by contradictory evidence.")
    job = replace(job, provider_submission_outcome=submission_outcome)
    if submission_outcome in {ProviderSubmissionOutcome.UNKNOWN, ProviderSubmissionOutcome.ACCEPTED}:
        return replace(
            job, provider_submission_outcome=submission_outcome, status=JobStatus.RECONCILIATION_REQUIRED, lease_expires_at=None,
            next_attempt_at=None, result_asset_id=None, error_code="provider_outcome_unknown",
        )
    if job.status == JobStatus.CANCEL_REQUESTED:
        return replace(job, status=JobStatus.CANCELLED, lease_expires_at=None, result_asset_id=None)
    can_retry = job.attempt_count < job.max_attempts
    return replace(
        job,
        status=JobStatus.RETRY_WAIT if can_retry else JobStatus.FAILED,
        lease_expires_at=None,
        next_attempt_at=now if can_retry else None,
        error_code="worker_lease_expired",
    )


def _validate_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime.")
