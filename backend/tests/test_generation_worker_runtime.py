import asyncio
from uuid import UUID

import pytest

from app.services.generation_worker import ClaimedImageJob, WorkerResult
from app.services.generation_worker_runtime import GenerationWorkerRuntime


class FakeWorker:
    worker_id = "runtime-test"
    lease_seconds = 120

    def __init__(self):
        self.jobs = []

    async def process(self, job):
        self.jobs.append(job.job_id)
        return WorkerResult("succeeded")


class FakeRepository:
    def __init__(self, responses):
        self.responses = list(responses)
        self.claims = []

    async def claim_next(self, worker_id, lease_seconds):
        self.claims.append((worker_id, lease_seconds))
        value = self.responses.pop(0) if self.responses else None
        if isinstance(value, Exception):
            raise value
        return value


def job(job_id="22222222-2222-4222-8222-222222222222"):
    return ClaimedImageJob(
        job_id=UUID(job_id),
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        job_type="image_generation",
        provider="fake",
        model="fake-v1",
        request_snapshot={"prompt": "test"},
        attempt_count=1,
        max_attempts=3,
    )


@pytest.mark.asyncio
async def test_disabled_runtime_never_claims():
    worker, repo = FakeWorker(), FakeRepository([job()])
    runtime = GenerationWorkerRuntime(worker=worker, repository=repo, enabled=False)
    assert await runtime.run() == 0
    assert repo.claims == []


@pytest.mark.asyncio
async def test_runtime_processes_claimed_job_then_stops_at_iteration_limit():
    worker, repo = FakeWorker(), FakeRepository([job()])
    runtime = GenerationWorkerRuntime(
        worker=worker, repository=repo, enabled=True, idle_poll_seconds=0.25
    )
    assert await runtime.run(max_iterations=1) == 1
    assert worker.jobs == [job().job_id]
    assert len(repo.claims) == 1


@pytest.mark.asyncio
async def test_runtime_backoff_after_claim_error_and_continues():
    worker, repo = FakeWorker(), FakeRepository([RuntimeError("secret"), job()])
    runtime = GenerationWorkerRuntime(
        worker=worker,
        repository=repo,
        enabled=True,
        idle_poll_seconds=0.25,
        error_backoff_seconds=0.25,
    )
    assert await runtime.run(max_iterations=2) == 1
    assert worker.jobs == [job().job_id]
    assert len(repo.claims) == 2


@pytest.mark.asyncio
async def test_stop_request_prevents_additional_claims():
    worker, repo = FakeWorker(), FakeRepository([None, job()])
    runtime = GenerationWorkerRuntime(
        worker=worker, repository=repo, enabled=True, idle_poll_seconds=30
    )
    task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.02)
    runtime.request_stop()
    assert await task == 0
    assert len(repo.claims) == 1


def test_runtime_rejects_unbounded_poll_configuration():
    with pytest.raises(ValueError):
        GenerationWorkerRuntime(
            worker=FakeWorker(), repository=FakeRepository([]),
            enabled=True, idle_poll_seconds=0.01,
        )
