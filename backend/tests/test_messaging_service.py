from fastapi import HTTPException

from app.core.config import Settings
from app.services import messaging_service


USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"


def test_delete_message_repeats_participant_guard_in_update(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload))
        if method == "GET":
            return [{"id": MESSAGE_ID, "sender_id": USER_ID, "recipient_id": OTHER_ID}]
        return [{"id": MESSAGE_ID}]

    monkeypatch.setattr(messaging_service, "_request", fake_request)

    result = messaging_service.delete_message_for_self(Settings(), USER_ID, MESSAGE_ID)

    assert result == {"deleted_for_you": True}
    assert len(calls) == 2
    method, table, params, payload = calls[1]
    assert (method, table) == ("PATCH", "direct_messages")
    assert params["id"] == f"eq.{MESSAGE_ID}"
    assert params["or"] == f"(sender_id.eq.{USER_ID},recipient_id.eq.{USER_ID})"
    assert "deleted_for_sender_at" in payload
    assert "deleted_for_recipient_at" not in payload


def test_delete_message_does_not_update_for_non_participant(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload))
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)

    try:
        messaging_service.delete_message_for_self(Settings(), USER_ID, MESSAGE_ID)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected non-participant deletion to be rejected.")

    assert len(calls) == 1
    assert calls[0][0] == "GET"
