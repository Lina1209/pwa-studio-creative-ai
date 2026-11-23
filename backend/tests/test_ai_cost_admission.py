from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services import ai_cost_admission as cost


def make_settings(**overrides):
    values = {
        "supabase_url": "https://project.example.supabase.co",
        "supabase_service_role_key": "eyJ.test.service-role",
        "ai_provider": "deepseek",
        "ai_model": "deepseek-flash",
        "ai_max_output_tokens": 2048,
        "ai_max_input_bytes": 30000,
    }
    values.update(overrides)
    return Settings(**values)


def test_worst_case_reservation_uses_peak_paid_rate_and_safety_margin():
    settings = make_settings()
    messages = [{"role": "user", "content": "hello"}]
    input_bytes, reserve = cost.estimate_worst_case_cost(settings, messages)
    assert input_bytes > 0
    expected_raw = (Decimal(input_bytes) * Decimal("0.30")
                    + Decimal(2048) * Decimal("1.20")) / Decimal(1_000_000)
    assert reserve >= expected_raw * Decimal("1.25")


@pytest.mark.parametrize(
    "provider,model,input_rate,output_rate",
    [
        ("deepseek", "deepseek-flash", "0.30", "1.20"),
        ("deepseek", "deepseek-v4-pro", "1.32", "3.96"),
        ("gemini", "gemini-3.1-flash-lite", "0.25", "1.50"),
    ],
)
def test_actual_cost_uses_server_maintained_peak_price_table(provider, model, input_rate, output_rate):
    settings = make_settings(ai_provider=provider, ai_model=model)
    expected = (
        Decimal(1000) * Decimal(input_rate) + Decimal(500) * Decimal(output_rate)
    ) / Decimal(1_000_000)
    assert cost.estimate_actual_cost(settings, input_tokens=1000, output_tokens=500) == expected.quantize(
        Decimal("0.0000000001")
    )


def test_unknown_token_usage_stays_unpriced():
    settings = make_settings()
    assert cost.estimate_actual_cost(settings, input_tokens=None, output_tokens=2) is None


def test_input_above_byte_limit_is_rejected_before_reservation():
    settings = make_settings(ai_max_input_bytes=256)
    with pytest.raises(cost.AIProviderBudgetRejected) as error:
        cost.estimate_worst_case_cost(settings, [{"role": "user", "content": "x" * 300}])
    assert error.value.reason == "input_size_limit"


def test_reservation_calls_atomic_rpc_and_fails_closed_on_budget_rejection(monkeypatch):
    seen = {}
    def rpc(settings, name, payload):
        seen.update(name=name, payload=payload)
        return {"admitted": True}

    monkeypatch.setattr(cost, "_rpc", rpc)
    user_id, request_id = uuid4(), uuid4()
    reservation = cost.reserve_ai_provider_cost(
        make_settings(), user_id=user_id, request_id=request_id,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert reservation.request_id == request_id
    assert seen["name"] == "reserve_ai_provider_cost"
    assert seen["payload"]["p_user_id"] == str(user_id)
    assert Decimal(seen["payload"]["p_reserved_cost_usd"]) > 0

    monkeypatch.setattr(cost, "_rpc", lambda *args, **kwargs: {
        "admitted": False, "reason": "global_daily_budget_reached"
    })
    with pytest.raises(cost.AIProviderBudgetRejected) as error:
        cost.reserve_ai_provider_cost(
            make_settings(), user_id=user_id, request_id=uuid4(),
            messages=[{"role": "user", "content": "hello"}],
        )
    assert error.value.reason == "global_daily_budget_reached"


def test_missing_supabase_credentials_fail_closed_before_rpc():
    with pytest.raises(cost.AIProviderBudgetUnavailable):
        cost.reserve_ai_provider_cost(
            Settings(supabase_url=None, supabase_service_role_key=None),
            user_id=uuid4(), request_id=uuid4(),
            messages=[{"role": "user", "content": "hello"}],
        )


def test_settlement_marks_unknown_when_usage_is_incomplete(monkeypatch):
    seen = {}
    monkeypatch.setattr(cost, "_rpc", lambda settings, name, payload:
                        seen.update(name=name, payload=payload) or True)
    reservation = cost.AIProviderCostReservation(uuid4(), Decimal("0.01"))
    estimate = cost.settle_ai_provider_cost(
        make_settings(), reservation, input_tokens=None, output_tokens=20,
    )
    assert estimate is None
    assert seen["name"] == "settle_ai_provider_cost"
    assert seen["payload"]["p_actual_estimated_cost_usd"] is None
    assert seen["payload"]["p_cost_source"] is None
