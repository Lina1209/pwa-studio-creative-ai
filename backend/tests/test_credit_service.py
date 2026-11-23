import httpx
import pytest
from dataclasses import replace
from decimal import Decimal
from fastapi import HTTPException

from app.core.config import Settings
from app.services import credit_service
from app.services.pricing_service import AIPricingRule, PricingError

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



def _pricing_catalog():
    key = ("prompt.generate", "deepseek", "deepseek/deepseek-chat")
    rule = AIPricingRule(
        operation_code=key[0], pricing_version=3, provider=key[1], model=key[2],
        input_usd_per_million_tokens=Decimal("1"),
        output_usd_per_million_tokens=Decimal("2"),
        credits_per_usd=Decimal("100"),
        max_input_tokens=10_000, max_output_tokens=2_000,
        min_credits=1, max_credits=100_000, active=True,
    )
    return {key: rule}, key


def test_priced_reservation_uses_only_server_catalog_amount(monkeypatch):
    catalog, key = _pricing_catalog()
    seen = {}

    def fake_reserve(settings, **kwargs):
        seen.update(kwargs)
        return {"status": "reserved", "reservation_id": RESERVATION_ID}

    monkeypatch.setattr(credit_service, "reserve_credits", fake_reserve)
    quote, result = credit_service.reserve_priced_ai_operation(
        _settings(), user_id=USER_ID, idempotency_key="request-456",
        operation_code=key[0], provider=key[1], model=key[2], catalog=catalog,
    )
    assert result["status"] == "reserved"
    assert seen["amount"] == quote.reserved_credits == 2
    assert seen["pricing_version"] == 3
    assert seen["operation_code"] == "prompt.generate"


def test_priced_reservation_fails_closed_when_catalog_has_no_rule():
    with pytest.raises(PricingError, match="No approved pricing rule"):
        credit_service.reserve_priced_ai_operation(
            _settings(), user_id=USER_ID, idempotency_key="request-456",
            operation_code="prompt.generate", provider="deepseek",
            model="deepseek/deepseek-chat",
        )


def test_priced_settlement_marks_ambiguous_usage_for_reconciliation(monkeypatch):
    catalog, key = _pricing_catalog()
    quote = credit_service.quote_ai_operation(
        operation_code=key[0], provider=key[1], model=key[2], catalog=catalog
    )
    seen = {}
    monkeypatch.setattr(
        credit_service, "mark_reconciliation_required",
        lambda settings, **kwargs: seen.update(kwargs) or {"status": "reconciliation_required"},
    )
    with pytest.raises(PricingError, match="incomplete"):
        credit_service.settle_priced_ai_operation(
            _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID,
            quote=quote, provider=key[1], model=key[2],
            input_tokens=None, output_tokens=100, catalog=catalog,
        )
    assert seen == {"user_id": USER_ID, "reservation_id": RESERVATION_ID}


def test_priced_settlement_captures_server_calculated_amount(monkeypatch):
    catalog, key = _pricing_catalog()
    quote = credit_service.quote_ai_operation(
        operation_code=key[0], provider=key[1], model=key[2], catalog=catalog
    )
    seen = {}

    def fake_settle(settings, **kwargs):
        seen.update(kwargs)
        return {"status": "settled", "captured_credits": kwargs["capture_amount"]}

    monkeypatch.setattr(credit_service, "settle_reservation", fake_settle)
    settlement, result = credit_service.settle_priced_ai_operation(
        _settings(), user_id=USER_ID, reservation_id=RESERVATION_ID,
        quote=quote, provider=key[1], model=key[2],
        input_tokens=1_000, output_tokens=500, catalog=catalog,
    )
    assert settlement.captured_credits == 1
    assert seen["capture_amount"] == 1
    assert result["status"] == "settled"
