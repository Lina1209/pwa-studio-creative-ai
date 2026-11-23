from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

ADMIN = "11111111-1111-4111-8111-111111111111"
CREATOR = "22222222-2222-4222-8222-222222222222"
DRAFT = "33333333-3333-4333-8333-333333333333"

def client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def teardown_function():
    app.dependency_overrides.clear()

def valid_payload():
    return {
        "version": "pilot-2026-01",
        "rules": [{
            "job_type": "scene_image",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "credits_per_unit": 10,
            "unit_label": "image",
            "min_quantity": 1,
            "max_quantity": 3,
            "max_provider_cost_usd_per_unit": "0.01"
        }]
    }

def test_creator_cannot_list_tariff_drafts():
    response = client_for(StudioUser(user_id=CREATOR,email=None,role="creator")).get("/api/admin/pricing/drafts")
    assert response.status_code == 403

def test_admin_can_save_valid_tariff_as_inactive_draft(monkeypatch):
    import app.main as main
    captured = {}
    monkeypatch.setattr(main, "create_draft", lambda *a, **k: captured.update(version=k["version"],catalog=k["catalog"],actor_id=k["actor_id"]) or {"id":DRAFT})
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: "audit")
    response = client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/pricing/drafts",json=valid_payload())
    assert response.status_code == 201
    assert response.json()["live_pricing_changed"] is False
    assert captured["version"] == "pilot-2026-01"
    assert captured["actor_id"] == UUID(ADMIN)

def test_tariff_draft_requires_provider_cost_ceiling(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "create_draft", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not save")))
    payload = valid_payload()
    del payload["rules"][0]["max_provider_cost_usd_per_unit"]
    response = client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/pricing/drafts",json=payload)
    assert response.status_code == 422

def test_tariff_draft_rejects_unsupported_model(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "create_draft", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not save")))
    payload = valid_payload()
    payload["rules"][0]["model"] = "unknown-model"
    response = client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/pricing/drafts",json=payload)
    assert response.status_code == 422


def test_pricing_draft_audit_intent_precedes_creation(monkeypatch):
    import app.main as main

    calls = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: calls.append(("audit", k)) or "audit-id")
    monkeypatch.setattr(main, "create_draft", lambda *a, **k: calls.append(("create", k)) or {"id": DRAFT})
    response = client_for(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/pricing/drafts", json=valid_payload()
    )
    assert response.status_code == 201
    assert [entry[0] for entry in calls] == ["audit", "create", "audit"]
    assert calls[0][1]["action"] == "admin.pricing.draft.create"
    assert calls[0][1]["outcome"] == "requested"
    assert calls[2][1]["outcome"] == "executed"
    assert calls[2][1]["resource_id"] == UUID(DRAFT)


def test_pricing_draft_fails_closed_when_intent_audit_is_unavailable(monkeypatch):
    import app.main as main
    from app.services.admin_audit_service import AdminAuditUnavailable

    mutations = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable("unavailable")))
    monkeypatch.setattr(main, "create_draft", lambda *a, **k: mutations.append(True) or {"id": DRAFT})
    response = client_for(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/pricing/drafts", json=valid_payload()
    )
    assert response.status_code == 503
    assert mutations == []
