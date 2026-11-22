from datetime import datetime, timezone
from uuid import UUID
import httpx
import pytest
from app.core.config import Settings
from app.services.admin_credit_ledger import (
    AdminCreditLedgerUnavailable, list_admin_credit_ledger,
)

USER = UUID("44444444-4444-4444-8444-444444444444")

def row(**changes):
    value = {
        "entry_id": 17, "user_id": str(USER), "hold_id": None,
        "operation_type": "grant", "delta_available": 50, "delta_reserved": 0,
        "balance_available_after": 50, "balance_reserved_after": 0,
        "created_at": "2026-11-22T12:00:00Z",
    }
    value.update(changes)
    return value

class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return None
    def json(self): return self.payload

class FakeClient:
    def __init__(self, payload): self.payload, self.calls = payload, []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def post(self, url, *, json, headers):
        self.calls.append((url, json, headers))
        return FakeResponse(self.payload)

def settings():
    return Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="service-role-secret")

def test_admin_ledger_returns_only_safe_fields_and_passes_keyset_cursor(monkeypatch):
    import app.services.admin_credit_ledger as module
    fake = FakeClient([row(metadata={"private_prompt":"must_not_escape"}, operation_key="secret")])
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: fake)
    before = datetime(2026, 11, 23, tzinfo=timezone.utc)
    result = list_admin_credit_ledger(settings(), user_id=USER, before_created_at=before, before_id=20)
    assert result[0]["entry_id"] == 17
    assert "metadata" not in result[0] and "operation_key" not in result[0]
    assert fake.calls[0][1]["p_before_id"] == 20
    assert fake.calls[0][1]["p_before_created_at"] == before.isoformat()

@pytest.mark.parametrize("bad", [
    row(user_id="33333333-3333-4333-8333-333333333333"),
    row(operation_type="steal"),
    row(delta_available=True),
    row(entry_id=True),
    row(created_at="2026-11-22T12:00:00"),
])
def test_admin_ledger_malformed_rows_fail_closed(monkeypatch, bad):
    import app.services.admin_credit_ledger as module
    fake = FakeClient([bad])
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: fake)
    with pytest.raises(AdminCreditLedgerUnavailable):
        list_admin_credit_ledger(settings(), user_id=USER)

def test_admin_ledger_rejects_partial_cursor_before_network():
    with pytest.raises(ValueError):
        list_admin_credit_ledger(settings(), user_id=USER, before_id=10)

def test_admin_ledger_sanitizes_upstream_failure(monkeypatch):
    import app.services.admin_credit_ledger as module
    class Broken(FakeClient):
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("secret host and token")
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: Broken([]))
    with pytest.raises(AdminCreditLedgerUnavailable) as exc:
        list_admin_credit_ledger(settings(), user_id=USER)
    assert "secret host" not in str(exc.value)
