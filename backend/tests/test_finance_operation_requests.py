from decimal import Decimal
from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import finance_operation_requests as service


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
TARGET = UUID("22222222-2222-4222-8222-222222222222")
REQUEST = UUID("33333333-3333-4333-8333-333333333333")
IDEMPOTENCY = UUID("44444444-4444-4444-8444-444444444444")
SETTINGS = Settings(supabase_url="https://example.test", supabase_service_role_key="server-secret")


def test_create_request_uses_verified_actor_and_idempotent_server_rpc(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or str(REQUEST))
    result = service.create_finance_operation_request(
        SETTINGS, requester_id=ACTOR, request_type="credit_compensation",
        target_user_id=TARGET, amount=Decimal("12"), currency_code="CRD",
        scope_key="tenant-a", reason="Approved support case",
        idempotency_key=IDEMPOTENCY,
    )
    assert result == REQUEST
    name, payload = calls[0]
    assert name == "create_finance_operation_request"
    assert payload["p_requester_id"] == str(ACTOR)
    assert payload["p_target_user_id"] == str(TARGET)
    assert payload["p_amount"] == "12"
    assert payload["p_idempotency_key"] == str(IDEMPOTENCY)


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("0.00001")])
def test_create_request_rejects_invalid_amount_before_rpc(monkeypatch, amount):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.create_finance_operation_request(
            SETTINGS, requester_id=ACTOR, request_type="billing_refund",
            target_user_id=TARGET, amount=amount, currency_code="USD",
            scope_key="tenant-a", reason="Refund review",
            idempotency_key=IDEMPOTENCY,
        )
    assert called == []


def test_create_request_rejects_untrusted_or_noncanonical_fields(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    for values in [
        {"request_type": "owner"},
        {"currency_code": "crd"},
        {"scope_key": " tenant-a"},
        {"reason": " "},
    ]:
        kwargs = {
            "request_type": "credit_compensation", "currency_code": "CRD",
            "scope_key": "tenant-a", "reason": "Review request",
        }
        kwargs.update(values)
        with pytest.raises(ValueError):
            service.create_finance_operation_request(
                SETTINGS, requester_id=ACTOR, target_user_id=TARGET,
                amount=Decimal("1"), idempotency_key=IDEMPOTENCY, **kwargs,
            )
    assert called == []


def test_decision_and_cancellation_use_server_actor_and_exact_request(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or str(REQUEST))
    assert service.decide_finance_operation_request(
        SETTINGS, request_id=REQUEST, actor_id=TARGET,
        decision="approve", reason="Independently reviewed",
    ) == REQUEST
    assert service.cancel_finance_operation_request(
        SETTINGS, request_id=REQUEST, actor_id=ACTOR, reason="Requester cancelled",
    ) == REQUEST
    assert calls[0][0] == "decide_finance_operation_request"
    assert calls[0][1]["p_actor_id"] == str(TARGET)
    assert calls[1][0] == "cancel_finance_operation_request"
    assert calls[1][1]["p_actor_id"] == str(ACTOR)


def test_invalid_decisions_and_mismatched_rpc_ids_fail_closed(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True) or str(REQUEST))
    with pytest.raises(ValueError):
        service.decide_finance_operation_request(
            SETTINGS, request_id=REQUEST, actor_id=TARGET,
            decision="execute", reason="Must not execute",
        )
    assert called == []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: str(TARGET))
    with pytest.raises(service.FinanceRequestUnavailable):
        service.decide_finance_operation_request(
            SETTINGS, request_id=REQUEST, actor_id=TARGET,
            decision="reject", reason="Decision",
        )

def test_credit_compensation_requires_whole_credits_and_cash_refund_requires_currency(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True) or str(REQUEST))
    invalid = [
        ("credit_compensation", Decimal("1.5"), "CRD"),
        ("credit_compensation", Decimal("1"), "KZT"),
        ("billing_refund", Decimal("1"), "CRD"),
    ]
    for request_type, amount, currency in invalid:
        with pytest.raises(ValueError):
            service.create_finance_operation_request(
                SETTINGS, requester_id=ACTOR, request_type=request_type,
                target_user_id=TARGET, amount=amount, currency_code=currency,
                scope_key="user:" + str(TARGET), reason="Unit mismatch",
                idempotency_key=IDEMPOTENCY,
            )
    assert called == []


def test_finance_request_cannot_target_the_requester_account(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.create_finance_operation_request(
            SETTINGS, requester_id=ACTOR, request_type="credit_compensation",
            target_user_id=ACTOR, amount=Decimal("1"), currency_code="CRD",
            scope_key="user:" + str(ACTOR), reason="Self-target attempt",
            idempotency_key=IDEMPOTENCY,
        )
    assert called == []
