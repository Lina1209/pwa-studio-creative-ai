from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


def _client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_financial_report_denies_non_admin_before_reading_data(monkeypatch):
    import app.main as main_module

    def forbidden(*args, **kwargs):
        raise AssertionError("report must not be queried for a non-admin")

    monkeypatch.setattr(main_module, "get_provider_cost_report", forbidden)
    client = _client_for(StudioUser(user_id="creator-id", email="creator@example.com", role="creator"))
    try:
        response = client.get(
            "/api/admin/financial/provider-costs",
            params={"date_from": "2026-11-01", "date_to": "2026-11-02"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "This operation is not permitted."
    finally:
        app.dependency_overrides.clear()


def test_financial_report_admin_response_is_private_and_no_store(monkeypatch):
    import app.main as main_module

    expected = {
        "event_count": 0,
        "known_provider_cost_usd": "0.0000000000",
        "cost_evidence": {"reported": 0, "estimated": 0, "unknown": 0},
    }
    audit_calls = []
    monkeypatch.setattr(main_module, "get_provider_cost_report", lambda *a, **k: expected)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit_calls.append(k) or "audit-id")
    actor_id = "22222222-2222-4222-8222-222222222222"
    client = _client_for(StudioUser(user_id=actor_id, email="admin@example.com", role="admin"))
    try:
        response = client.get(
            "/api/admin/financial/provider-costs",
            params={"date_from": "2026-11-01", "date_to": "2026-11-02"},
        )
        assert response.status_code == 200
        assert response.json() == expected
        assert response.headers["cache-control"] == "private, no-store"
        assert len(audit_calls) == 1
        assert audit_calls[0]["actor_user_id"] == UUID(actor_id)
        assert audit_calls[0]["action"] == "admin.access"
        assert audit_calls[0]["reason"] == "Viewed provider cost report"
    finally:
        app.dependency_overrides.clear()


def test_financial_report_rejects_invalid_date_range(monkeypatch):
    import app.main as main_module

    def should_not_run(*args, **kwargs):
        raise AssertionError("invalid date range must be rejected before querying")

    monkeypatch.setattr(main_module, "get_provider_cost_report", should_not_run)
    client = _client_for(StudioUser(user_id="admin-id", email="admin@example.com", role="admin"))
    try:
        response = client.get(
            "/api/admin/financial/provider-costs",
            params={"date_from": "not-a-date", "date_to": "2026-11-02"},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
