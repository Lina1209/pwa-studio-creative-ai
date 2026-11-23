from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CONVERSATION = "33333333-3333-4333-8333-333333333333"
KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_create_conversation_uses_authenticated_actor_and_supplied_recipient(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "create_conversation", lambda settings, actor, recipient:
                        captured.update(actor=actor, recipient=recipient) or UUID(CONVERSATION))
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        "/api/messages/direct/conversations", json={"recipient_user_id": OTHER})
    assert response.status_code == 201
    assert captured == {"actor": UUID(OWNER), "recipient": UUID(OTHER)}


def test_self_conversation_is_rejected_before_storage():
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        "/api/messages/direct/conversations", json={"recipient_user_id": OWNER})
    assert response.status_code == 422


def test_nonparticipant_cannot_read_messages(monkeypatch):
    import app.api.direct_messaging as api
    monkeypatch.setattr(api, "read_messages", lambda *args, **kwargs: None)
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).get(
        f"/api/messages/direct/conversations/{CONVERSATION}")
    assert response.status_code == 404


def test_nonparticipant_cannot_send_message(monkeypatch):
    import app.api.direct_messaging as api
    monkeypatch.setattr(api, "send_message", lambda *args, **kwargs: None)
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "hello", "idempotency_key": KEY})
    assert response.status_code == 404


def test_send_message_uses_authenticated_sender_and_trims_body(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "send_message", lambda settings, conversation, sender, body, key:
                        captured.update(conversation=conversation, sender=sender, body=body, key=key)
                        or {"message_id": "m1"})
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "  hello  ", "idempotency_key": KEY})
    assert response.status_code == 201
    assert captured == {"conversation": UUID(CONVERSATION), "sender": UUID(OWNER),
                        "body": "hello", "key": UUID(KEY)}


def test_message_rejects_untrusted_sender_field():
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "hello", "sender_user_id": OTHER})
    assert response.status_code == 422


def test_message_rejects_blank_body():
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "   "})
    assert response.status_code == 422


def test_conversation_list_is_scoped_to_verified_user(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "list_conversations", lambda settings, user_id:
                        captured.update(user_id=user_id) or [])
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).get(
        "/api/messages/direct/conversations")
    assert response.status_code == 200
    assert captured["user_id"] == UUID(OWNER)


def test_mark_read_is_scoped_to_verified_user(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "mark_read", lambda settings, conversation_id, user_id:
                        captured.update(conversation_id=conversation_id, user_id=user_id) or True)
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).patch(
        f"/api/messages/direct/conversations/{CONVERSATION}/read")
    assert response.status_code == 200
    assert captured == {"conversation_id": UUID(CONVERSATION), "user_id": UUID(OWNER)}


def test_message_notification_is_attempted_after_successful_send(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "send_message", lambda *args, **kwargs: {
        "message_id": "m1", "conversation_id": CONVERSATION,
        "sender_user_id": OWNER, "body": "hello"})
    monkeypatch.setattr(api, "create_message_notification",
                        lambda settings, message: captured.update(message=message))
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "hello", "idempotency_key": KEY})
    assert response.status_code == 201
    assert captured["message"]["message_id"] == "m1"


def test_notification_failure_does_not_hide_successful_message(monkeypatch):
    import app.api.direct_messaging as api
    from app.services.direct_messaging import DirectMessagingUnavailable
    monkeypatch.setattr(api, "send_message", lambda *args, **kwargs: {
        "message_id": "m1", "conversation_id": CONVERSATION,
        "sender_user_id": OWNER, "body": "hello"})
    def fail(*args, **kwargs):
        raise DirectMessagingUnavailable("notification unavailable")
    monkeypatch.setattr(api, "create_message_notification", fail)
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).post(
        f"/api/messages/direct/conversations/{CONVERSATION}/messages",
        json={"body": "hello", "idempotency_key": KEY})
    assert response.status_code == 201


def test_notification_list_is_scoped_to_authenticated_user(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "list_user_notifications", lambda settings, user_id:
                        captured.update(user_id=user_id) or [])
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).get(
        "/api/messages/direct/notifications")
    assert response.status_code == 200
    assert captured["user_id"] == UUID(OWNER)


def test_notification_read_is_scoped_to_authenticated_user(monkeypatch):
    import app.api.direct_messaging as api
    captured = {}
    monkeypatch.setattr(api, "mark_user_notification_read",
                        lambda settings, notification_id, user_id:
                        captured.update(notification_id=notification_id, user_id=user_id) or 1)
    notification_id = "44444444-4444-4444-8444-444444444444"
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).patch(
        f"/api/messages/direct/notifications/{notification_id}/read")
    assert response.status_code == 200
    assert captured == {"notification_id": UUID(notification_id), "user_id": UUID(OWNER)}
