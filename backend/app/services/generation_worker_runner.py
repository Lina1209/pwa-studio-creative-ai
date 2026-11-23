"""Long-running claim/process loop for a separately deployed generation worker.

The runner is dependency-injected on purpose: it does not construct providers,
storage clients, or service-role credentials, and it is never started by FastAPI.
A deployment entrypoint must supply reviewed adapters and an explicit runtime gate.
"""
import asyncio
import logging
from dataclasses import dataclass

from app.services.generation_worker import GenerationWorker
from app.services.supabase_generation_worker_repository import (
    SupabaseGenerationJobRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationWorkerRunnerConfig:
    worker_id: str
    lease_seconds: int = 180
    idle_poll_seconds: float = 3.0
    error_backoff_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.worker_id, str) or not self.worker_id.strip() or len(self.worker_id.strip()) > 120:
            raise ValueError("Worker identity must contain 1 to 120 characters.")
        if isinstance(self.lease_seconds, bool) or not 30 <= self.lease_seconds <= 3600:
            raise ValueError("Lease duration must be between 30 and 3600 seconds.")
        for name, value in (
            ("idle_poll_seconds", self.idle_poll_seconds),
            ("error_backoff_seconds", self.error_backoff_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.25 <= value <= 300:
                raise ValueError(f"{name} must be between 0.25 and 300 seconds.")


@dataclass
class GenerationWorkerRunnerStats:
    claimed_jobs: int = 0
    empty_polls: int = 0
    claim_errors: int = 0
    completed_process_calls: int = 0


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    """Return True when shutdown was requested, False when the delay elapsed."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return stop_event.is_set()


async def run_generation_worker_loop(
    *,
    repository: SupabaseGenerationJobRepository,
    worker: GenerationWorker,
    config: GenerationWorkerRunnerConfig,
    stop_event: asyncio.Event,
) -> GenerationWorkerRunnerStats:
    """Claim one durable job at a time and process it until graceful shutdown.

    Claim failures use bounded configured backoff. Empty queues use a shorter
    idle poll. A process cancellation is deliberately propagated so the
    deployment supervisor can restart the worker; DB leases handle recovery.
    """
    stats = GenerationWorkerRunnerStats()
    while not stop_event.is_set():
        try:
            job = await repository.claim_next(
                config.worker_id, lease_seconds=config.lease_seconds
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats.claim_errors += 1
            code = getattr(exc, "error_code", "worker_claim_failed")
            logger.warning("generation_worker_claim_error code=%s", str(code)[:80])
            if await _wait_or_stop(stop_event, config.error_backoff_seconds):
                break
            continue

        if job is None:
            stats.empty_polls += 1
            if await _wait_or_stop(stop_event, config.idle_poll_seconds):
                break
            continue

        stats.claimed_jobs += 1
        try:
            result = await worker.process(job)
            stats.completed_process_calls += 1
            logger.info(
                "generation_worker_job_processed job_id=%s outcome=%s",
                job.job_id,
                getattr(result, "outcome", "unknown")[:80],
            )
        except asyncio.CancelledError:
            # Do not mutate the job after shutdown cancellation. Its lease
            # expires and the next worker reconciles the durable provider journal.
            raise
        except Exception:
            # The worker normally converts operational errors to WorkerResult.
            # This final boundary keeps one unexpected job from killing the loop.
            logger.exception("generation_worker_unhandled_process_error job_id=%s", job.job_id)

    return stats
