from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import app
from app.services.auth import StudioUser, get_current_user


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_ai_provider_status_is_owner_only_and_secret_free(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            ai_provider="deepseek",
            ai_model="deepseek-flash",
            deepseek_api_key="deepseek-secret-value",
            gemini_api_key="gemini-secret-value",
        ),
    )
    audit = []
    monkeypatch.setattr(
        main_module,
        "record_admin_audit_event",
        lambda *args, **kwargs: audit.append(kwargs) or "audit-id",
    )
    client = _client(
        StudioUser(
            user_id="22222222-2222-4222-8222-222222222222",
            email="owner@example.com",
            role="admin",
        )
    )
    try:
        response = client.get("/api/admin/ai/providers")
        assert response.status_code == 200
        data = response.json()
        assert data["selected_provider"] == "deepseek"
        assert data["ai_ready"] is True
        assert data["automatic_fallback"] is False
        assert data["runtime_provider_switching"] is False
        assert all("secret" not in str(value).lower() for value in data.values())
        assert "deepseek-secret-value" not in response.text
        assert "gemini-secret-value" not in response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert len(audit) == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_provider_status_denies_creator_before_returning_configuration(monkeypatch):
    import app.main as main_module

    def forbidden(*args, **kwargs):
        raise AssertionError("provider configuration must not be read for creators")

    monkeypatch.setattr(main_module, "record_admin_audit_event", forbidden)
    client = _client(
        StudioUser(
            user_id="33333333-3333-4333-8333-333333333333",
            email="creator@example.com",
            role="creator",
        )
    )
    try:
        response = client.get("/api/admin/ai/providers")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
