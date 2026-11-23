from types import SimpleNamespace
from uuid import UUID

import app.services.admin_finance_integrity as service


USER_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    payload = None
    last_request = None

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json, headers):
        FakeClient.last_request = (url, json, headers)
        return FakeResponse(FakeClient.payload)


def snapshot(*, complete=True, ledger_count=0, ledger=None):
    limits = dict(service.SNAPSHOT_LIMITS)
    counts = {
        "ledger": ledger_count,
        "holds": 0,
        "lots": 0,
        "allocations": 0,
        "jobs": 0,
        "provider_cost_events": 0,
    }
    return {
        "user_id": str(USER_ID),
        "wallet": {"available_credits": 0, "reserved_credits": 0},
        "ledger": ledger or [],
        "holds": [],
        "lots": [],
        "allocations": [],
        "jobs": [],
        "provider_cost_events": [],
        "counts": counts,
        "limits": limits,
        "complete": complete,
    }


def test_service_calls_one_snapshot_rpc_and_returns_read_only_report(monkeypatch):
    FakeClient.payload = snapshot()
    monkeypatch.setattr(service.httpx, "Client", FakeClient)
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
    )

    report = service.get_finance_integrity_audit(settings, user_id=USER_ID)

    assert report["read_only"] is True
    assert report["snapshot_consistency"] == "single_statement"
    assert report["complete"] is True
    assert FakeClient.last_request[0].endswith(
        "/rpc/get_finance_integrity_audit_snapshot"
    )
    assert FakeClient.last_request[1] == {"p_user_id": str(USER_ID)}


def test_service_marks_over_limit_snapshot_incomplete(monkeypatch):
    payload = snapshot(complete=False, ledger_count=10001)
    payload["ledger"] = [{
        "entry_id": index + 1,
        "user_id": str(USER_ID),
        "operation_type": "grant",
        "operation_key": f"ledger-op-{index + 1:05d}",
        "delta_available": 0,
        "delta_reserved": 0,
        "balance_available_after": 0,
        "balance_reserved_after": 0,
        "created_at": "2026-11-23T10:00:00Z",
    } for index in range(10000)]
    FakeClient.payload = payload
    monkeypatch.setattr(service.httpx, "Client", FakeClient)
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
    )

    report = service.get_finance_integrity_audit(settings, user_id=USER_ID)

    assert report["complete"] is False
    assert report["status"] == "incomplete"


def test_service_rejects_snapshot_for_another_user(monkeypatch):
    payload = snapshot()
    payload["user_id"] = "33333333-3333-4333-8333-333333333333"
    FakeClient.payload = payload
    monkeypatch.setattr(service.httpx, "Client", FakeClient)
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
    )

    try:
        service.get_finance_integrity_audit(settings, user_id=USER_ID)
    except service.FinanceIntegrityAuditError:
        pass
    else:
        raise AssertionError("foreign-user snapshot must be rejected")
