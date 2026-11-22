from uuid import UUID

import pytest

from app.core.config import Settings
from app.services import credit_wallet_service as wallet


USER_ID = UUID("11111111-1111-4111-8111-111111111111")


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
        return FakeResponse(item)


def settings():
    return Settings(
        supabase_url="https://project.example.supabase.co",
        supabase_service_role_key="sb_secret_test_key",
    )


def test_wallet_uses_one_atomic_owner_scoped_rpc_and_returns_history(monkeypatch):
    client = FakeClient([{
        "user_id": str(USER_ID),
        "currency_unit": "credit",
        "available_credits": 120,
        "reserved_credits": 30,
        "holds": [{
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "job_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "amount": 30, "status": "held", "created_at": "2026-11-23T00:00:00Z",
            "quote_snapshot": {"private": "must not be returned"},
        }],
        "lots": [{
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "lot_type": "purchased", "granted_credits": 150,
            "available_credits": 120, "reserved_credits": 30,
            "expires_at": None, "created_at": "2026-11-22T00:00:00Z",
            "source_reference": "must not be returned",
        }],
        "allocations": [{
            "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "hold_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "lot_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "amount": 30, "status": "held", "created_at": "2026-11-23T00:00:00Z",
        }],
        "ledger": [{
            "id": 9, "operation_type": "reserve", "operation_key": "reserve:job-1234",
            "delta_available": -30, "delta_reserved": 30,
            "balance_available_after": 120, "balance_reserved_after": 30,
            "created_at": "2026-11-23T00:00:00Z",
        }],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    result = wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)

    assert result.available_credits == 120
    assert result.reserved_credits == 30
    assert result.holds[0]["amount"] == 30
    assert "quote_snapshot" not in result.holds[0]
    assert result.ledger[0]["delta_available"] == -30
    assert result.lots[0]["lot_type"] == "purchased"
    assert result.lots[0]["reserved_credits"] == 30
    assert result.allocations[0]["amount"] == 30
    assert "source_reference" not in result.lots[0]
    assert len(client.calls) == 1
    url, payload, headers = client.calls[0]
    assert url.endswith("/rpc/get_credit_wallet_snapshot")
    assert payload == {"p_user_id": str(USER_ID), "p_history_limit": 50}
    assert headers["apikey"] == "sb_secret_test_key"


def test_missing_wallet_is_zero_balance_not_an_implicit_grant(monkeypatch):
    client = FakeClient([{
        "user_id": str(USER_ID),
        "currency_unit": "credit",
        "available_credits": 0,
        "reserved_credits": 0,
        "holds": [],
        "ledger": [],
        "lots": [],
        "allocations": [],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    result = wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)

    assert result.available_credits == 0
    assert result.reserved_credits == 0
    assert result.holds == []
    assert result.ledger == []


def test_history_limit_is_bounded_before_database_access(monkeypatch):
    monkeypatch.setattr(
        wallet.httpx, "Client",
        lambda timeout: pytest.fail("No database request expected"),
    )
    with pytest.raises(ValueError):
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID, history_limit=101)


def test_missing_database_configuration_fails_closed():
    with pytest.raises(wallet.CreditWalletNotConfigured):
        wallet.get_credit_wallet_snapshot(
            Settings(supabase_url=None, supabase_service_role_key=None),
            user_id=USER_ID,
        )


def test_invalid_wallet_balance_is_rejected(monkeypatch):
    client = FakeClient([{
        "user_id": str(USER_ID),
        "currency_unit": "credit",
        "available_credits": -1,
        "reserved_credits": 0,
        "holds": [],
        "ledger": [],
        "lots": [],
        "allocations": [],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    with pytest.raises(wallet.CreditWalletUnavailable):
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)


def test_wallet_snapshot_identity_mismatch_is_rejected(monkeypatch):
    client = FakeClient([{
        "user_id": "22222222-2222-4222-8222-222222222222",
        "currency_unit": "credit",
        "available_credits": 100,
        "reserved_credits": 0,
        "holds": [],
        "ledger": [],
        "lots": [],
        "allocations": [],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    with pytest.raises(wallet.CreditWalletUnavailable):
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)


def test_database_failure_is_sanitized(monkeypatch):
    client = FakeClient([RuntimeError("secret database response")])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    with pytest.raises(wallet.CreditWalletUnavailable) as error:
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)

    assert "secret database response" not in str(error.value)


def test_lot_totals_must_reconcile_with_wallet(monkeypatch):
    client = FakeClient([{
        "user_id": str(USER_ID),
        "currency_unit": "credit",
        "available_credits": 50,
        "reserved_credits": 0,
        "holds": [],
        "ledger": [],
        "lots": [{
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "lot_type": "free", "granted_credits": 50,
            "available_credits": 40, "reserved_credits": 0,
            "expires_at": None, "created_at": "2026-11-22T00:00:00Z",
        }],
        "allocations": [],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    with pytest.raises(wallet.CreditWalletUnavailable):
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)


def test_unknown_credit_lot_type_is_rejected(monkeypatch):
    client = FakeClient([{
        "user_id": str(USER_ID),
        "currency_unit": "credit",
        "available_credits": 0,
        "reserved_credits": 0,
        "holds": [],
        "ledger": [],
        "lots": [{
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "lot_type": "untrusted_type", "granted_credits": 1,
            "available_credits": 0, "reserved_credits": 0,
            "expires_at": None, "created_at": "2026-11-22T00:00:00Z",
        }],
        "allocations": [],
    }])
    monkeypatch.setattr(wallet.httpx, "Client", lambda timeout: client)

    with pytest.raises(wallet.CreditWalletUnavailable):
        wallet.get_credit_wallet_snapshot(settings(), user_id=USER_ID)
