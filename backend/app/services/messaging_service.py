import httpx
from datetime import datetime, timezone, timedelta
from uuid import UUID
from fastapi import HTTPException

from app.core.config import Settings


def _request(settings: Settings, method: str, table: str, *, params=None, payload=None, prefer="return=representation"):
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Messaging storage is not configured.")
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    try:
        response = httpx.request(
            method, f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}",
            headers=headers, params=params, json=payload, timeout=12.0,
        )
        response.raise_for_status()
        return response.json() if response.content else []
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="Messaging storage rejected the request.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Messaging storage is temporarily unavailable.") from exc


def _canonical_pair(first: str, second: str):
    try:
        a, b = UUID(first), UUID(second)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="A valid account ID is required.") from exc
    if a == b:
        raise HTTPException(status_code=400, detail="You cannot start a conversation with yourself.")
    return tuple(sorted((str(a), str(b))))


def list_conversations(settings: Settings, user_id: str):
    return _request(settings, "GET", "conversation_threads", params={
        "select": "id,user_a_id,user_b_id,created_at,updated_at,last_message_at",
        "or": f"(user_a_id.eq.{user_id},user_b_id.eq.{user_id})",
        "order": "last_message_at.desc.nullslast,created_at.desc", "limit": "100",
    })


def _get_or_create_thread(settings: Settings, user_id: str, recipient_id: str):
    user_a, user_b = _canonical_pair(user_id, recipient_id)
    rows = _request(settings, "POST", "conversation_threads",
        params={"on_conflict": "user_a_id,user_b_id"},
        payload={"user_a_id": user_a, "user_b_id": user_b},
        prefer="resolution=ignore-duplicates,return=representation")
    if rows:
        return rows[0]
    rows = _request(settings, "GET", "conversation_threads", params={
        "select": "id,user_a_id,user_b_id,created_at,updated_at,last_message_at",
        "user_a_id": f"eq.{user_a}", "user_b_id": f"eq.{user_b}", "limit": "1",
    })
    if not rows:
        raise HTTPException(status_code=502, detail="Conversation could not be opened.")
    return rows[0]


def send_message(settings: Settings, sender_id: str, recipient_id: str, body: str):
    _canonical_pair(sender_id, recipient_id)
    if not body or not body.strip():
        raise HTTPException(status_code=422, detail="Message text cannot be empty.")
    recent = _request(settings, "GET", "direct_messages", params={
        "select": "id", "sender_id": f"eq.{sender_id}",
        "created_at": f"gte.{(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}",
        "limit": "21",
    })
    if len(recent) >= 20:
        raise HTTPException(status_code=429, detail="Please wait before sending more messages.")
    thread = _get_or_create_thread(settings, sender_id, recipient_id)
    rows = _request(settings, "POST", "direct_messages",
        params={"select": "id,thread_id,sender_id,recipient_id,body,read_at,created_at"},
        payload={"thread_id": thread["id"], "sender_id": sender_id,
                 "recipient_id": recipient_id, "body": body.strip(), "attachments": []})
    if not rows:
        raise HTTPException(status_code=502, detail="Message could not be sent.")
    message = rows[0]
    _request(settings, "PATCH", "conversation_threads",
        params={"id": f"eq.{thread['id']}"},
        payload={"last_message_at": message["created_at"], "updated_at": message["created_at"]})
    return message


def list_messages(settings: Settings, user_id: str, thread_id: str):
    try:
        thread_uuid = str(UUID(thread_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="A valid conversation ID is required.") from exc
    threads = _request(settings, "GET", "conversation_threads", params={
        "select": "id,user_a_id,user_b_id", "id": f"eq.{thread_uuid}",
        "or": f"(user_a_id.eq.{user_id},user_b_id.eq.{user_id})", "limit": "1",
    })
    if not threads:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _request(settings, "GET", "direct_messages", params={
        "select": "id,thread_id,sender_id,recipient_id,body,read_at,created_at,edited_at",
        "thread_id": f"eq.{thread_uuid}",
        "or": f"(and(sender_id.eq.{user_id},deleted_for_sender_at.is.null),and(recipient_id.eq.{user_id},deleted_for_recipient_at.is.null))",
        "order": "created_at.asc", "limit": "200",
    })


def mark_conversation_read(settings: Settings, user_id: str, thread_id: str):
    try:
        thread_uuid = str(UUID(thread_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="A valid conversation ID is required.") from exc
    threads = _request(settings, "GET", "conversation_threads", params={
        "select": "id", "id": f"eq.{thread_uuid}",
        "or": f"(user_a_id.eq.{user_id},user_b_id.eq.{user_id})", "limit": "1",
    })
    if not threads:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    now = datetime.now(timezone.utc).isoformat()
    rows = _request(settings, "PATCH", "direct_messages", params={
        "thread_id": f"eq.{thread_uuid}", "recipient_id": f"eq.{user_id}",
        "read_at": "is.null", "select": "id",
    }, payload={"read_at": now})
    return {"updated": len(rows)}
