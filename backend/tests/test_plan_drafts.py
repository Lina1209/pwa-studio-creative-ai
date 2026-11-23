import pytest
from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

ADMIN="11111111-1111-4111-8111-111111111111"
CREATOR="22222222-2222-4222-8222-222222222222"
DRAFT="33333333-3333-4333-8333-333333333333"

def client_for(user):
    app.dependency_overrides[get_current_user]=lambda:user
    return TestClient(app)

def teardown_function():
    app.dependency_overrides.clear()

def valid_plan():
    return {
        "plan_code":"creator",
        "plan_version":1,
        "display_name":"Creator",
        "billing_period":"month",
        "period_days":30,
        "credits_per_period":1500,
        "price_minor":None,
        "currency":None,
        "limits":{"max_parallel_jobs":2,"max_video_seconds":60,"max_resolution":"1080p"},
        "features":["Расширенные инструменты","Приоритетная очередь"]
    }

def test_creator_cannot_list_plan_drafts():
    response=client_for(StudioUser(user_id=CREATOR,email=None,role="creator")).get("/api/admin/plans/drafts")
    assert response.status_code==403

def test_admin_saves_plan_as_non_activating_draft(monkeypatch):
    import app.main as main
    captured={}
    monkeypatch.setattr(main,"create_plan_draft",lambda *a,**k:captured.update(payload=k["payload"],actor_id=k["actor_id"]) or {"id":DRAFT})
    monkeypatch.setattr(main,"record_admin_audit_event",lambda *a,**k:"audit")
    response=client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/plans/drafts",json=valid_plan())
    assert response.status_code==201
    assert response.json()["credits_granted"] is False
    assert response.json()["checkout_enabled"] is False
    assert captured["actor_id"]==UUID(ADMIN)
    assert captured["payload"]["credits_per_period"]==1500

def test_plan_period_must_match_week_or_month():
    payload=valid_plan()
    payload["period_days"]=31
    response=client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/plans/drafts",json=payload)
    assert response.status_code==422

def test_plan_rejects_unknown_or_negative_limits(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"create_plan_draft",lambda *a,**k:(_ for _ in ()).throw(AssertionError("must not save")))
    payload=valid_plan()
    payload["limits"]={"max_parallel_jobs":-1,"unrestricted":True}
    response=client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/plans/drafts",json=payload)
    assert response.status_code==422

def test_free_plan_cannot_have_paid_price(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"create_plan_draft",lambda *a,**k:(_ for _ in ()).throw(AssertionError("must not save")))
    payload=valid_plan()
    payload.update({"plan_code":"free","price_minor":1000,"currency":"USD"})
    response=client_for(StudioUser(user_id=ADMIN,email=None,role="admin")).post("/api/admin/plans/drafts",json=payload)
    assert response.status_code==422


@pytest.mark.parametrize(
    "limit_key,value",
    [
        ("daily_ai_requests", 50),
        ("monthly_ai_requests", 1000),
        ("max_concurrent_ai_requests", 3),
        ("daily_image_generations", 10),
        ("monthly_image_generations", 200),
        ("daily_video_generations", 2),
        ("monthly_video_generations", 20),
        ("daily_audio_generations", 15),
        ("monthly_audio_generations", 300),
    ],
)
def test_plan_accepts_explicit_server_quota_dimensions(monkeypatch, limit_key, value):
    import app.main as main
    captured = {}
    monkeypatch.setattr(
        main, "create_plan_draft",
        lambda *a, **k: captured.update(payload=k["payload"]) or {"id": DRAFT},
    )
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: "audit")
    payload = valid_plan()
    payload["limits"] = {limit_key: value}
    response = client_for(
        StudioUser(user_id=ADMIN, email=None, role="admin")
    ).post("/api/admin/plans/drafts", json=payload)
    assert response.status_code == 201
    assert captured["payload"]["limits_json"][limit_key] == value


@pytest.mark.parametrize(
    "limit_key",
    ["daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests",
     "daily_image_generations", "monthly_image_generations",
     "daily_video_generations", "monthly_video_generations",
     "daily_audio_generations", "monthly_audio_generations"],
)
def test_plan_rejects_boolean_quota_values(monkeypatch, limit_key):
    import app.main as main
    monkeypatch.setattr(
        main, "create_plan_draft",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not save")),
    )
    payload = valid_plan()
    payload["limits"] = {limit_key: True}
    response = client_for(
        StudioUser(user_id=ADMIN, email=None, role="admin")
    ).post("/api/admin/plans/drafts", json=payload)
    assert response.status_code == 422
