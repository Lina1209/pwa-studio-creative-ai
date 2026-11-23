from uuid import UUID
import hashlib
import pytest

from app.core.config import Settings
from app.services import payment_orders as service
from app.services.payment_provider_contracts import (
    PaymentProviderAdapterRegistry,
    PaymentProviderNotConfigured,
    PaymentProviderSecretStore,
    VerifiedProviderEvent,
)

USER = UUID("11111111-1111-4111-8111-111111111111")
ORDER = UUID("22222222-2222-4222-8222-222222222222")
IDEMPOTENCY = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
SETTINGS = Settings(supabase_url="https://example.test", supabase_service_role_key="server-secret", payment_provider_runtime_enabled=True)


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


class FakeVerifiedAdapter:
    provider_code = "examplepay"

    def __init__(self, event=None, error=None):
        self.event = event or VerifiedProviderEvent(
            provider_event_id="evt-123",
            payment_order_id=ORDER,
            event_type="payment.succeeded",
            amount_minor=1250,
            currency_code="KZT",
            provider_payment_id="pay-123",
        )
        self.error = error
        self.received_body = None
        self.received_headers = None

    def validate_configuration(self, settings, secrets):
        if getattr(settings, "test_adapter_ready", True) is not True:
            raise ValueError("adapter configuration is incomplete")

    def verify_webhook(self, *, raw_body, headers):
        self.received_body = raw_body
        self.received_headers = headers
        if self.error:
            raise self.error
        return self.event


def test_webhook_signature_failure_stops_before_privileged_rpc(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    adapter = FakeVerifiedAdapter(error=ValueError("invalid provider signature"))
    with pytest.raises(ValueError, match="invalid provider signature"):
        service.record_verified_provider_event(
            SETTINGS, registry=PaymentProviderAdapterRegistry([adapter], enabled=True, settings=Settings(payment_provider_runtime_enabled=True)), provider_code="examplepay", raw_body=b'{"paid":true}',
            headers={"x-signature": "invalid"},
        )
    assert called == []
    assert adapter.received_body == b'{"paid":true}'


def test_verified_webhook_persists_raw_body_digest_and_replay_flag(monkeypatch):
    body = b'{"id":"evt-123","status":"succeeded"}'
    adapter = FakeVerifiedAdapter()
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "event_id": str(EVENT), "replayed": True, "resulting_status": "succeeded",
    }])
    result = service.record_verified_provider_event(
        SETTINGS, registry=PaymentProviderAdapterRegistry([adapter], enabled=True, settings=SETTINGS), provider_code="examplepay", raw_body=body,
        headers={"x-signature": "valid"},
    )
    assert result == {"event_id": EVENT, "replayed": True, "resulting_status": "succeeded"}
    assert adapter.received_body == body
    assert calls[0][0] == "record_verified_payment_provider_event"
    assert calls[0][1]["p_payload_sha256"] == hashlib.sha256(body).hexdigest()
    assert calls[0][1]["p_amount_minor"] == 1250
    assert calls[0][1]["p_currency_code"] == "KZT"


def test_webhook_rejects_unknown_normalized_event_before_rpc(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    adapter = FakeVerifiedAdapter(event=VerifiedProviderEvent(
        provider_event_id="evt-123", payment_order_id=ORDER,
        event_type="client.redirect", amount_minor=1250,
        currency_code="KZT", provider_payment_id="pay-123",
    ))
    with pytest.raises(ValueError, match="Unsupported normalized"):
        service.record_verified_provider_event(
            SETTINGS, registry=PaymentProviderAdapterRegistry([adapter], enabled=True, settings=SETTINGS), provider_code="examplepay", raw_body=b"redirect", headers={},
        )
    assert called == []


def test_webhook_rejects_non_verified_adapter_result_before_rpc(monkeypatch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    adapter = FakeVerifiedAdapter(event={"event_type": "payment.succeeded"})
    with pytest.raises(ValueError, match="did not return verified event facts"):
        service.record_verified_provider_event(
            SETTINGS, registry=PaymentProviderAdapterRegistry([adapter], enabled=True, settings=SETTINGS), provider_code="examplepay", raw_body=b"payload", headers={},
        )
    assert called == []



def test_provider_registry_is_empty_by_default_and_fails_closed():
    registry = PaymentProviderAdapterRegistry()
    assert registry.provider_codes == ()
    with pytest.raises(PaymentProviderNotConfigured):
        registry.get("examplepay")


def test_provider_registry_rejects_duplicate_adapter_identity():
    adapter = FakeVerifiedAdapter()
    with pytest.raises(ValueError, match="Duplicate"):
        PaymentProviderAdapterRegistry([adapter, adapter])


def test_provider_registry_does_not_select_provider_from_unknown_code():
    registry = PaymentProviderAdapterRegistry([FakeVerifiedAdapter()], enabled=True, settings=Settings(payment_provider_runtime_enabled=True))
    with pytest.raises(PaymentProviderNotConfigured):
        registry.get("otherpay")



def test_provider_registry_cannot_enable_without_server_runtime_flag():
    with pytest.raises(PaymentProviderNotConfigured, match="runtime is disabled"):
        PaymentProviderAdapterRegistry(
            [FakeVerifiedAdapter()], enabled=True,
            settings=Settings(payment_provider_runtime_enabled=False),
        )


def test_provider_registry_validates_adapter_configuration_before_registration():
    class IncompleteAdapter(FakeVerifiedAdapter):
        def validate_configuration(self, settings, secrets):
            raise ValueError("missing webhook secret")

    with pytest.raises(ValueError, match="missing webhook secret"):
        PaymentProviderAdapterRegistry(
            [IncompleteAdapter()], enabled=True,
            settings=Settings(payment_provider_runtime_enabled=True),
        )


def test_secret_store_reads_only_named_server_environment_secret(monkeypatch):
    store = PaymentProviderSecretStore()
    monkeypatch.setenv("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET", "secret-value")
    assert store.get_required_secret("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET") == "secret-value"


@pytest.mark.parametrize("name", ["WEBHOOK_SECRET", "PAYMENT_PROVIDER_SECRET", "PAYMENT_PROVIDER_X_SECRET/"])
def test_secret_store_rejects_unapproved_environment_variable_names(name):
    with pytest.raises(ValueError, match="secret reference is invalid"):
        PaymentProviderSecretStore().get_required_secret(name)


def test_secret_store_fails_closed_for_missing_or_blank_secret(monkeypatch):
    store = PaymentProviderSecretStore()
    monkeypatch.delenv("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET", raising=False)
    with pytest.raises(PaymentProviderNotConfigured, match="unavailable"):
        store.get_required_secret("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET")
    monkeypatch.setenv("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET", " ")
    with pytest.raises(PaymentProviderNotConfigured, match="unavailable"):
        store.get_required_secret("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET")


def test_secret_store_error_never_includes_secret_value(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET", "")
    with pytest.raises(PaymentProviderNotConfigured) as error:
        PaymentProviderSecretStore().get_required_secret("PAYMENT_PROVIDER_EXAMPLEPAY_WEBHOOK_SECRET")
    assert "secret-value" not in str(error.value)


def test_disabled_registry_rejects_even_registered_provider():
    registry = PaymentProviderAdapterRegistry([FakeVerifiedAdapter()])
    with pytest.raises(PaymentProviderNotConfigured, match="runtime is disabled"):
        registry.get("examplepay")


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


def test_claim_payment_fulfillment_parses_database_lease(monkeypatch):
    fulfillment = UUID("77777777-7777-4777-8777-777777777777")
    lease = UUID("88888888-8888-4888-8888-888888888888")
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "fulfillment_id": str(fulfillment), "payment_order_id": str(ORDER),
        "user_id": str(USER), "provider_code": "examplepay",
        "amount_minor": 99000, "currency_code": "KZT", "attempt_count": 1,
        "lease_token": str(lease), "lease_expires_at": "2026-11-23T10:00:00+00:00",
    }])
    result = service.claim_payment_fulfillment(SETTINGS, lease_seconds=180, batch_size=5)
    assert result[0]["fulfillment_id"] == fulfillment
    assert result[0]["lease_token"] == lease
    assert calls[0][0] == "claim_payment_fulfillment"
    assert calls[0][1] == {"p_lease_seconds": 180, "p_batch_size": 5}


@pytest.mark.parametrize("batch", [0, 21, True, 1.5])
def test_claim_payment_fulfillment_rejects_unbounded_batch(monkeypatch, batch):
    called = []
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: called.append(True))
    with pytest.raises(ValueError):
        service.claim_payment_fulfillment(SETTINGS, batch_size=batch)
    assert called == []


def test_fulfill_payment_order_uses_fencing_token_and_returns_entitlement(monkeypatch):
    fulfillment = UUID("77777777-7777-4777-8777-777777777777")
    lease = UUID("88888888-8888-4888-8888-888888888888")
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or [{
        "fulfillment_status": "completed", "purchase_type": "credit_pack",
        "entitlement_reference": "credit-lot-123", "replayed": False,
    }])
    result = service.fulfill_payment_order(SETTINGS, fulfillment_id=fulfillment, lease_token=lease)
    assert result["fulfillment_status"] == "completed"
    assert result["purchase_type"] == "credit_pack"
    assert calls[0][0] == "fulfill_payment_order"
    assert calls[0][1]["p_lease_token"] == str(lease)


def test_fail_payment_fulfillment_uses_fenced_retry_rpc(monkeypatch):
    fulfillment = UUID("77777777-7777-4777-8777-777777777777")
    lease = UUID("88888888-8888-4888-8888-888888888888")
    calls = []
    monkeypatch.setattr(service, "_rpc", lambda settings, name, payload: calls.append((name, payload)) or "queued")
    result = service.fail_payment_fulfillment(
        SETTINGS, fulfillment_id=fulfillment, lease_token=lease,
        error_code="temporary_storage_error", retry_after_seconds=90,
    )
    assert result == "queued"
    assert calls[0][0] == "fail_payment_fulfillment"
    assert calls[0][1]["p_max_attempts"] == 5


@pytest.mark.parametrize("malformed", [{}, [], None, 7])
def test_fail_payment_fulfillment_rejects_malformed_rpc_response(monkeypatch, malformed):
    fulfillment = UUID("77777777-7777-4777-8777-777777777777")
    lease = UUID("88888888-8888-4888-8888-888888888888")
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: malformed)
    with pytest.raises(service.PaymentOrderUnavailable):
        service.fail_payment_fulfillment(
            SETTINGS, fulfillment_id=fulfillment, lease_token=lease,
            error_code="temporary_storage_error",
        )


def test_fulfill_payment_order_rejects_malformed_rpc_response(monkeypatch):
    fulfillment = UUID("77777777-7777-4777-8777-777777777777")
    lease = UUID("88888888-8888-4888-8888-888888888888")
    monkeypatch.setattr(service, "_rpc", lambda *a, **k: {"unexpected": "object"})
    with pytest.raises(service.PaymentOrderUnavailable):
        service.fulfill_payment_order(
            SETTINGS, fulfillment_id=fulfillment, lease_token=lease,
        )



def test_central_payment_provider_bootstrap_is_disabled_by_default():
    from app.services.payment_provider_contracts import build_payment_provider_registry

    registry = build_payment_provider_registry(Settings(payment_provider_runtime_enabled=False), adapters=[FakeVerifiedAdapter()])
    assert registry.provider_codes == ()
    with pytest.raises(PaymentProviderNotConfigured):
        registry.get("examplepay")


def test_central_payment_provider_bootstrap_rejects_enabled_runtime_without_adapter():
    from app.services.payment_provider_contracts import build_payment_provider_registry

    with pytest.raises(PaymentProviderNotConfigured, match="without a concrete server adapter"):
        build_payment_provider_registry(Settings(payment_provider_runtime_enabled=True))


def test_central_payment_provider_bootstrap_validates_server_adapter():
    from app.services.payment_provider_contracts import build_payment_provider_registry

    registry = build_payment_provider_registry(
        Settings(payment_provider_runtime_enabled=True), adapters=[FakeVerifiedAdapter()]
    )
    assert registry.provider_codes == ("examplepay",)
