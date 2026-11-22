from datetime import date
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.services.admin_ai_usage_reporting import (
    _aggregate,
    _row,
    get_admin_ai_usage_report,
)


def test_ai_usage_aggregate_separates_provider_estimates_from_real_billing():
    rows = [
        _row({
            "provider": "deepseek", "model": "deepseek/deepseek-flash",
            "endpoint": "movie_script", "input_tokens": 120,
            "output_tokens": 80, "total_tokens": 200,
            "cost_usd": "0.00012", "cost_source": "litellm_response_cost",
            "created_at": "2026-11-23T10:00:00Z",
        }),
        _row({
            "provider": "gemini", "model": "gemini/gemini-3.1-flash-lite",
            "endpoint": "chat", "input_tokens": 50,
            "output_tokens": 20, "total_tokens": 70,
            "cost_usd": None, "cost_source": None,
            "created_at": "2026-11-23T11:00:00Z",
        }),
    ]
    report = _aggregate(rows, date(2026, 11, 23), date(2026, 11, 23))
    assert report["totals"]["requests"] == 2
    assert report["totals"]["input_tokens"] == 170
    assert report["totals"]["output_tokens"] == 100
    assert report["totals"]["total_tokens"] == 270
    assert report["totals"]["reported_estimated_cost_usd"] == "0.0001200000"
    assert report["totals"]["cost_unknown_events"] == 1
    assert report["actual_billed_cost_usd"] is None
    assert report["billing_reconciliation"] == "not_available"
    assert len(report["by_provider_model"]) == 2


def test_ai_usage_row_rejects_negative_tokens_and_naive_timestamps():
    base = {
        "provider": "deepseek", "model": "deepseek/deepseek-flash",
        "endpoint": "chat", "input_tokens": -1, "output_tokens": 0,
        "total_tokens": 0, "cost_usd": None, "cost_source": None,
        "created_at": "2026-11-23T11:00:00",
    }
    with pytest.raises(ValueError):
        _row(base)
    base["input_tokens"] = 1
    with pytest.raises(ValueError):
        _row(base)


def test_ai_usage_report_rejects_period_over_31_days_before_network():
    settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="test")
    with pytest.raises(ValueError):
        get_admin_ai_usage_report(
            settings, date_from=date(2026, 1, 1), date_to=date(2026, 2, 1)
        )
