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



def test_send_message_uses_atomic_database_rate_limit(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload, prefer))
        if table == "user_blocks":
            return []
        if table == "rpc/consume_message_rate_limit":
            return True
        if table == "conversation_threads":
            return [{"id": "44444444-4444-4444-8444-444444444444",
                     "user_a_id": USER_ID, "user_b_id": OTHER_ID}]
        if table == "direct_messages" and method == "POST":
            return [{"id": MESSAGE_ID, "thread_id": "44444444-4444-4444-8444-444444444444",
                     "created_at": "2026-11-23T12:00:00+00:00"}]
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)

    messaging_service.send_message(Settings(), USER_ID, OTHER_ID, "Hello")

    rate_call = next(call for call in calls if call[1] == "rpc/consume_message_rate_limit")
    assert rate_call[0] == "POST"
    assert rate_call[3] == {"p_user_id": USER_ID, "p_limit": 20, "p_window_seconds": 60}


def test_send_message_rejects_when_atomic_rate_limit_is_exhausted(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table))
        if table == "user_blocks":
            return []
        if table == "rpc/consume_message_rate_limit":
            return False
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)

    try:
        messaging_service.send_message(Settings(), USER_ID, OTHER_ID, "Hello")
    except HTTPException as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("Expected exhausted message rate limit to be rejected.")

    assert ("POST", "direct_messages") not in calls



def test_send_message_rejects_blocks_in_either_direction_before_rate_limit(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload))
        if table == "user_blocks":
            return [{"id": "blocked"}]
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)

    try:
        messaging_service.send_message(Settings(), USER_ID, OTHER_ID, "Hello")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Expected blocked pair to be rejected.")

    assert len(calls) == 1
    method, table, params, _ = calls[0]
    assert (method, table) == ("GET", "user_blocks")
    assert params["or"] == (
        f"(and(blocker_id.eq.{USER_ID},blocked_id.eq.{OTHER_ID}),"
        f"and(blocker_id.eq.{OTHER_ID},blocked_id.eq.{USER_ID}))"
    )


def test_block_user_uses_verified_blocker_and_target_pair(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload, prefer))
        return [{"id": "block-row"}]

    monkeypatch.setattr(messaging_service, "_request", fake_request)
    result = messaging_service.block_user(Settings(), USER_ID, OTHER_ID)

    assert result == {"blocked": True, "created": True}
    method, table, params, payload, prefer = calls[0]
    assert (method, table) == ("POST", "user_blocks")
    assert params == {"on_conflict": "blocker_id,blocked_id"}
    assert payload == {"blocker_id": USER_ID, "blocked_id": OTHER_ID}
    assert prefer == "resolution=ignore-duplicates,return=representation"


def test_unblock_user_deletes_only_callers_own_block(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params, payload, prefer))
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)
    result = messaging_service.unblock_user(Settings(), USER_ID, OTHER_ID)

    assert result == {"blocked": False}
    method, table, params, _, prefer = calls[0]
    assert (method, table) == ("DELETE", "user_blocks")
    assert params == {
        "blocker_id": f"eq.{USER_ID}",
        "blocked_id": f"eq.{OTHER_ID}",
    }
    assert prefer == "return=minimal"


def test_list_blocked_users_is_scoped_to_authenticated_blocker(monkeypatch):
    calls = []

    def fake_request(settings, method, table, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, table, params))
        return []

    monkeypatch.setattr(messaging_service, "_request", fake_request)
    assert messaging_service.list_blocked_users(Settings(), USER_ID) == []

    method, table, params = calls[0]
    assert (method, table) == ("GET", "user_blocks")
    assert params["blocker_id"] == f"eq.{USER_ID}"
    assert params["select"] == "blocked_id,created_at"
