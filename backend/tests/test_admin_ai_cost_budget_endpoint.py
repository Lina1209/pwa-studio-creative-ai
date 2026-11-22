from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_admin_ai_cost_budget_endpoint_is_private_and_audited(monkeypatch):
    import app.main as main_module

    expected = {
        "date_utc": "2026-11-23",
        "enabled": True,
        "global_daily_budget_usd": "2.0000000000",
        "global_settled_estimated_spend_usd": "0.0000000000",
        "global_outstanding_reserved_usd": "0.0000000000",
        "global_committed_total_usd": "0.0000000000",
        "global_remaining_usd": "2.0000000000",
        "max_outstanding_reserved_usd": "0.5000000000",
        "providers": [],
        "actual_billed_cost_usd": None,
        "billing_reconciliation": "not_available",
        "note": "estimate only",
    }
    audit = []
    monkeypatch.setattr(main_module, "get_admin_ai_cost_budget_report", lambda *a, **k: expected)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit.append(k) or "audit-id")
    client = _client(StudioUser(
        user_id="22222222-2222-4222-8222-222222222222",
        email="owner@example.com", role="admin",
    ))
    try:
        response = client.get("/api/admin/ai/budget")
        assert response.status_code == 200
        assert response.json() == expected
        assert response.headers["cache-control"] == "private, no-store"
        assert len(audit) == 1
        assert audit[0]["reason"] == "Viewed synchronous AI cost budget status"
    finally:
        app.dependency_overrides.clear()


def test_admin_ai_cost_budget_endpoint_denies_creator_before_reading_data(monkeypatch):
    import app.main as main_module

    def forbidden(*args, **kwargs):
        raise AssertionError("Budget report must not be queried for a creator")

    monkeypatch.setattr(main_module, "get_admin_ai_cost_budget_report", forbidden)
    client = _client(StudioUser(
        user_id="33333333-3333-4333-8333-333333333333",
        email="creator@example.com", role="creator",
    ))
    try:
        response = client.get("/api/admin/ai/budget")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
