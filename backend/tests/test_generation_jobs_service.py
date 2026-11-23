from decimal import Decimal
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import generation_jobs
from app.services.pricing_service import PricingCatalog, PricingRule, canonical_request_hash, issue_pricing_quote


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
EVENT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = RuntimeError("HTTP error")
            error.response = type("Response", (), {"status_code": self.status_code})()
            raise error

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, *, json, headers):
        self.calls.append(("POST", url, json, headers))
        return self.response

    def get(self, url, *, params, headers):
        self.calls.append(("GET", url, params, headers))
        return self.response


def configured_settings(**overrides):
    values = {
        "supabase_url": "https://example.supabase.co/",
        "supabase_service_role_key": "sb_secret_test_key",
        "generation_jobs_enabled": True,
        "pricing_quote_signing_secret": "test-signing-secret-with-at-least-32-bytes",
    }
    values.update(overrides)
    return Settings(**values)


def test_create_generation_job_calls_trusted_rpc_with_server_key(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{
                "job_id": str(JOB_ID),
                "event_id": str(EVENT_ID),
                "created": True,
            }]),
            calls,
        ),
    )

    result = generation_jobs.create_generation_job(
        configured_settings(),
        user_id=USER_ID,
        project_id=None,
        job_type="video_generation",
        provider="test-provider",
        model="test-model",
        idempotency_key="test-idempotency-key",
        request_hash="a" * 64,
        request_snapshot={"prompt": "safe test prompt"},
        pricing_snapshot={"version": 1},
    )

    assert result.job_id == JOB_ID
    assert result.event_id == EVENT_ID
    assert result.created is True
    method, url, payload, headers = calls[0]
    assert method == "POST"
    assert url == "https://example.supabase.co/rest/v1/rpc/create_generation_job_with_outbox"
    assert payload["p_user_id"] == str(USER_ID)
    assert payload["p_request_hash"] == "a" * 64
    assert headers["apikey"] == "sb_secret_test_key"
    assert "Authorization" not in headers


def test_legacy_service_role_jwt_is_sent_in_both_headers(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{"job_id": str(JOB_ID), "event_id": None, "created": False}]),
            calls,
        ),
    )

    generation_jobs.create_generation_job(
        configured_settings(supabase_service_role_key="eyJlegacy-test"),
        user_id=USER_ID,
        project_id=None,
        job_type="ai_processing",
        provider="test-provider",
        model="test-model",
        idempotency_key="another-idempotency-key",
        request_hash="b" * 64,
    )

    headers = calls[0][3]
    assert headers["apikey"] == "eyJlegacy-test"
    assert headers["Authorization"] == "Bearer eyJlegacy-test"


def test_get_generation_job_always_filters_by_job_and_owner(monkeypatch):
    calls = []
    row = {
        "id": str(JOB_ID),
        "project_id": None,
        "job_type": "video_generation",
        "provider": "test-provider",
        "model": "test-model",
        "status": "queued",
        "attempt_count": 0,
        "max_attempts": 3,
        "last_error_code": None,
        "created_at": "2026-11-22T00:00:00Z",
        "updated_at": "2026-11-22T00:00:00Z",
        "started_at": None,
        "completed_at": None,
    }
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse([row]), calls),
    )

    result = generation_jobs.get_generation_job(
        configured_settings(),
        user_id=USER_ID,
        job_id=JOB_ID,
    )

    assert result == row
    method, url, params, headers = calls[0]
    assert method == "GET"
    assert url == "https://example.supabase.co/rest/v1/generation_jobs"
    assert params["id"] == f"eq.{JOB_ID}"
    assert params["user_id"] == f"eq.{USER_ID}"
    assert "request_snapshot" not in params["select"]
    assert "pricing_snapshot" not in params["select"]
    assert headers["apikey"] == "sb_secret_test_key"


def test_get_generation_job_returns_none_for_missing_or_other_owner(monkeypatch):
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse([]), []),
    )

    result = generation_jobs.get_generation_job(
        configured_settings(),
        user_id=USER_ID,
        job_id=JOB_ID,
    )

    assert result is None


def test_jobs_are_disabled_by_default_and_do_not_call_supabase(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Supabase must not be called while jobs are disabled")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)

    with pytest.raises(generation_jobs.GenerationJobsNotConfiguredError):
        generation_jobs.get_generation_job(
            Settings(),
            user_id=USER_ID,
            job_id=JOB_ID,
        )


def test_rpc_invalid_response_is_rejected(monkeypatch):
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse([]), []),
    )

    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="invalid response"):
        generation_jobs.create_generation_job(
            configured_settings(),
            user_id=USER_ID,
            project_id=None,
            job_type="ai_processing",
            provider="test-provider",
            model="test-model",
            idempotency_key="invalid-response-key",
            request_hash="c" * 64,
        )


def test_create_scene_generation_job_uses_scene_rpc_and_never_maps_studio_project_to_cloud_project(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{
                "job_id": str(JOB_ID),
                "event_id": str(EVENT_ID),
                "created": True,
            }]),
            calls,
        ),
    )

    scene_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    result = generation_jobs.create_scene_generation_job(
        configured_settings(),
        user_id=USER_ID,
        studio_scene_id=scene_id,
        job_type="image_generation",
        provider="provider-neutral",
        model="not-configured",
        idempotency_key="scene-idempotency-key-1",
        request_hash="f" * 64,
        request_snapshot={"prompt": "test scene prompt"},
    )

    assert result.job_id == JOB_ID
    assert result.created is True
    method, url, payload, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/rpc/create_scene_generation_job_with_outbox")
    assert payload["p_user_id"] == str(USER_ID)
    assert payload["p_studio_scene_id"] == str(scene_id)
    assert "p_project_id" not in payload
    assert headers["apikey"] == "sb_secret_test_key"


def test_scene_job_creation_is_disabled_without_server_flag(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Supabase must not be called while jobs are disabled")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    with pytest.raises(generation_jobs.GenerationJobsNotConfiguredError):
        generation_jobs.create_scene_generation_job(
            Settings(),
            user_id=USER_ID,
            studio_scene_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            job_type="image_generation",
            provider="provider-neutral",
            model="not-configured",
            idempotency_key="scene-idempotency-key-2",
            request_hash="a" * 64,
        )


def test_create_credited_generation_job_calls_atomic_rpc_and_parses_wallet_result(monkeypatch):
    calls = []
    hold_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{
                "job_id": str(JOB_ID),
                "event_id": str(EVENT_ID),
                "hold_id": str(hold_id),
                "available_credits": 40,
                "reserved_credits": 10,
                "created": True,
                "replayed": False,
            }]),
            calls,
        ),
    )

    quote = issue_pricing_quote(
        secret="test-signing-secret-with-at-least-32-bytes",
        catalog=PricingCatalog("test-v1", (
            PricingRule("image_generation", "provider-test", "model-test", 10, "image", 1, 3, Decimal("0.075")),
        )),
        user_id=USER_ID,
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        request_hash=canonical_request_hash({"prompt": "test"}),
        idempotency_key="credited-job-key-001",
        studio_scene_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        quantity=1,
    )
    result = generation_jobs.create_credited_generation_job(
        configured_settings(),
        user_id=USER_ID,
        project_id=None,
        studio_scene_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        idempotency_key="credited-job-key-001",
        request_hash=canonical_request_hash({"prompt": "test"}),
        request_snapshot={"prompt": "test"},
        quote_snapshot=quote.snapshot(),
    )

    assert result.job_id == JOB_ID
    assert result.event_id == EVENT_ID
    assert result.hold_id == hold_id
    assert result.available_credits == 40
    assert result.reserved_credits == 10
    assert result.created is True
    assert result.replayed is False
    method, url, payload, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/rpc/create_credited_generation_job_with_outbox")
    assert payload["p_user_id"] == str(USER_ID)
    assert payload["p_studio_scene_id"] == "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    assert payload["p_project_id"] is None
    assert payload["p_quote_snapshot"]["price_version"] == "test-v1"
    assert payload["p_credit_amount"] == 10
    assert headers["apikey"] == "sb_secret_test_key"


def test_create_credited_generation_job_rejects_tampered_quote_before_network(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Invalid signed quote must be rejected before network access")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    quote = issue_pricing_quote(
        secret="test-signing-secret-with-at-least-32-bytes",
        catalog=PricingCatalog("test-v1", (
            PricingRule("image_generation", "provider-test", "model-test", 10, "image", 1, 1, Decimal("0.075")),
        )),
        user_id=USER_ID,
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        request_hash="b" * 64,
        idempotency_key="credited-job-key-002",
    ).snapshot()
    quote["amount"] = 1
    quote["maximum_authorized_charge"] = 1
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="quote is invalid"):
        generation_jobs.create_credited_generation_job(
            configured_settings(),
            user_id=USER_ID,
            project_id=None,
            studio_scene_id=None,
            job_type="image_generation",
            provider="provider-test",
            model="model-test",
            idempotency_key="credited-job-key-002",
            request_hash="b" * 64,
            request_snapshot={},
            quote_snapshot=quote,
        )


def test_create_credited_generation_job_rejects_quote_for_another_request(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Mismatched quote must be rejected before network access")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    quote = issue_pricing_quote(
        secret="test-signing-secret-with-at-least-32-bytes",
        catalog=PricingCatalog("test-v1", (
            PricingRule("image_generation", "provider-test", "model-test", 10, "image", 1, 1, Decimal("0.075")),
        )),
        user_id=USER_ID,
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        request_hash="c" * 64,
        idempotency_key="credited-job-key-003",
    ).snapshot()
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="quote is invalid"):
        generation_jobs.create_credited_generation_job(
            configured_settings(),
            user_id=USER_ID,
            project_id=None,
            studio_scene_id=None,
            job_type="image_generation",
            provider="provider-test",
            model="model-test",
            idempotency_key="credited-job-key-003",
            request_hash="d" * 64,
            request_snapshot={},
            quote_snapshot=quote,
        )

def test_create_credited_generation_job_remains_disabled_by_default(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Credited generation must remain disabled")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    with pytest.raises(generation_jobs.GenerationJobsNotConfiguredError):
        generation_jobs.create_credited_generation_job(
            Settings(),
            user_id=USER_ID,
            project_id=None,
            studio_scene_id=None,
            job_type="image_generation",
            provider="provider-test",
            model="model-test",
            idempotency_key="credited-job-key-004",
            request_hash="c" * 64,
            request_snapshot={},
            quote_snapshot={},
        )


def test_store_pricing_quote_persists_owner_key_and_returns_original_snapshot(monkeypatch):
    calls = []
    quote = issue_pricing_quote(
        secret="test-signing-secret-with-at-least-32-bytes",
        catalog=PricingCatalog("catalog-v1", (
            PricingRule("image_generation", "provider-test", "model-test", 10, "image", 1, 1, Decimal("0.075")),
        )),
        user_id=USER_ID,
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        request_hash=canonical_request_hash({"prompt": "persist me"}),
        idempotency_key="persisted-quote-key-001",
        studio_scene_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
    ).snapshot()
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{
                "quote_snapshot": quote,
                "created": True,
                "expired": False,
            }]),
            calls,
        ),
    )
    result = generation_jobs.store_pricing_quote(
        configured_settings(),
        user_id=USER_ID,
        idempotency_key="persisted-quote-key-001",
        request_hash=quote["request_hash"],
        job_type="image_generation",
        provider="provider-test",
        model="model-test",
        project_id=None,
        studio_scene_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        quote_snapshot=quote,
    )
    assert result.snapshot == quote
    assert result.created is True
    assert result.expired is False
    method, url, payload, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/rpc/store_generation_pricing_quote")
    assert payload["p_user_id"] == str(USER_ID)
    assert payload["p_idempotency_key"] == "persisted-quote-key-001"
    assert payload["p_quote_id"] == quote["quote_id"]
    assert headers["apikey"] == "sb_secret_test_key"


def test_store_pricing_quote_rejects_invalid_rpc_shape(monkeypatch):
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{"quote_snapshot": [], "created": "yes", "expired": False}]),
            [],
        ),
    )
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="incomplete metadata"):
        generation_jobs.store_pricing_quote(
            configured_settings(),
            user_id=USER_ID,
            idempotency_key="persisted-quote-key-002",
            request_hash="a" * 64,
            job_type="image_generation",
            provider="provider-test",
            model="model-test",
            project_id=None,
            studio_scene_id=None,
            quote_snapshot={"quote_id": str(JOB_ID), "expires_at": "2026-11-22T00:00:00+00:00"},
        )


def test_store_pricing_quote_maps_database_idempotency_conflict(monkeypatch):
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse([], status_code=400), []),
    )
    with pytest.raises(generation_jobs.GenerationPricingQuoteConflictError):
        generation_jobs.store_pricing_quote(
            configured_settings(),
            user_id=USER_ID,
            idempotency_key="persisted-quote-key-003",
            request_hash="a" * 64,
            job_type="image_generation",
            provider="provider-test",
            model="model-test",
            project_id=None,
            studio_scene_id=None,
            quote_snapshot={
                "quote_id": str(JOB_ID),
                "expires_at": "2026-11-22T00:00:00+00:00",
            },
        )


def test_request_generation_job_cancellation_uses_verified_owner_bridge(monkeypatch):
    calls = []
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(
            FakeResponse([{
                "job_status": "cancel_requested",
                "cancellation_action": "awaiting_worker_confirmation",
                "replayed": False,
            }]),
            calls,
        ),
    )

    result = generation_jobs.request_generation_job_cancellation(
        configured_settings(), user_id=USER_ID, job_id=JOB_ID
    )

    assert result.job_status == "cancel_requested"
    assert result.cancellation_action == "awaiting_worker_confirmation"
    assert result.replayed is False
    method, url, payload, headers = calls[0]
    assert method == "POST"
    assert url.endswith("/rpc/request_generation_job_cancellation_for_owner")
    assert payload == {"p_job_id": str(JOB_ID), "p_user_id": str(USER_ID)}
    assert headers["apikey"] == "sb_secret_test_key"
    assert "Authorization" not in headers


def test_request_generation_job_cancellation_maps_owner_scoped_not_found(monkeypatch):
    monkeypatch.setattr(
        generation_jobs.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse([], status_code=404), []),
    )

    with pytest.raises(generation_jobs.GenerationJobNotFoundError):
        generation_jobs.request_generation_job_cancellation(
            configured_settings(), user_id=USER_ID, job_id=JOB_ID
        )


def test_request_generation_job_cancellation_remains_disabled_by_default(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Cancellation RPC must not be called while generation jobs are disabled")

    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    with pytest.raises(generation_jobs.GenerationJobsNotConfiguredError):
        generation_jobs.request_generation_job_cancellation(
            Settings(), user_id=USER_ID, job_id=JOB_ID
        )
