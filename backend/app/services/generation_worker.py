"""Provider-neutral execution contract for one already-claimed image job.

This module intentionally has no polling loop, Supabase client, provider credentials,
or storage SDK. A trusted runner must claim via the service-role RPC and inject
repository/provider/storage adapters. The feature flag remains off until those
adapters and deployment controls exist.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.services.generation_result_storage import (
    StoredObjectMetadata,
    validate_generation_result_object,
)
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageProviderRegistry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedImageJob:
    job_id: UUID
    user_id: UUID
    job_type: str
    provider: str
    model: str
    request_snapshot: dict
    attempt_count: int
    max_attempts: int


@dataclass(frozen=True)
class UploadedImageObject:
    metadata: StoredObjectMetadata
    expected_bucket: str
    expected_object_path: str
    expected_sha256_hex: str


class GenerationJobRepository(Protocol):
    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int) -> bool: ...
    async def retry(self, job_id: UUID, worker_id: str, error_code: str, delay_seconds: int) -> bool: ...
    async def fail(self, job_id: UUID, worker_id: str, error_code: str) -> bool: ...
    async def complete(self, job_id: UUID, worker_id: str, result_path: str) -> bool: ...


class PrivateImageStorage(Protocol):
    async def upload_image(
        self, *, owner_id: UUID, job_id: UUID, image_bytes: bytes, mime_type: str
    ) -> UploadedImageObject: ...


@dataclass(frozen=True)
class WorkerResult:
    outcome: str
    error_code: str | None = None


class GenerationWorker:
    """Execute one leased image job; all state transitions remain DB-authoritative."""

    def __init__(
        self,
        *,
        worker_id: str,
        repository: GenerationJobRepository,
        providers: ImageProviderRegistry,
        storage: PrivateImageStorage,
        lease_seconds: int = 180,
        heartbeat_interval_seconds: float = 30.0,
        retry_base_seconds: int = 15,
        retry_max_seconds: int = 900,
    ):
        if not worker_id or len(worker_id.strip()) > 120:
            raise ValueError("Worker identity must contain 1 to 120 characters.")
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("Lease duration must be between 30 and 3600 seconds.")
        if not 0 < heartbeat_interval_seconds < lease_seconds / 2:
            raise ValueError("Heartbeat interval must be less than half the lease.")
        if not 1 <= retry_base_seconds <= retry_max_seconds <= 86400:
            raise ValueError("Retry delay bounds are invalid.")
        self.worker_id = worker_id.strip()
        self.repository = repository
        self.providers = providers
        self.storage = storage
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    def _retry_delay(self, attempt: int) -> int:
        return min(self.retry_max_seconds, self.retry_base_seconds * (2 ** max(0, attempt - 1)))

    async def _maintain_lease(self, job_id: UUID, lost: asyncio.Event) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            try:
                active = await self.repository.heartbeat(
                    job_id, self.worker_id, self.lease_seconds
                )
            except Exception:
                logger.warning("generation_worker_heartbeat_error job_id=%s", job_id)
                active = False
            if not active:
                lost.set()
                return

    async def _run_while_leased(self, awaitable, lost: asyncio.Event):
        operation = asyncio.create_task(awaitable)
        lease_lost = asyncio.create_task(lost.wait())
        done, pending = await asyncio.wait(
            {operation, lease_lost}, return_when=asyncio.FIRST_COMPLETED
        )
        if lease_lost in done and lost.is_set():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise ImageGenerationError("worker_lease_lost", retryable=False)
        lease_lost.cancel()
        await asyncio.gather(lease_lost, return_exceptions=True)
        return await operation

    async def process(self, job: ClaimedImageJob) -> WorkerResult:
        if job.job_type != "image_generation":
            return await self._terminal_failure(job, "unsupported_job_type")
        if job.attempt_count < 1 or job.max_attempts < job.attempt_count:
            return await self._terminal_failure(job, "invalid_attempt_metadata")

        try:
            request = ImageGenerationRequest(**job.request_snapshot)
            provider: ImageGenerationProvider = self.providers.get(job.provider)
            if provider.name.strip().lower() != job.provider.strip().lower():
                raise ImageGenerationError("provider_identity_mismatch", retryable=False)
            lost = asyncio.Event()
            heartbeat = asyncio.create_task(self._maintain_lease(job.job_id, lost))
            try:
                result = await self._run_while_leased(provider.generate(request), lost)
                if result.provider.strip().lower() != job.provider.strip().lower():
                    raise ImageGenerationError("provider_result_mismatch", retryable=False)
                if result.model != job.model:
                    raise ImageGenerationError("model_result_mismatch", retryable=False)

                uploaded = await self._run_while_leased(
                    self.storage.upload_image(
                        owner_id=job.user_id,
                        job_id=job.job_id,
                        image_bytes=result.image_bytes,
                        mime_type=result.mime_type,
                    ),
                    lost,
                )
                actual_digest = calculate_sha256(result.image_bytes)
                if (
                    uploaded.expected_sha256_hex != actual_digest
                    or uploaded.metadata.size_bytes != len(result.image_bytes)
                    or uploaded.metadata.content_type != result.mime_type
                ):
                    raise GenerationResultStorageError("uploaded_object_content_mismatch")
                verified = validate_generation_result_object(
                    owner_id=job.user_id,
                    expected_bucket=uploaded.expected_bucket,
                    expected_object_path=uploaded.expected_object_path,
                    expected_sha256_hex=actual_digest,
                    metadata=uploaded.metadata,
                )
                if not await self.repository.complete(
                    job.job_id, self.worker_id, verified.object_path
                ):
                    return WorkerResult("lease_lost", "completion_rejected")
                return WorkerResult("succeeded")
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
        except GenerationResultStorageError as exc:
            return await self._terminal_failure(job, exc.error_code)
        except ImageGenerationError as exc:
            if exc.error_code == "worker_lease_lost":
                return WorkerResult("lease_lost", exc.error_code)
            if exc.retryable:
                return await self._schedule_retry(job, exc.error_code)
            return await self._terminal_failure(job, exc.error_code)
        except (ValueError, TypeError, KeyError):
            return await self._terminal_failure(job, "invalid_job_payload")
        except Exception:
            logger.exception("generation_worker_job_error job_id=%s", job.job_id)
            return await self._schedule_retry(job, "worker_internal_error")

    async def _terminal_failure(self, job: ClaimedImageJob, code: str) -> WorkerResult:
        try:
            changed = await self.repository.fail(job.job_id, self.worker_id, code)
        except Exception:
            logger.warning("generation_worker_failure_transition_error job_id=%s", job.job_id)
            return WorkerResult("transition_error", code)
        return WorkerResult("failed" if changed else "lease_lost", code)

    async def _schedule_retry(self, job: ClaimedImageJob, code: str) -> WorkerResult:
        try:
            changed = await self.repository.retry(
                job.job_id, self.worker_id, code, self._retry_delay(job.attempt_count)
            )
        except Exception:
            logger.warning("generation_worker_retry_transition_error job_id=%s", job.job_id)
            return WorkerResult("transition_error", code)
        return WorkerResult("retry_scheduled" if changed else "lease_lost", code)
