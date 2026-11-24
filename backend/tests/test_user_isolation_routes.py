import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth import StudioUser, get_current_user


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
THREAD_ID = "33333333-3333-4333-8333-333333333333"
NOTIFICATION_ID = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(
        user_id=USER_A, email="creator@example.com", role="creator"
    )
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def test_notification_routes_always_scope_to_verified_user(client, monkeypatch):
    calls = []

    def list_for_user(settings, user_id):
        calls.append(("list", user_id))
        return []

    def read_for_user(settings, user_id, notification_id):
        calls.append(("read", user_id, notification_id))
        return {"id": notification_id, "read_at": "now"}

    def read_all_for_user(settings, user_id):
        calls.append(("read_all", user_id))
        return {"updated": 0}

    monkeypatch.setattr(main, "list_notifications", list_for_user)
    monkeypatch.setattr(main, "mark_notification_read", read_for_user)
    monkeypatch.setattr(main, "mark_all_notifications_read", read_all_for_user)

    assert client.get("/api/notifications").status_code == 200
    assert client.post(f"/api/notifications/{NOTIFICATION_ID}/read").status_code == 200
    assert client.post("/api/notifications/read-all").status_code == 200
    assert calls == [
        ("list", USER_A),
        ("read", USER_A, NOTIFICATION_ID),
        ("read_all", USER_A),
    ]


def test_profile_read_and_update_use_verified_user_not_request_identity(client, monkeypatch):
    calls = []

    def own_profile(settings, user_id):
        calls.append(("get", user_id))
        return {"user_id": user_id}

    def update_profile(settings, user_id, changes):
        calls.append(("update", user_id, changes))
        return {"user_id": user_id}

    monkeypatch.setattr(main, "get_own_profile", own_profile)
    monkeypatch.setattr(main, "update_own_profile", update_profile)

    assert client.get("/api/community/profile").json() == {"user_id": USER_A}
    response = client.patch("/api/community/profile", json={
        "display_name": "My profile",
        "user_id": USER_B,
    })
    assert response.status_code == 200
    assert calls[0] == ("get", USER_A)
    assert calls[1][0:2] == ("update", USER_A)
    assert calls[1][2] == {"display_name": "My profile"}


def test_public_profile_lookup_receives_verified_viewer_id(client, monkeypatch):
    calls = []

    def get_profile(settings, target_user_id, current_user_id):
        calls.append((target_user_id, current_user_id))
        return {"user_id": target_user_id}

    monkeypatch.setattr(main, "get_public_profile", get_profile)
    response = client.get(f"/api/community/profiles/{USER_B}")
    assert response.status_code == 200
    assert calls == [(USER_B, USER_A)]


def test_conversation_routes_use_verified_participant_id(client, monkeypatch):
    calls = []

    def conversations(settings, user_id):
        calls.append(("list", user_id))
        return []

    def messages(settings, user_id, thread_id):
        calls.append(("messages", user_id, thread_id))
        return []

    def read(settings, user_id, thread_id):
        calls.append(("read", user_id, thread_id))
        return {"updated": 0}

    monkeypatch.setattr(main, "list_conversations", conversations)
    monkeypatch.setattr(main, "list_messages", messages)
    monkeypatch.setattr(main, "mark_conversation_read", read)

    assert client.get("/api/conversations").status_code == 200
    assert client.get(f"/api/conversations/{THREAD_ID}/messages").status_code == 200
    assert client.post(f"/api/conversations/{THREAD_ID}/read").status_code == 200
    assert calls == [
        ("list", USER_A),
        ("messages", USER_A, THREAD_ID),
        ("read", USER_A, THREAD_ID),
    ]


def test_message_send_uses_verified_sender_and_path_recipient(client, monkeypatch):
    calls = []

    def not_suspended(settings, user_id, scope):
        calls.append(("suspension", user_id, scope))

    def send(settings, sender_id, recipient_id, body):
        calls.append(("send", sender_id, recipient_id, body))
        return {"id": "message-id", "thread_id": THREAD_ID}

    def notify(settings, user_id, *args, **kwargs):
        calls.append(("notify", user_id))

    monkeypatch.setattr(main, "ensure_user_not_suspended", not_suspended)
    monkeypatch.setattr(main, "send_message", send)
    monkeypatch.setattr(main, "create_notification", notify)

    response = client.post(f"/api/conversations/{USER_B}/messages", json={
        "body": "Hello",
        "sender_id": USER_B,
        "user_id": USER_B,
    })
    assert response.status_code == 201
    assert ("send", USER_A, USER_B, "Hello") in calls
    assert ("notify", USER_B) in calls


def test_admin_moderation_list_rejects_creator(client, monkeypatch):
    called = False

    def should_not_run(settings):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(main, "list_user_reports", should_not_run)
    response = client.get("/api/admin/reports")
    assert response.status_code == 403
    assert called is False
