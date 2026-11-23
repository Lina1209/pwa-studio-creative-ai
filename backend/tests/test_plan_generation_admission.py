from decimal import Decimal
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import generation_jobs
from app.services.pricing_service import (
    PricingCatalog, PricingRule, canonical_request_hash, issue_pricing_quote,
)


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


def configured_settings():
    return Settings(
        supabase_url="https://example.supabase.co/",
        supabase_service_role_key="sb_secret_test_key",
        generation_jobs_enabled=True,
        pricing_quote_signing_secret="test-signing-secret-with-at-least-32-bytes",
    )


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
EVENT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
HOLD_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SCENE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def _quote(job_type="image_generation", quantity=2):
    snapshot = {"prompt": "test plan admission", "quantity": quantity}
    request_hash = canonical_request_hash(snapshot)
    catalog = PricingCatalog("test-v1", (
        PricingRule(job_type, "provider-test", "model-test", 10, "unit", 1, 5, Decimal("0.02")),
    ))
    quote = issue_pricing_quote(
        secret="test-signing-secret-with-at-least-32-bytes",
        catalog=catalog,
        user_id=USER_ID,
        job_type=job_type,
        provider="provider-test",
        model="model-test",
        request_hash=request_hash,
        idempotency_key="plan-admission-key-001",
        studio_scene_id=SCENE_ID,
        quantity=quantity,
    )
    return snapshot, request_hash, quote.snapshot()


def _response_row(features):
    return {
        "job_id": str(JOB_ID),
        "event_id": str(EVENT_ID),
        "hold_id": str(HOLD_ID),
        "available_credits": 80,
        "reserved_credits": 20,
        "created": True,
        "replayed": False,
        "quota_reservations": [
            {
                "reservation_id": str(UUID(int=i + 1)),
                "feature_key": feature,
                "feature_limit": 10,
                "used_units": 2,
                "remaining_units": 8,
                "status": "reserved",
                "replayed": False,
            }
            for i, feature in enumerate(features)
        ],
    }


def test_plan_credited_admission_uses_atomic_rpc_and_verifies_quote(monkeypatch):
    calls = []
    features = ["daily_image_generations", "monthly_image_generations"]
    monkeypatch.setattr(
        generation_jobs.httpx, "Client",
        lambda timeout: FakeClient(FakeResponse([_response_row(features)]), calls),
    )
    snapshot, request_hash, quote = _quote()
    result = generation_jobs.create_plan_credited_generation_job(
        configured_settings(), user_id=USER_ID, project_id=None,
        studio_scene_id=SCENE_ID, job_type="image_generation",
        provider="provider-test", model="model-test",
        idempotency_key="plan-admission-key-001",
        request_hash=request_hash, request_snapshot=snapshot, quote_snapshot=quote,
    )
    assert result.job_id == JOB_ID
    assert result.hold_id == HOLD_ID
    assert result.available_credits == 80
    assert {q.feature_key for q in result.quota_reservations} == set(features)
    _, url, payload, headers = calls[0]
    assert url.endswith("/rpc/create_plan_credited_generation_job_with_outbox")
    assert payload["p_credit_amount"] == 20
    assert payload["p_quote_snapshot"]["amount"] == 20
    assert headers["apikey"] == "sb_secret_test_key"


def test_plan_credited_admission_rejects_tampered_quote_before_network(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("No network call is allowed for a tampered quote")
    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    snapshot, request_hash, quote = _quote()
    quote["amount"] = 1
    quote["maximum_authorized_charge"] = 1
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="quote is invalid"):
        generation_jobs.create_plan_credited_generation_job(
            configured_settings(), user_id=USER_ID, project_id=None,
            studio_scene_id=SCENE_ID, job_type="image_generation",
            provider="provider-test", model="model-test",
            idempotency_key="plan-admission-key-001",
            request_hash=request_hash, request_snapshot=snapshot, quote_snapshot=quote,
        )


def test_plan_credited_admission_rejects_missing_quota_dimension(monkeypatch):
    features = ["daily_image_generations"]
    monkeypatch.setattr(
        generation_jobs.httpx, "Client",
        lambda timeout: FakeClient(FakeResponse([_response_row(features)]), []),
    )
    snapshot, request_hash, quote = _quote()
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="inconsistent metadata"):
        generation_jobs.create_plan_credited_generation_job(
            configured_settings(), user_id=USER_ID, project_id=None,
            studio_scene_id=SCENE_ID, job_type="image_generation",
            provider="provider-test", model="model-test",
            idempotency_key="plan-admission-key-001",
            request_hash=request_hash, request_snapshot=snapshot, quote_snapshot=quote,
        )


def test_plan_credited_admission_rejects_unmapped_job_type_before_network(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Unmapped job type must fail before network access")
    monkeypatch.setattr(generation_jobs.httpx, "Client", unexpected_client)
    snapshot = {"prompt": "test", "quantity": 1}
    request_hash = canonical_request_hash(snapshot)
    with pytest.raises(generation_jobs.GenerationJobsServiceError, match="no approved"):
        generation_jobs.create_plan_credited_generation_job(
            configured_settings(), user_id=USER_ID, project_id=None,
            studio_scene_id=SCENE_ID, job_type="media_export",
            provider="provider-test", model="model-test",
            idempotency_key="plan-admission-key-001",
            request_hash=request_hash, request_snapshot=snapshot, quote_snapshot={},
        )
