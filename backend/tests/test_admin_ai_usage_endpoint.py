from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_admin_ai_usage_report_is_admin_only_and_private(monkeypatch):
    import app.main as main_module

    expected = {
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat(), "timezone": "UTC"},
        "totals": {"requests": 1, "input_tokens": 10, "output_tokens": 5,
                   "total_tokens": 15, "reported_estimated_cost_usd": "0.0001",
                   "cost_unknown_events": 0},
        "by_provider_model": [], "by_endpoint": [], "by_day": [],
        "actual_billed_cost_usd": None, "billing_reconciliation": "not_available",
        "cost_disclaimer": "estimate only", "truncated": False,
        "today_by_provider": [],
    }
    audit = []
    monkeypatch.setattr(main_module, "get_admin_ai_usage_report", lambda *a, **k: expected)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit.append(k) or "audit-id")
    client = _client(StudioUser(
        user_id="22222222-2222-4222-8222-222222222222",
        email="owner@example.com", role="admin",
    ))
    try:
        response = client.get(
            "/api/admin/ai/usage",
            params={"date_from": date.today().isoformat(), "date_to": date.today().isoformat()},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["period"] == expected["period"]
        assert payload["totals"] == expected["totals"]
        assert payload["daily_budget_status"] == [
            {"provider": "deepseek", "daily_budget_usd": None, "estimated_spend_usd": "0",
             "unknown_cost_events": 0, "utilization_percent": None, "status": "unconfigured"},
        ]
        assert "not a hard billing cap" in payload["budget_status_note"]
        assert response.headers["cache-control"] == "private, no-store"
        assert len(audit) == 1
        assert audit[0]["reason"] == "Viewed aggregate AI usage report"
    finally:
        app.dependency_overrides.clear()


def test_admin_ai_usage_report_denies_creator_before_reading_data(monkeypatch):
    import app.main as main_module

    def forbidden(*args, **kwargs):
        raise AssertionError("AI usage report must not be queried for a creator")

    monkeypatch.setattr(main_module, "get_admin_ai_usage_report", forbidden)
    client = _client(StudioUser(
        user_id="33333333-3333-4333-8333-333333333333",
        email="creator@example.com", role="creator",
    ))
    try:
        response = client.get(
            "/api/admin/ai/usage",
            params={"date_from": date.today().isoformat(), "date_to": date.today().isoformat()},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()

def test_admin_ai_usage_report_warns_at_eighty_percent_of_configured_provider_budget(monkeypatch):
    from decimal import Decimal
    from app.core.config import Settings
    import app.main as main_module

    report = {
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat(), "timezone": "UTC"},
        "totals": {"requests": 1, "input_tokens": 10, "output_tokens": 5,
                   "total_tokens": 15, "reported_estimated_cost_usd": "0.00085",
                   "cost_unknown_events": 0, "token_count_unknown_events": 0},
        "today_by_provider": [{
            "provider": "deepseek", "requests": 1,
            "reported_estimated_cost_usd": "0.00085", "cost_unknown_events": 0,
        }],
    }
    monkeypatch.setattr(main_module, "settings", Settings(
        ai_daily_budget_usd_deepseek=Decimal("0.001"),
    ))
    monkeypatch.setattr(main_module, "get_admin_ai_usage_report", lambda *a, **k: report)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: "audit-id")
    client = _client(StudioUser(
        user_id="22222222-2222-4222-8222-222222222222",
        email="owner@example.com", role="admin",
    ))
    try:
        response = client.get(
            "/api/admin/ai/usage",
            params={"date_from": date.today().isoformat(), "date_to": date.today().isoformat()},
        )
        assert response.status_code == 200
        statuses = {item["provider"]: item for item in response.json()["daily_budget_status"]}
        assert statuses["deepseek"]["status"] == "warning"
        assert statuses["deepseek"]["utilization_percent"] == 85.0
        assert "gemini" not in statuses
    finally:
        app.dependency_overrides.clear()
