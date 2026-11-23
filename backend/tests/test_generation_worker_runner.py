import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.generation_worker_runner import (
    GenerationWorkerRunnerConfig,
    run_generation_worker_loop,
)


class FakeRepository:
    def __init__(self, jobs=None, fail_claims=0):
        self.jobs = list(jobs or [])
        self.fail_claims = fail_claims
        self.claim_calls = []

    async def claim_next(self, worker_id, lease_seconds=180):
        self.claim_calls.append((worker_id, lease_seconds))
        if self.fail_claims:
            self.fail_claims -= 1
            raise RuntimeError("private database response must not be logged")
        return self.jobs.pop(0) if self.jobs else None


class FakeWorker:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.processed = []

    async def process(self, job):
        self.processed.append(job)
        self.stop_event.set()
        return SimpleNamespace(outcome="succeeded")


def config(**overrides):
    values = {
        "worker_id": "worker-test",
        "lease_seconds": 120,
        "idle_poll_seconds": 0.25,
        "error_backoff_seconds": 0.25,
    }
    values.update(overrides)
    return GenerationWorkerRunnerConfig(**values)


def test_runner_config_rejects_unsafe_bounds():
    with pytest.raises(ValueError):
        config(worker_id=" ")
    with pytest.raises(ValueError):
        config(lease_seconds=29)
    with pytest.raises(ValueError):
        config(idle_poll_seconds=0.01)
    with pytest.raises(ValueError):
        config(error_backoff_seconds=True)


@pytest.mark.asyncio
async def test_runner_claims_processes_and_stops_gracefully():
    stop = asyncio.Event()
    job = SimpleNamespace(job_id=uuid4())
    repository = FakeRepository([job])
    worker = FakeWorker(stop)

    stats = await run_generation_worker_loop(
        repository=repository,
        worker=worker,
        config=config(),
        stop_event=stop,
    )

    assert worker.processed == [job]
    assert stats.claimed_jobs == 1
    assert stats.completed_process_calls == 1
    assert stats.claim_errors == 0
    assert repository.claim_calls == [("worker-test", 120)]


@pytest.mark.asyncio
async def test_runner_backs_off_after_claim_error_and_recovers():
    stop = asyncio.Event()

    class RecoveringRepository:
        def __init__(self):
            self.claim_calls = 0

        async def claim_next(self, worker_id, lease_seconds=180):
            self.claim_calls += 1
            if self.claim_calls == 1:
                raise RuntimeError("private database response must not be logged")
            stop.set()
            return None

    repository = RecoveringRepository()
    worker = FakeWorker(stop)
    stats = await run_generation_worker_loop(
        repository=repository,
        worker=worker,
        config=config(),
        stop_event=stop,
    )

    assert stats.claim_errors == 1
    assert stats.empty_polls == 1
    assert repository.claim_calls == 2


@pytest.mark.asyncio
async def test_runner_propagates_process_cancellation():
    stop = asyncio.Event()
    repository = FakeRepository([SimpleNamespace(job_id=uuid4())])

    class CancelledWorker:
        async def process(self, job):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_generation_worker_loop(
            repository=repository,
            worker=CancelledWorker(),
            config=config(),
            stop_event=stop,
        )
