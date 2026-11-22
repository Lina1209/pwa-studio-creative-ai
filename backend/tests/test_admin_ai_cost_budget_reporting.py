from app.core.config import Settings
from app.services import admin_ai_cost_budget_reporting as report


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, timeout):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params, headers):
        self.calls.append((url, params, headers))
        if url.endswith("/ai_provider_budget_policy"):
            return FakeResponse([{
                "enabled": True,
                "global_daily_budget_usd": "2.0000000000",
                "max_outstanding_reserved_usd": "0.5000000000",
            }])
        if url.endswith("/ai_provider_daily_budgets"):
            return FakeResponse([
                {"provider": "deepseek", "daily_budget_usd": "1.0000000000", "enabled": True},
                {"provider": "gemini", "daily_budget_usd": "1.0000000000", "enabled": True},
            ])
        if url.endswith("/ai_provider_cost_reservations"):
            if params.get("status") == "in.(reserved,unknown)":
                return FakeResponse([
                    {"provider": "deepseek", "status": "reserved", "reserved_cost_usd": "0.10", "actual_estimated_cost_usd": None},
                    {"provider": "gemini", "status": "unknown", "reserved_cost_usd": "0.20", "actual_estimated_cost_usd": None},
                ])
            return FakeResponse([
                {"provider": "deepseek", "status": "settled", "reserved_cost_usd": "0.02", "actual_estimated_cost_usd": "0.03"},
            ])
        raise AssertionError(url)


def test_admin_budget_report_separates_spend_reservations_and_unknown(monkeypatch):
    client = FakeClient(timeout=10)
    monkeypatch.setattr(report.httpx, "Client", lambda timeout: client)
    result = report.get_admin_ai_cost_budget_report(Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-secret",
    ))
    assert result["enabled"] is True
    assert result["global_daily_budget_usd"] == "2.0000000000"
    assert result["global_settled_estimated_spend_usd"] == "0.0300000000"
    assert result["global_outstanding_reserved_usd"] == "0.3000000000"
    by_provider = {row["provider"]: row for row in result["providers"]}
    assert by_provider["deepseek"]["settled_estimated_spend_usd"] == "0.0300000000"
    assert by_provider["deepseek"]["outstanding_reserved_usd"] == "0.1000000000"
    assert by_provider["gemini"]["unknown_reservations"] == 1
    assert by_provider["gemini"]["status"] == "unknown_costs"
    assert result["actual_billed_cost_usd"] is None


def test_admin_budget_report_fails_closed_without_service_credentials():
    import pytest
    from app.services.admin_ai_cost_budget_reporting import AICostBudgetReportNotConfiguredError

    with pytest.raises(AICostBudgetReportNotConfiguredError):
        report.get_admin_ai_cost_budget_report(Settings(
            supabase_url=None, supabase_service_role_key=None,
        ))
