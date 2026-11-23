from uuid import UUID

from app.core.config import Settings
from app.services import payment_orders
from app.services import payment_fulfillment_worker as worker


SETTINGS = Settings(supabase_url="https://example.test", supabase_service_role_key="server-secret")
FULFILLMENT = UUID("77777777-7777-4777-8777-777777777777")
LEASE = UUID("88888888-8888-4888-8888-888888888888")


def _claim():
    return {"fulfillment_id": FULFILLMENT, "lease_token": LEASE}


def test_batch_fulfills_claimed_items_and_counts_replays(monkeypatch):
    monkeypatch.setattr(payment_orders, "claim_payment_fulfillment", lambda *a, **k: [_claim(), _claim()])
    results = iter([
        {"fulfillment_status": "completed", "purchase_type": "credit_pack", "replayed": False},
        {"fulfillment_status": "completed", "purchase_type": "subscription", "replayed": True},
    ])
    monkeypatch.setattr(payment_orders, "fulfill_payment_order", lambda *a, **k: next(results))
    failed = []
    monkeypatch.setattr(payment_orders, "fail_payment_fulfillment", lambda *a, **k: failed.append(True))
    summary = worker.run_payment_fulfillment_batch(SETTINGS, batch_size=2)
    assert summary["claimed"] == 2
    assert summary["completed"] == 2
    assert summary["replayed"] == 1
    assert summary["outcome_unknown"] == 0
    assert failed == []


def test_ambiguous_fulfillment_failure_is_not_blindly_failed(monkeypatch):
    monkeypatch.setattr(payment_orders, "claim_payment_fulfillment", lambda *a, **k: [_claim()])
    def ambiguous(*args, **kwargs):
        raise payment_orders.PaymentOrderUnavailable("network outcome unknown")
    monkeypatch.setattr(payment_orders, "fulfill_payment_order", ambiguous)
    failed = []
    monkeypatch.setattr(payment_orders, "fail_payment_fulfillment", lambda *a, **k: failed.append(True))
    summary = worker.run_payment_fulfillment_batch(SETTINGS)
    assert summary["outcome_unknown"] == 1
    assert summary["completed"] == 0
    assert failed == []


def test_deterministic_conflict_uses_fenced_failure_transition(monkeypatch):
    monkeypatch.setattr(payment_orders, "claim_payment_fulfillment", lambda *a, **k: [_claim()])
    def conflict(*args, **kwargs):
        raise payment_orders.PaymentOrderConflict("known conflict")
    monkeypatch.setattr(payment_orders, "fulfill_payment_order", conflict)
    calls = []
    monkeypatch.setattr(
        payment_orders, "fail_payment_fulfillment",
        lambda *a, **k: calls.append(k) or "queued",
    )
    summary = worker.run_payment_fulfillment_batch(SETTINGS)
    assert summary["retry_queued"] == 1
    assert summary["outcome_unknown"] == 0
    assert calls[0]["fulfillment_id"] == FULFILLMENT
    assert calls[0]["lease_token"] == LEASE
    assert calls[0]["error_code"] == "fulfillment_conflict"


def test_ambiguous_failure_transition_is_reported_unknown(monkeypatch):
    monkeypatch.setattr(payment_orders, "claim_payment_fulfillment", lambda *a, **k: [_claim()])
    monkeypatch.setattr(
        payment_orders, "fulfill_payment_order",
        lambda *a, **k: (_ for _ in ()).throw(payment_orders.PaymentOrderNotFound("missing")),
    )
    monkeypatch.setattr(
        payment_orders, "fail_payment_fulfillment",
        lambda *a, **k: (_ for _ in ()).throw(payment_orders.PaymentOrderUnavailable("timeout")),
    )
    summary = worker.run_payment_fulfillment_batch(SETTINGS)
    assert summary["outcome_unknown"] == 1
    assert summary["retry_queued"] == 0
