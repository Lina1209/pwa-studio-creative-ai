import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import credit_service

USER_ID = "11111111-1111-4111-8111-111111111111"
RESERVATION_ID = "22222222-2222-4222-8222-222222222222"


def _settings():
    return Settings(supabase_url="https://example.supabase.co",
                    supabase_service_role_key="sb_secret_test")


def test_reserve_credits_calls_atomic_rpc_with_server_payload(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "reserved", "reservation_id": RESERVATION_ID}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(credit_service.httpx, "post", fake_post)
    result = credit_service.reserve_credits(
        _settings(), user_id=USER_ID, idempotency_key="request-123",
        operation_code="cinema.render", pricing_version=2, amount=75,
    )
    assert result["status"] == "reserved"
    assert seen["url"].endswith("/rpc/reserve_user_credits")
    assert seen["json"]["p_amount"] == 75
    assert seen["json"]["p_pricing_version"] == 2
    assert "Authorization" not in seen["headers"]
    assert seen["headers"]["apikey"] == "sb_secret_test"
    assert seen["timeout"] == 8.0


def test_grant_rejects_untrusted_source_and_invalid_amount():
    with pytest.raises(ValueError):
        credit_service.grant_credits(
            _settings(), user_id=USER_ID, amount=50, source="client_input",
            source_reference="order-123",
        )
    with pytest.raises(ValueError):
        credit_service.grant_credits(
            _settings(), user_id=USER_ID, amount=True, source="purchase",
            source_reference="order-123",
        )


def test_reserve_rejects_invalid_identifiers_and_pricing():
    with pytest.raises(ValueError):
        credit_service.reserve_credits(
            _settings(), user_id="not-a-uuid", idempotency_key="request-123",
            operation_code="cinema.render", pricing_version=1, amount=10,
        )
    with pytest.raises(ValueError):
        credit_service.reserve_credits(
            _settings(), user_id=USER_ID, idempotency_key="request-123",
            operation_code="Cinema Render", pricing_version=1, amount=10,
        )
    with pytest.raises(ValueError):
        credit_service.reserve_credits(
            _settings(), user_id=USER_ID, idempotency_key="request-123",
            operation_code="cinema.render", pricing_version=0, amount=10,
        )


def test_settle_allows_zero_capture_and_calls_correct_rpc(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "settled", "captured_credits": 0}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(credit_service.httpx, "post", fake_post)
    result = credit_service.settle_reservation(
        _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID, capture_amount=0
    )
    assert result["status"] == "settled"
    assert seen["url"].endswith("/rpc/settle_user_credit_reservation")
    assert seen["json"]["p_capture_amount"] == 0


def test_reconciliation_keeps_uncertain_reservation_pending(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "reconciliation_required", "idempotent_replay": False}

    monkeypatch.setattr(credit_service.httpx, "post", lambda *a, **k: Response())
    result = credit_service.mark_reconciliation_required(
        _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID
    )
    assert result["status"] == "reconciliation_required"


def test_credit_rpc_fails_closed_on_storage_error(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(credit_service.httpx, "post", fail)
    with pytest.raises(HTTPException) as exc:
        credit_service.release_reservation(
            _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID
        )
    assert exc.value.status_code == 503


def test_credit_rpc_fails_closed_without_configuration():
    with pytest.raises(HTTPException) as exc:
        credit_service.release_reservation(
            Settings(), user_id=USER_ID, reservation_id=RESERVATION_ID
        )
    assert exc.value.status_code == 503


def test_credit_rpc_rejects_unexpected_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return [{"status": "released"}]

    monkeypatch.setattr(credit_service.httpx, "post", lambda *a, **k: Response())
    with pytest.raises(HTTPException) as exc:
        credit_service.release_reservation(
            _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID
        )
    assert exc.value.status_code == 503
