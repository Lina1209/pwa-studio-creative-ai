import json
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.services.generation_worker import ClaimedImageJob
from app.services.supabase_generation_worker_repository import (
    SupabaseGenerationJobRepository,
    WorkerRepositoryError,
    WorkerRepositoryNotConfiguredError,
)


def settings(**overrides):
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_test",
        **overrides,
    )


@pytest.mark.asyncio
async def test_claim_parses_single_job_and_uses_service_key_only_as_apikey():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, json=[{
            "job_id": "22222222-2222-4222-8222-222222222222",
            "user_id": "11111111-1111-4111-8111-111111111111",
            "job_type": "image_generation",
            "provider": "fake",
            "model": "fake-v1",
            "request_snapshot": {"prompt": "test"},
            "attempt_count": 1,
            "max_attempts": 3,
        }])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        job = await repository.claim_next("worker-a", 120)

    assert isinstance(job, ClaimedImageJob)
    assert job.request_snapshot == {"prompt": "test"}
    assert seen["url"].endswith("/rpc/claim_next_generation_job")
    assert seen["headers"]["apikey"] == "sb_secret_test"
    assert "authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_claim_returns_none_when_queue_is_empty():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        assert await repository.claim_next("worker-a") is None


@pytest.mark.asyncio
async def test_claim_rejects_ambiguous_or_incomplete_rows():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"job_id": "bad"}]))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError):
            await repository.claim_next("worker-a")


@pytest.mark.asyncio
async def test_transition_accepts_only_boolean_rpc_result():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=True))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        assert await repository.heartbeat(
            UUID("22222222-2222-4222-8222-222222222222"), "worker-a", 120
        )


def test_repository_fails_closed_without_server_credentials():
    with pytest.raises(WorkerRepositoryNotConfiguredError):
        SupabaseGenerationJobRepository(
            Settings(supabase_url="https://example.supabase.co"),
            httpx.AsyncClient(),
        )


@pytest.mark.asyncio
async def test_owner_job_inventory_is_filtered_and_parsed():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        return httpx.Response(200, json=[{
            "id": "22222222-2222-4222-8222-222222222222",
            "status": "succeeded",
            "result_storage_path": "11111111-1111-4111-8111-111111111111/generated/22222222-2222-4222-8222-222222222222.png",
            "updated_at": "2026-11-20T10:00:00+00:00",
        }])

    owner = UUID("11111111-1111-4111-8111-111111111111")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        rows = await repository.list_owner_job_inventory(owner)

    assert len(rows) == 1
    assert rows[0].job_id == UUID("22222222-2222-4222-8222-222222222222")
    assert rows[0].status == "succeeded"
    assert "user_id=eq." + str(owner) in seen["url"]
    assert seen["headers"]["apikey"] == "sb_secret_test"


@pytest.mark.asyncio
async def test_owner_job_inventory_rejects_invalid_row_and_page_exhaustion():
    owner = UUID("11111111-1111-4111-8111-111111111111")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"id": "bad"}]))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError):
            await repository.list_owner_job_inventory(owner)

    def full_page(request):
        return httpx.Response(200, json=[{
            "id": "22222222-2222-4222-8222-222222222222",
            "status": "failed",
            "result_storage_path": None,
            "updated_at": "2026-11-20T10:00:00+00:00",
        }])

    async with httpx.AsyncClient(transport=httpx.MockTransport(full_page)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError):
            await repository.list_owner_job_inventory(owner, page_size=1, max_pages=1)



@pytest.mark.asyncio
async def test_provider_journal_begin_and_result_transition_use_service_role_rpc():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.read()))
        if request.url.path.endswith("/rpc/begin_generation_provider_operation"):
            return httpx.Response(200, json=[{
                "operation_id": "33333333-3333-4333-8333-333333333333",
                "operation_state": "submitting",
                "provider_request_id": None,
                "created": True,
            }])
        return httpx.Response(200, json=True)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        operation = await repository.begin_provider_operation(
            UUID("22222222-2222-4222-8222-222222222222"),
            "worker-a", "fake", "22222222-2222-4222-8222-222222222222",
        )
        assert operation.created is True
        assert operation.state == "submitting"
        assert await repository.mark_provider_operation_result_received(
            UUID("22222222-2222-4222-8222-222222222222"), "worker-a"
        )

    assert len(seen) == 2
    assert seen[0][1].endswith("/rpc/begin_generation_provider_operation")
    assert seen[1][1].endswith("/rpc/mark_generation_provider_operation_result_received")
    assert b"p_provider_request_id" in seen[1][2]


@pytest.mark.asyncio
async def test_provider_journal_read_parses_existing_state_and_rejects_duplicates():
    def handler(request):
        return httpx.Response(200, json=[{
            "id": "33333333-3333-4333-8333-333333333333",
            "state": "unknown",
            "provider_request_id": None,
        }])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        operation = await repository.get_provider_operation(
            UUID("22222222-2222-4222-8222-222222222222")
        )
    assert operation is not None
    assert operation.state == "unknown"
    assert operation.created is False
