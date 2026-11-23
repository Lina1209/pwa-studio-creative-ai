import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


USER = StudioUser(
    user_id="11111111-1111-4111-8111-111111111111",
    email="creator@example.test",
    role="creator",
)


def _client():
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)


def test_chat_uses_authenticated_owner_and_records_usage(monkeypatch):
    import app.main as main

    calls = []
    usage = []
    result = SimpleNamespace(
        text="Давайте начнём с идеи короткого фильма.",
        actual_model="companion-test-model",
        request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    def run(operation, user_id, call):
        calls.append((operation, user_id))
        return result

    monkeypatch.setattr(main, "_run_admitted_ai", run)
    monkeypatch.setattr(main, "record_ai_usage", lambda *args, **kwargs: usage.append(kwargs))

    client = _client()
    try:
        response = client.post("/api/chat", json={"message": "Помоги придумать фильм о море."})
        assert response.status_code == 200
        assert response.json()["reply"] == result.text
        assert response.json()["model"] == result.actual_model
        assert calls == [("chat", USER.user_id)]
        assert usage[0]["endpoint"] == "chat"
        assert usage[0]["user_id"] == USER.user_id
        assert response.headers["cache-control"] == "private, no-store"
    finally:
        app.dependency_overrides.clear()


def test_prompt_studio_returns_finished_prompt_and_records_usage(monkeypatch):
    import app.main as main

    calls = []
    usage = []
    result = SimpleNamespace(
        text="Cinematic wide shot of a lighthouse at sunrise, soft golden light.",
        actual_model="prompt-test-model",
        request_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )

    def run(operation, user_id, call):
        calls.append((operation, user_id))
        return result

    monkeypatch.setattr(main, "_run_admitted_ai", run)
    monkeypatch.setattr(main, "record_ai_usage", lambda *args, **kwargs: usage.append(kwargs))

    client = _client()
    try:
        response = client.post(
            "/api/prompts",
            json={
                "idea": "Маяк на берегу во время рассвета",
                "purpose": "video",
                "language": "English",
                "style": "cinematic realism",
            },
        )
        assert response.status_code == 200
        assert response.json()["prompt"] == result.text
        assert response.json()["model"] == result.actual_model
        assert calls == [("prompts", USER.user_id)]
        assert usage[0]["endpoint"] == "prompts"
        assert usage[0]["user_id"] == USER.user_id
    finally:
        app.dependency_overrides.clear()


def test_chat_and_prompt_studio_require_authentication(monkeypatch):
    import app.services.auth as auth

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(supabase_url="https://auth.example.test"),
    )
    client = TestClient(app)

    chat = client.post("/api/chat", json={"message": "Помоги с идеей."})
    prompt = client.post("/api/prompts", json={"idea": "Город будущего"})

    assert chat.status_code == 401
    assert prompt.status_code == 401


def test_chat_and_prompt_studio_reject_invalid_payloads():
    client = _client()
    try:
        empty_chat = client.post("/api/chat", json={"message": ""})
        extra_chat = client.post(
            "/api/chat",
            json={"message": "Привет", "user_id": "22222222-2222-4222-8222-222222222222"},
        )
        empty_prompt = client.post("/api/prompts", json={"idea": ""})
        extra_prompt = client.post(
            "/api/prompts",
            json={"idea": "Город будущего", "credits": 0},
        )

        assert empty_chat.status_code == 422
        assert extra_chat.status_code == 422
        assert empty_prompt.status_code == 422
        assert extra_prompt.status_code == 422
    finally:
        app.dependency_overrides.clear()
