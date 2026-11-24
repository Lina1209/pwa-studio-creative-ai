from app.core.config import Settings
from app.services import notification_service


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
NOTICE_ID = "33333333-3333-4333-8333-333333333333"


def test_notification_list_is_scoped_to_requested_owner(monkeypatch):
    calls = []

    def fake_request(settings, method, *, params=None, payload=None):
        calls.append((method, params, payload))
        return []

    monkeypatch.setattr(notification_service, "_request", fake_request)
    assert notification_service.list_notifications(Settings(), USER_A) == []
    method, params, _ = calls[0]
    assert method == "GET"
    assert params["user_id"] == f"eq.{USER_A}"
    assert "user_id" not in params["select"]


def test_mark_notification_read_requires_both_notification_and_owner(monkeypatch):
    calls = []

    def fake_request(settings, method, *, params=None, payload=None):
        calls.append((method, params, payload))
        return [{"id": NOTICE_ID, "read_at": "now"}]

    monkeypatch.setattr(notification_service, "_request", fake_request)
    notification_service.mark_notification_read(Settings(), USER_A, NOTICE_ID)
    method, params, payload = calls[0]
    assert method == "PATCH"
    assert params["id"] == f"eq.{NOTICE_ID}"
    assert params["user_id"] == f"eq.{USER_A}"
    assert "read_at" in payload


def test_mark_all_notifications_read_only_updates_unread_owner_rows(monkeypatch):
    calls = []

    def fake_request(settings, method, *, params=None, payload=None):
        calls.append((method, params, payload))
        return [{"id": NOTICE_ID}]

    monkeypatch.setattr(notification_service, "_request", fake_request)
    result = notification_service.mark_all_notifications_read(Settings(), USER_A)
    method, params, payload = calls[0]
    assert result == {"updated": 1}
    assert method == "PATCH"
    assert params["user_id"] == f"eq.{USER_A}"
    assert params["read_at"] == "is.null"
    assert "read_at" in payload


def test_notification_creation_uses_explicit_recipient_and_allowlisted_fields(monkeypatch):
    calls = []

    def fake_request(settings, method, *, params=None, payload=None):
        calls.append((method, params, payload))
        return [{"id": NOTICE_ID, "user_id": USER_B}]

    monkeypatch.setattr(notification_service, "_request", fake_request)
    notification_service.create_notification(
        Settings(), USER_B, "direct_message", "New message", "You have a message",
        {"thread_id": "thread-id"},
    )
    method, params, payload = calls[0]
    assert method == "POST"
    assert params["select"] == "id,user_id,type,title,body,data,read_at,created_at"
    assert payload["user_id"] == USER_B
    assert payload["type"] == "direct_message"
    assert payload["data"] == {"thread_id": "thread-id"}
    assert "sender_id" not in payload
    assert "owner_id" not in payload
