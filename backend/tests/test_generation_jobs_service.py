from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import generation_jobs


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
