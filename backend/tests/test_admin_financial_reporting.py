from datetime import date

import pytest

from app.core.config import Settings
from app.services.admin_financial_reporting import (
    MAX_REPORT_DAYS, ProviderCostReportNotConfiguredError,
    _aggregate, _row, get_provider_cost_report,
)


def sample(job="00000000-0000-0000-0000-000000000001", **changes):
    row = {
        "job_id": job, "provider": "provider-a", "model": "image-v1",
        "cost_usd": "0.125", "cost_source": "reported",
        "budget_exceeded": False, "created_at": "2026-11-22T12:00:00Z",
        "metadata": {"prompt": "private prompt"},
        "provider_usage_id": "private-usage-id",
    }
    row.update(changes)
    return row


def test_report_aggregates_evidence_and_budget_without_sensitive_metadata():
    rows = [
        _row(sample()),
        _row(sample(job="00000000-0000-0000-0000-000000000002",
                    cost_usd="0.025", cost_source="estimated", budget_exceeded=True)),
        _row(sample(job="00000000-0000-0000-0000-000000000003",
                    cost_usd=None, cost_source="unknown", budget_exceeded=None)),
    ]
    report = _aggregate(rows, date(2026, 11, 22), date(2026, 11, 22))
    assert report["event_count"] == 3
    assert report["known_provider_cost_usd"] == "0.1500000000"
    assert report["cost_evidence"] == {"reported": 1, "estimated": 1, "unknown": 1}
    assert report["budget_events"]["exceeded"] == 1
    assert report["budget_events"]["within_limit"] == 1
    assert report["budget_events"]["indeterminate_or_unconfigured"] == 1
    serialized = str(report)
    assert "private prompt" not in serialized
    assert "private-usage-id" not in serialized
    assert "metadata" not in serialized


@pytest.mark.parametrize("bad", [
    sample(cost_usd="NaN"), sample(cost_usd="-1"),
    sample(cost_usd=None, cost_source="reported"),
    sample(cost_usd="0", cost_source="unknown"),
    sample(budget_exceeded="true"), sample(budget_exceeded=0),
    sample(created_at="2026-11-22T12:00:00"), sample(job="not-a-uuid"),
])
def test_invalid_database_rows_fail_closed(bad):
    with pytest.raises(ValueError):
        _row(bad)


def test_date_range_is_bounded_before_database_access():
    settings = Settings(supabase_url=None, supabase_service_role_key=None)
    with pytest.raises(ValueError, match="date_range_invalid"):
        get_provider_cost_report(
            settings, date_from=date(2026, 1, 1),
            date_to=date(2026, 2, 1),
        )


def test_missing_database_configuration_fails_closed():
    settings = Settings(supabase_url=None, supabase_service_role_key=None)
    with pytest.raises(ProviderCostReportNotConfiguredError):
        get_provider_cost_report(
            settings, date_from=date(2026, 11, 22), date_to=date(2026, 11, 22)
        )
