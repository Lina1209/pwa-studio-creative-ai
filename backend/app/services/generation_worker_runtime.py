"""Long-running, single-process polling loop for the generation worker.

Adapters are injected by the deployment composition root. This module never
creates credentials, selects a provider, or enables generation by itself.
"""
import asyncio
import logging
from typing import Protocol

from app.services.generation_worker import ClaimedImageJob, GenerationWorker, WorkerResult

logger = logging.getLogger(__name__)


class ClaimingGenerationJobRepository(Protocol):
    async def claim_next(
        self, worker_id: str, lease_seconds: int = 180
    ) -> ClaimedImageJob | None: ...


class GenerationWorkerRuntime:
    def __init__(
        self,
        *,
        worker: GenerationWorker,
        repository: ClaimingGenerationJobRepository,
        enabled: bool = False,
        idle_poll_seconds: float = 3.0,
        max_poll_seconds: float = 30.0,
        error_backoff_seconds: float = 5.0,
    ):
        if not 0.25 <= idle_poll_seconds <= 60:
            raise ValueError("Idle polling interval must be between 0.25 and 60 seconds.")
        if not idle_poll_seconds <= max_poll_seconds <= 300:
            raise ValueError("Maximum polling interval must be between idle interval and 300 seconds.")
        if not 0.25 <= error_backoff_seconds <= 300:
            raise ValueError("Error backoff must be between 0.25 and 300 seconds.")
        self.worker = worker
        self.repository = repository
        self.enabled = enabled
        self.idle_poll_seconds = idle_poll_seconds
        self.max_poll_seconds = max_poll_seconds
        self.error_backoff_seconds = error_backoff_seconds
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Stop claiming new jobs; an already-running job is allowed to finish."""
        self._stop.set()

    async def _wait_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def run(self, *, max_iterations: int | None = None) -> int:
        if not self.enabled:
            logger.info("generation_worker_runtime_disabled")
            return 0

        processed = 0
        idle_delay = self.idle_poll_seconds
        iterations = 0
        while not self._stop.is_set():
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            try:
                job = await self.repository.claim_next(
                    self.worker.worker_id, self.worker.lease_seconds
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("generation_worker_claim_error")
                await self._wait_or_stop(self.error_backoff_seconds)
                continue

            if job is None:
                await self._wait_or_stop(idle_delay)
                idle_delay = min(self.max_poll_seconds, max(self.idle_poll_seconds, idle_delay * 2))
                continue

            idle_delay = self.idle_poll_seconds
            try:
                result: WorkerResult = await self.worker.process(job)
                processed += 1
                logger.info(
                    "generation_worker_job_finished job_id=%s outcome=%s error_code=%s",
                    job.job_id, result.outcome, result.error_code,
                )
            except asyncio.CancelledError:
                # The lease expires naturally if the process is forcibly stopped.
                raise
            except Exception:
                logger.exception("generation_worker_unhandled_job_error job_id=%s", job.job_id)
                # Do not attempt an unverified state transition here. Lease recovery
                # remains the database's responsibility.
        return processed
