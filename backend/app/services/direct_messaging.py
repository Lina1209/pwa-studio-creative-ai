"""Private one-to-one messaging persistence via server-only Supabase credentials."""
from datetime import datetime, timezone
from uuid import UUID

import httpx

from app.core.config import Settings


class DirectMessagingUnavailable(RuntimeError):
    pass


def _headers(settings: Settings):
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise DirectMessagingUnavailable("Direct messaging storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(settings: Settings, method: str, resource: str, *, params=None, payload=None):
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.request(
                method, f"{settings.supabase_url.rstrip('/')}/rest/v1/{resource}",
                params=params, json=payload, headers=_headers(settings),
            )
            response.raise_for_status()
            return response.json() if response.content else []
    except DirectMessagingUnavailable:
        raise
    except Exception as exc:
        raise DirectMessagingUnavailable("Private messages are temporarily unavailable.") from exc


def create_conversation(settings: Settings, actor_id: UUID, recipient_id: UUID):
    if actor_id == recipient_id:
        raise ValueError("A conversation requires two different users.")
    rows = _request(settings, "POST", "rpc/create_direct_conversation", payload={
        "p_actor_user_id": str(actor_id), "p_recipient_user_id": str(recipient_id),
    })
    if isinstance(rows, str):
        return UUID(rows)
    if isinstance(rows, list) and len(rows) == 1:
        value = rows[0]
        if isinstance(value, str):
            return UUID(value)
        if isinstance(value, dict):
            candidate = value.get("create_direct_conversation") or value.get("id")
            if candidate:
                return UUID(str(candidate))
    raise DirectMessagingUnavailable("Could not open private conversation.")


def _require_participant(settings: Settings, conversation_id: UUID, user_id: UUID):
    rows = _request(settings, "GET", "direct_conversation_participants", params={
        "select": "conversation_id,user_id,last_read_at",
        "conversation_id": f"eq.{conversation_id}", "user_id": f"eq.{user_id}", "limit": "1",
    })
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def list_conversations(settings: Settings, user_id: UUID, *, limit: int = 50):
    memberships = _request(settings, "GET", "direct_conversation_participants", params={
        "select": "conversation_id,last_read_at",
        "user_id": f"eq.{user_id}", "order": "joined_at.desc", "limit": str(max(1, min(limit, 100))),
    })
    if not isinstance(memberships, list) or not memberships:
        return []
    result = []
    for membership in memberships:
        conversation_id = membership.get("conversation_id")
        if not conversation_id:
            continue
        conversations = _request(settings, "GET", "direct_conversations", params={
            "select": "id,created_at,last_message_at", "id": f"eq.{conversation_id}", "limit": "1",
        })
        if not isinstance(conversations, list) or not conversations:
            continue
        participants = _request(settings, "GET", "direct_conversation_participants", params={
            "select": "user_id", "conversation_id": f"eq.{conversation_id}",
        })
        peer_ids = [row["user_id"] for row in participants
                    if row.get("user_id") and row["user_id"] != str(user_id)]
        latest = _request(settings, "GET", "direct_messages", params={
            "select": "id,sender_user_id,body,created_at", "conversation_id": f"eq.{conversation_id}",
            "order": "created_at.desc,id.desc", "limit": "1",
        })
        item = dict(conversations[0])
        item["peer_user_id"] = peer_ids[0] if peer_ids else None
        item["last_read_at"] = membership.get("last_read_at")
        item["last_message"] = latest[0] if isinstance(latest, list) and latest else None
        result.append(item)
    result.sort(key=lambda item: item.get("last_message_at") or "", reverse=True)
    return result


def read_messages(settings: Settings, conversation_id: UUID, user_id: UUID, *, limit: int = 100):
    if not _require_participant(settings, conversation_id, user_id):
        return None
    rows = _request(settings, "GET", "direct_messages", params={
        "select": "id,conversation_id,sender_user_id,body,created_at",
        "conversation_id": f"eq.{conversation_id}", "order": "created_at.asc,id.asc",
        "limit": str(max(1, min(limit, 200))),
    })
    if not isinstance(rows, list):
        raise DirectMessagingUnavailable("Invalid private message history.")
    return rows


def send_message(settings: Settings, conversation_id: UUID, sender_id: UUID,
                 body: str, idempotency_key: UUID):
    if not _require_participant(settings, conversation_id, sender_id):
        return None
    rows = _request(settings, "POST", "rpc/send_direct_message", payload={
        "p_conversation_id": str(conversation_id), "p_sender_user_id": str(sender_id),
        "p_body": body, "p_idempotency_key": str(idempotency_key),
    })
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
        return rows[0]
    raise DirectMessagingUnavailable("Could not send private message.")


def mark_read(settings: Settings, conversation_id: UUID, user_id: UUID):
    membership = _require_participant(settings, conversation_id, user_id)
    if not membership:
        return False
    _request(settings, "PATCH", "direct_conversation_participants", params={
        "conversation_id": f"eq.{conversation_id}", "user_id": f"eq.{user_id}",
    }, payload={"last_read_at": datetime.now(timezone.utc).isoformat()})
    return True
