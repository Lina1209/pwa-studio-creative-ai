from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.services import ai_admission


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json, headers):
        self.calls.append((url, json, headers))
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def make_settings():
    return Settings(
        supabase_url="https://project.example.supabase.co",
        supabase_service_role_key="eyJ.test.service-role",
    )


def test_reserve_and_finish_use_service_role_and_server_limits(monkeypatch):
    client = FakeClient([
        FakeResponse({"admitted": True, "duplicate": False, "state": "reserved"}),
        FakeResponse(True),
    ])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)
    user_id = uuid4()

    reservation = ai_admission.reserve_ai_request(
        make_settings(), user_id=user_id, endpoint="chat"
    )
    ai_admission.finish_ai_request(make_settings(), reservation, completed=True)

    reserve_url, reserve_body, headers = client.calls[0]
    finish_url, finish_body, _ = client.calls[1]
    assert reserve_url.endswith("/rpc/reserve_ai_request")
    assert reserve_body["p_user_id"] == str(user_id)
    assert reserve_body["p_endpoint"] == "chat"
    assert reserve_body["p_max_per_minute"] == 10
    assert reserve_body["p_max_concurrent"] == 2
    assert reserve_body["p_max_global_concurrent"] == 16
    assert headers["Authorization"].startswith("Bearer ")
    assert finish_url.endswith("/rpc/finish_ai_request")
    assert finish_body["p_request_id"] == str(reservation.request_id)
    assert finish_body["p_outcome"] == "completed"


def test_rate_limit_response_becomes_retryable_rejection(monkeypatch):
    client = FakeClient([
        FakeResponse({"admitted": False, "reason": "rate_limited", "retry_after_seconds": 60})
    ])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)

    with pytest.raises(ai_admission.AIAdmissionRejected) as error:
        ai_admission.reserve_ai_request(
            make_settings(), user_id=uuid4(), endpoint="prompts"
        )

    assert error.value.reason == "rate_limited"
    assert error.value.retry_after_seconds == 60


def test_concurrency_limit_response_is_rejected(monkeypatch):
    client = FakeClient([
        FakeResponse({"admitted": False, "reason": "concurrency_limited", "retry_after_seconds": 10})
    ])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)

    with pytest.raises(ai_admission.AIAdmissionRejected) as error:
        ai_admission.reserve_ai_request(
            make_settings(), user_id=uuid4(), endpoint="chat"
        )

    assert error.value.reason == "concurrency_limited"


def test_missing_supabase_credentials_fail_closed():
    with pytest.raises(ai_admission.AIAdmissionUnavailable):
        ai_admission.reserve_ai_request(
            Settings(supabase_url=None, supabase_service_role_key=None),
            user_id=uuid4(),
            endpoint="chat",
        )


def test_duplicate_reservation_never_launches_second_provider_call(monkeypatch):
    client = FakeClient([
        FakeResponse({"admitted": True, "duplicate": True, "state": "reserved"})
    ])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)

    with pytest.raises(ai_admission.AIAdmissionRejected) as error:
        ai_admission.reserve_ai_request(
            make_settings(), user_id=uuid4(), endpoint="chat"
        )

    assert error.value.reason == "duplicate_request"


def test_invalid_admission_response_fails_closed(monkeypatch):
    client = FakeClient([FakeResponse({"unexpected": True})])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)

    with pytest.raises(ai_admission.AIAdmissionUnavailable):
        ai_admission.reserve_ai_request(
            make_settings(), user_id=uuid4(), endpoint="chat"
        )


def test_global_concurrency_limit_response_is_rejected(monkeypatch):
    client = FakeClient([
        FakeResponse({"admitted": False, "reason": "global_concurrency_limited", "retry_after_seconds": 10})
    ])
    monkeypatch.setattr(ai_admission.httpx, "Client", lambda timeout: client)

    with pytest.raises(ai_admission.AIAdmissionRejected) as error:
        ai_admission.reserve_ai_request(
            make_settings(), user_id=uuid4(), endpoint="chat"
        )

    assert error.value.reason == "global_concurrency_limited"
