import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.services.generation_worker import ClaimedImageJob
from app.services.supabase_generation_worker_repository import (
    ProviderCostEventResult,
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


@pytest.mark.asyncio
async def test_repository_classifies_transient_http_failures_as_retryable():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="sensitive upstream detail"))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError) as caught:
            await repository.claim_next("worker-a")

    assert caught.value.error_code == "database_temporarily_unavailable"
    assert caught.value.retryable is True
    assert "sensitive upstream detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_repository_classifies_rejected_credentials_as_permanent_and_sanitized():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, text="secret policy detail"))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError) as caught:
            await repository.claim_next("worker-a")

    assert caught.value.error_code == "database_credentials_rejected"
    assert caught.value.retryable is False
    assert "secret policy detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_repository_classifies_connection_loss_as_retryable_without_leaking_exception():
    def disconnect(request):
        raise httpx.ConnectError("private host and credential context", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(disconnect)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError) as caught:
            await repository.claim_next("worker-a")

    assert caught.value.error_code == "database_connection_error"
    assert caught.value.retryable is True
    assert "private host" not in str(caught.value)


@pytest.mark.asyncio
async def test_complete_credited_parses_atomic_capture_result_and_uses_service_rpc():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.read())
        return httpx.Response(200, json=[{
            "completed": True,
            "replayed": False,
            "available_credits": 30,
            "reserved_credits": 0,
        }])

    job_id = UUID("22222222-2222-4222-8222-222222222222")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        result = await repository.complete_credited(
            job_id, "worker-a",
            "11111111-1111-4111-8111-111111111111/generated/result.png", "a".repeat(64),
        )

    assert result.completed is True
    assert result.replayed is False
    assert result.available_credits == 30
    assert result.reserved_credits == 0
    assert seen["url"].endswith("/rpc/complete_credited_generation_job")
    assert seen["payload"]["p_job_id"] == str(job_id)
    assert seen["payload"]["p_worker_id"] == "worker-a"
    assert seen["payload"]["p_result_sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_complete_credited_accepts_lease_lost_result_without_balance_mutation():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{
                "completed": False,
                "replayed": False,
                "available_credits": None,
                "reserved_credits": None,
            }])
        )
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        result = await repository.complete_credited(
            UUID("22222222-2222-4222-8222-222222222222"),
            "stale-worker",
            "11111111-1111-4111-8111-111111111111/generated/result.png", "a" * 64,
        )

    assert result.completed is False
    assert result.available_credits is None
    assert result.reserved_credits is None


@pytest.mark.asyncio
async def test_complete_credited_rejects_malformed_rpc_result():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{
                "completed": True,
                "replayed": False,
                "available_credits": -1,
                "reserved_credits": 0,
            }])
        )
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError):
            await repository.complete_credited(
                UUID("22222222-2222-4222-8222-222222222222"),
                "worker-a",
                "11111111-1111-4111-8111-111111111111/generated/result.png", "a" * 64,
            )


@pytest.mark.asyncio
async def test_record_provider_cost_event_uses_service_rpc_and_parses_budget_status():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json=[{
            "event_id": 17,
            "created": True,
            "cumulative_known_cost_usd": "0.1250000000",
            "budget_limit_usd": "0.1000000000",
            "budget_exceeded": True,
        }])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        result = await repository.record_provider_cost(
            job_id=UUID("22222222-2222-4222-8222-222222222222"),
            user_id=UUID("11111111-1111-4111-8111-111111111111"),
            operation_key="provider-call-0001",
            provider="test-provider",
            model="test-model",
            provider_usage_id="usage-123",
            cost_usd=Decimal("0.125"),
            cost_source="reported",
            input_units=100,
            output_units=25,
            total_units=125,
            unit_kind="token",
            metadata={"billing_reference": "synthetic"},
        )

    assert isinstance(result, ProviderCostEventResult)
    assert result.event_id == 17
    assert result.created is True
    assert result.cumulative_known_cost_usd == Decimal("0.1250000000")
    assert result.budget_limit_usd == Decimal("0.1000000000")
    assert result.budget_exceeded is True
    assert seen["url"].endswith("/rpc/record_generation_provider_cost")
    assert seen["payload"]["p_cost_usd"] == "0.125"
    assert seen["payload"]["p_user_id"] == "11111111-1111-4111-8111-111111111111"


@pytest.mark.asyncio
async def test_record_provider_cost_rejects_inconsistent_or_invalid_cost_before_network():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        base = {
            "job_id": UUID("22222222-2222-4222-8222-222222222222"),
            "user_id": UUID("11111111-1111-4111-8111-111111111111"),
            "operation_key": "provider-call-0002",
            "provider": "test-provider",
            "model": "test-model",
            "provider_usage_id": None,
            "cost_usd": Decimal("0.01"),
            "cost_source": "reported",
        }
        with pytest.raises(WorkerRepositoryError):
            await repository.record_provider_cost(**{**base, "cost_usd": Decimal("-0.01")})
        with pytest.raises(WorkerRepositoryError):
            await repository.record_provider_cost(**{**base, "cost_usd": None})
        with pytest.raises(WorkerRepositoryError):
            await repository.record_provider_cost(**{**base, "input_units": True})


@pytest.mark.asyncio
async def test_record_provider_cost_rejects_malformed_rpc_result():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{
            "event_id": 1,
            "created": "true",
            "cumulative_known_cost_usd": "0.01",
            "budget_limit_usd": None,
            "budget_exceeded": None,
        }]))
    ) as client:
        repository = SupabaseGenerationJobRepository(settings(), client)
        with pytest.raises(WorkerRepositoryError):
            await repository.record_provider_cost(
                job_id=UUID("22222222-2222-4222-8222-222222222222"),
                user_id=UUID("11111111-1111-4111-8111-111111111111"),
                operation_key="provider-call-0003",
                provider="test-provider",
                model="test-model",
                provider_usage_id=None,
                cost_usd=Decimal("0.01"),
                cost_source="estimated",
            )
