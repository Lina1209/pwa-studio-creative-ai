from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.pricing_service import (
    AIPricingRule,
    PricingError,
    quote_ai_operation,
    settle_ai_operation,
)

KEY = ("prompt.generate", "deepseek", "deepseek/deepseek-chat")


def _catalog(**overrides):
    rule = AIPricingRule(
        operation_code=KEY[0],
        pricing_version=3,
        provider=KEY[1],
        model=KEY[2],
        input_usd_per_million_tokens=Decimal("1.00"),
        output_usd_per_million_tokens=Decimal("2.00"),
        credits_per_usd=Decimal("100"),
        max_input_tokens=10_000,
        max_output_tokens=2_000,
        min_credits=1,
        max_credits=100_000,
        active=True,
    )
    return {KEY: replace(rule, **overrides)}


def test_production_catalog_starts_disabled():
    with pytest.raises(PricingError, match="No approved pricing rule"):
        quote_ai_operation(operation_code=KEY[0], provider=KEY[1], model=KEY[2])


def test_quote_reserves_worst_case_server_defined_token_ceiling():
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=_catalog()
    )
    # (10,000 * $1 + 2,000 * $2) / 1M * 100 credits/USD = 1.4 credits.
    assert quote.reserved_credits == 2
    assert quote.pricing_version == 3
    assert quote.max_input_tokens == 10_000


def test_settlement_rounds_up_and_never_exceeds_reservation():
    catalog = _catalog()
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=catalog
    )
    result = settle_ai_operation(
        quote, provider=KEY[1], model=KEY[2],
        input_tokens=1_000, output_tokens=500, catalog=catalog,
    )
    # ($0.001 + $0.001) * 100 = 0.2 credits, rounded up to 1.
    assert result.captured_credits == 1


def test_missing_usage_requires_reconciliation():
    catalog = _catalog()
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=catalog
    )
    with pytest.raises(PricingError, match="incomplete"):
        settle_ai_operation(
            quote, provider=KEY[1], model=KEY[2],
            input_tokens=None, output_tokens=10, catalog=catalog,
        )


def test_actual_usage_above_ceiling_is_rejected():
    catalog = _catalog()
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=catalog
    )
    with pytest.raises(PricingError, match="exceeds"):
        settle_ai_operation(
            quote, provider=KEY[1], model=KEY[2],
            input_tokens=10_001, output_tokens=1, catalog=catalog,
        )


def test_actual_cost_above_reservation_is_rejected():
    catalog = _catalog()
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=catalog
    )
    tiny_quote = replace(quote, reserved_credits=1)
    with pytest.raises(PricingError, match="reconciliation"):
        settle_ai_operation(
            tiny_quote, provider=KEY[1], model=KEY[2],
            input_tokens=10_000, output_tokens=2_000, catalog=catalog,
        )


def test_settlement_rejects_model_mismatch_and_version_change():
    catalog = _catalog()
    quote = quote_ai_operation(
        operation_code=KEY[0], provider=KEY[1], model=KEY[2], catalog=catalog
    )
    with pytest.raises(PricingError, match="differs"):
        settle_ai_operation(
            quote, provider=KEY[1], model="deepseek/other",
            input_tokens=1, output_tokens=1, catalog=catalog,
        )
    newer = _catalog(pricing_version=4)
    with pytest.raises(PricingError, match="version changed"):
        settle_ai_operation(
            quote, provider=KEY[1], model=KEY[2],
            input_tokens=1, output_tokens=1, catalog=newer,
        )


def test_invalid_or_disabled_rule_fails_closed():
    with pytest.raises(PricingError, match="not active"):
        quote_ai_operation(
            operation_code=KEY[0], provider=KEY[1], model=KEY[2],
            catalog=_catalog(active=False),
        )
    with pytest.raises(PricingError, match="conversion rate"):
        quote_ai_operation(
            operation_code=KEY[0], provider=KEY[1], model=KEY[2],
            catalog=_catalog(credits_per_usd=Decimal("0")),
        )
