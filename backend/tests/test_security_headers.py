from fastapi.testclient import TestClient

from app import main


def test_api_responses_include_baseline_security_headers():
    response = TestClient(main.app).get("/")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_hsts_is_not_added_in_development(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "development")
    response = TestClient(main.app).get("/")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_is_added_in_production(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "production")
    response = TestClient(main.app).get("/")
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_api_responses_are_never_cached():
    response = TestClient(main.app).get("/api/health")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"

def test_admin_put_preflight_is_allowed_for_configured_frontend_origin():
    client = TestClient(main.app)
    response = client.options(
        "/api/admin/ai/budget/global",
        headers={
            "Origin": "https://lina1209.github.io",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://lina1209.github.io"
    assert "PUT" in response.headers["Access-Control-Allow-Methods"]
    allowed_headers = response.headers["Access-Control-Allow-Headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers


def test_admin_put_preflight_rejects_untrusted_origin():
    client = TestClient(main.app)
    response = client.options(
        "/api/admin/ai/budget/global",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
