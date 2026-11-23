from uuid import UUID
import hashlib
import pytest

from app.core.config import Settings
from app.services import payment_orders as service

USER = UUID("11111111-1111-4111-8111-111111111111")
ORDER = UUID("22222222-2222-4222-8222-222222222222")
IDEMPOTENCY = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
SETTINGS = Settings(supabase_url="https://example.test", supabase_service_role_key="server-secret")


def test_create_payment_order_calls_server_rpc_with_minor_units(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "payment_order_id": str(ORDER), "replayed": False,
    }])
    result = service.create_payment_order(
        SETTINGS, user_id=USER, provider_code="examplepay",
        merchant_reference="order-ref-123", idempotency_key=IDEMPOTENCY,
        amount_minor=1250, currency_code="KZT", description="Monthly plan",
    )
    assert result == {"payment_order_id": ORDER, "replayed": False}
    assert calls[0][0] == "create_payment_order"
    assert calls[0][1]["p_amount_minor"] == 1250
    assert calls[0][1]["p_currency_code"] == "KZT"


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, "100"])
def test_create_payment_order_rejects_invalid_amount_before_rpc(monkeypatch, amount):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.create_payment_order(
            SETTINGS, user_id=USER, provider_code="examplepay",
            merchant_reference="order-ref-123", idempotency_key=IDEMPOTENCY,
            amount_minor=amount, currency_code="KZT", description="Plan",
        )
    assert called == []


def test_webhook_event_requires_verified_signature_before_rpc(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.record_verified_provider_event(
            SETTINGS, provider_code="examplepay", provider_event_id="evt-123",
            payment_order_id=ORDER, event_type="payment.succeeded",
            raw_body=b'{"paid":true}', signature_verified=False,
            amount_minor=1250, currency_code="KZT", provider_payment_id="pay-123",
        )
    assert called == []


def test_verified_webhook_persists_raw_body_digest_and_replay_flag(monkeypatch):
    body = b'{"id":"evt-123","status":"succeeded"}'
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "event_id": str(EVENT), "replayed": True, "resulting_status": "succeeded",
    }])
    result = service.record_verified_provider_event(
        SETTINGS, provider_code="examplepay", provider_event_id="evt-123",
        payment_order_id=ORDER, event_type="payment.succeeded",
        raw_body=body, signature_verified=True, amount_minor=1250,
        currency_code="KZT", provider_payment_id="pay-123",
    )
    assert result == {"event_id": EVENT, "replayed": True, "resulting_status": "succeeded"}
    assert calls[0][0] == "record_verified_payment_provider_event"
    assert calls[0][1]["p_payload_sha256"] == hashlib.sha256(body).hexdigest()


def test_webhook_rejects_unknown_normalized_event(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.record_verified_provider_event(
            SETTINGS, provider_code="examplepay", provider_event_id="evt-123",
            payment_order_id=ORDER, event_type="client.redirect",
            raw_body=b"redirect", signature_verified=True, amount_minor=1250,
            currency_code="KZT", provider_payment_id="pay-123",
        )
    assert called == []


def test_credit_pack_order_uses_approved_version_rpc_and_no_client_price(monkeypatch):
    version = UUID("55555555-5555-4555-8555-555555555555")
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "payment_order_id": str(ORDER), "replayed": False,
    }])
    result = service.create_credit_pack_payment_order(
        SETTINGS, user_id=USER, provider_code="examplepay",
        merchant_reference="credit-pack-123", idempotency_key=IDEMPOTENCY,
        credit_pack_version_id=version,
    )
    assert result == {"payment_order_id": ORDER, "replayed": False}
    assert calls[0][0] == "create_credit_pack_payment_order"
    assert calls[0][1]["p_credit_pack_version_id"] == str(version)
    assert "p_amount_minor" not in calls[0][1]
    assert "p_currency_code" not in calls[0][1]


def test_subscription_order_uses_approved_plan_version_rpc(monkeypatch):
    version = UUID("66666666-6666-4666-8666-666666666666")
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "payment_order_id": str(ORDER), "replayed": True,
    }])
    result = service.create_subscription_payment_order(
        SETTINGS, user_id=USER, provider_code="examplepay",
        merchant_reference="subscription-123", idempotency_key=IDEMPOTENCY,
        approved_plan_version_id=version, metadata={"source": "settings"},
    )
    assert result == {"payment_order_id": ORDER, "replayed": True}
    assert calls[0][0] == "create_subscription_payment_order"
    assert calls[0][1]["p_approved_plan_version_id"] == str(version)
    assert calls[0][1]["p_metadata"] == {"source": "settings"}
    assert "p_amount_minor" not in calls[0][1]


def test_snapshot_purchase_rejects_non_uuid_product_version_before_rpc(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.create_credit_pack_payment_order(
            SETTINGS, user_id=USER, provider_code="examplepay",
            merchant_reference="credit-pack-123", idempotency_key=IDEMPOTENCY,
            credit_pack_version_id="not-a-uuid",
        )
    assert called == []
