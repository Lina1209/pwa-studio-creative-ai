from datetime import date

import httpx
import pytest

from app.core.config import Settings
from app.services.admin_financial_reporting import (
    MAX_REPORT_DAYS, PAGE_SIZE, MAX_EVENTS, ProviderCostReportError,
    ProviderCostReportNotConfiguredError, _aggregate, _row, get_provider_cost_report,
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
    sample(cost_source=[]), sample(cost_source={"unexpected": "object"}),
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, params, headers):
        self.calls.append((url, params, headers))
        return FakeResponse(next(self.pages))


def test_supabase_report_paginates_with_half_open_utc_range_and_stable_order(monkeypatch):
    import app.services.admin_financial_reporting as reporting

    first = [sample(job=f"00000000-0000-0000-0000-{i:012d}") for i in range(1, PAGE_SIZE + 1)]
    second = [sample(job="00000000-0000-0000-0000-000000000101")]
    fake = FakeClient([first, second])
    monkeypatch.setattr(reporting.httpx, "Client", lambda **kwargs: fake)
    settings = Settings(
        supabase_url="https://example.supabase.co/",
        supabase_service_role_key="service-role-secret",
    )

    report = get_provider_cost_report(
        settings, date_from=date(2026, 11, 22), date_to=date(2026, 11, 22)
    )

    assert report["event_count"] == 101
    assert [call[2]["Range"] for call in fake.calls] == ["0-99", "100-199"]
    url, params, headers = fake.calls[0]
    assert url == "https://example.supabase.co/rest/v1/generation_provider_cost_events"
    assert params["created_at"] == "gte.2026-11-22T00:00:00+00:00"
    assert params["and"] == "(created_at.lt.2026-11-23T00:00:00+00:00)"
    assert params["order"] == "created_at.asc,id.asc"
    assert params["limit"] == str(PAGE_SIZE)
    assert headers["apikey"] == "service-role-secret"
    assert "Authorization" not in headers


def test_supabase_report_fails_closed_when_event_cap_is_exceeded(monkeypatch):
    import app.services.admin_financial_reporting as reporting

    full_page = [sample(job=f"00000000-0000-0000-0000-{i:012d}") for i in range(1, PAGE_SIZE + 1)]
    fake = FakeClient([full_page for _ in range((MAX_EVENTS // PAGE_SIZE) + 1)])
    monkeypatch.setattr(reporting.httpx, "Client", lambda **kwargs: fake)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-secret",
    )

    with pytest.raises(ProviderCostReportError, match="could not be loaded safely"):
        get_provider_cost_report(
            settings, date_from=date(2026, 11, 22), date_to=date(2026, 11, 22)
        )
    assert len(fake.calls) == (MAX_EVENTS // PAGE_SIZE) + 1


def test_supabase_http_error_is_sanitized(monkeypatch):
    import app.services.admin_financial_reporting as reporting

    class ErrorClient(FakeClient):
        def get(self, url, *, params, headers):
            raise httpx.HTTPStatusError(
                "sensitive upstream body", request=httpx.Request("GET", url),
                response=httpx.Response(500, request=httpx.Request("GET", url)),
            )

    fake = ErrorClient([])
    monkeypatch.setattr(reporting.httpx, "Client", lambda **kwargs: fake)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-secret",
    )

    with pytest.raises(ProviderCostReportError) as exc:
        get_provider_cost_report(
            settings, date_from=date(2026, 11, 22), date_to=date(2026, 11, 22)
        )
    assert "sensitive upstream body" not in str(exc.value)
