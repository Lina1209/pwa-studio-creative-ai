import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import StudioUser, get_current_user

USER = StudioUser(
    user_id="11111111-1111-4111-8111-111111111111",
    email="creator@example.test", role="creator",
)

def _client():
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)

def test_movie_script_returns_structured_story_and_storyboard(monkeypatch):
    import app.main as main
    payload = {"story":"СЦЕНА 1. НАТ. ЛЕС — ДЕНЬ\nГерой идёт по тропе.","storyboard":"Кадр 1: общий план, плавный наезд."}
    calls=[]; usage=[]
    monkeypatch.setattr(main,"_run_admitted_ai",lambda operation,user_id,call: calls.append((operation,user_id)) or SimpleNamespace(text=json.dumps(payload,ensure_ascii=False),actual_model="test-model"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: usage.append(k))
    c=_client()
    try:
        response=c.post("/api/movie/script",json={"title":"Лесная история","idea":"Путешествие девочки к старому маяку","genre":"Приключения","duration_minutes":5,"frame":"16:9","language":"Русский"})
        assert response.status_code==200
        assert response.json()["story"]==payload["story"]
        assert response.json()["storyboard"]==payload["storyboard"]
        assert response.json()["model"]=="test-model"
        assert calls[0][0]=="movie_script" and calls[0][1]==USER.user_id
        assert usage[0]["endpoint"]=="movie_script"
        assert response.headers["cache-control"]=="private, no-store"
    finally:
        app.dependency_overrides.clear()

def test_movie_script_rejects_invalid_ai_json_without_leaking_provider_output(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"_run_admitted_ai",lambda *a,**k: SimpleNamespace(text="provider internal details",actual_model="test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: None)
    c=_client()
    try:
        response=c.post("/api/movie/script",json={"title":"История","idea":"Короткое путешествие"})
        assert response.status_code==502
        assert "provider internal details" not in response.text
    finally:
        app.dependency_overrides.clear()

def test_movie_script_rejects_oversized_duration_and_unknown_fields():
    c=_client()
    try:
        too_long=c.post("/api/movie/script",json={"title":"История","idea":"Идея","duration_minutes":90})
        assert too_long.status_code==422
        extra=c.post("/api/movie/script",json={"title":"История","idea":"Идея","untrusted_price":0})
        assert extra.status_code==422
    finally:
        app.dependency_overrides.clear()

def test_movie_script_requires_authentication():
    c=TestClient(app)
    response=c.post("/api/movie/script",json={"title":"История","idea":"Идея"})
    assert response.status_code in {401,403}
