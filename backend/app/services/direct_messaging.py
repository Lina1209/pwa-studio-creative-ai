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
        peer_profile = None
        if peer_ids:
            profiles = _request(settings, "GET", "profiles", params={
                "select": "id,username,display_name,profile_visibility",
                "id": f"in.({','.join(peer_ids)})", "limit": "1",
            })
            peer_profile = profiles[0] if isinstance(profiles, list) and profiles and profiles[0].get("profile_visibility") == "public" else None
        latest = _request(settings, "GET", "direct_messages", params={
            "select": "id,sender_user_id,body,created_at", "conversation_id": f"eq.{conversation_id}",
            "order": "created_at.desc,id.desc", "limit": "1",
        })
        item = dict(conversations[0])
        item["peer_user_id"] = peer_ids[0] if peer_ids else None
        item["peer_username"] = peer_profile.get("username") if peer_profile else None
        item["peer_display_name"] = peer_profile.get("display_name") if peer_profile else None
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


def create_message_notification(settings: Settings, message: dict):
    """Persist a recipient notification through a server-only RPC."""
    message_id = message.get("message_id") or message.get("id")
    conversation_id = message.get("conversation_id")
    sender_id = message.get("sender_user_id")
    body = str(message.get("body") or "").strip()
    if not message_id or not conversation_id or not sender_id:
        return None
    rows = _request(settings, "POST", "rpc/create_direct_message_notification", payload={
        "p_conversation_id": str(conversation_id),
        "p_message_id": str(message_id),
        "p_actor_user_id": str(sender_id),
        "p_title": "Новое личное сообщение",
        "p_body": body[:300] or "Вам отправили сообщение.",
        "p_dedupe_key": f"direct-message:{message_id}",
    })
    if isinstance(rows, str):
        return rows
    if isinstance(rows, list) and rows:
        value = rows[0]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("create_direct_message_notification") or value.get("id")
    raise DirectMessagingUnavailable("Could not persist direct message notification.")


def list_user_notifications(settings: Settings, user_id: UUID, *, limit: int = 50):
    rows = _request(settings, "GET", "user_notifications", params={
        "select": "id,conversation_id,message_id,kind,title,body,created_at,read_at",
        "recipient_user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(max(1, min(limit, 100))),
    })
    if not isinstance(rows, list):
        raise DirectMessagingUnavailable("Invalid notification list.")
    return rows


def mark_user_notification_read(settings: Settings, notification_id: UUID, user_id: UUID):
    owned = _request(settings, "GET", "user_notifications", params={
        "select": "id", "id": f"eq.{notification_id}",
        "recipient_user_id": f"eq.{user_id}", "read_at": "is.null", "limit": "1",
    })
    if not isinstance(owned, list) or not owned:
        return 0
    _request(settings, "PATCH", "user_notifications", params={
        "id": f"eq.{notification_id}", "recipient_user_id": f"eq.{user_id}",
        "read_at": "is.null",
    }, payload={"read_at": datetime.now(timezone.utc).isoformat()})
    return 1


def set_user_block(settings: Settings, blocker_id: UUID, blocked_id: UUID, blocked: bool):
    if blocker_id == blocked_id:
        raise ValueError("A user cannot block themselves.")
    rows = _request(settings, "POST", "rpc/set_direct_user_block", payload={
        "p_blocker_user_id": str(blocker_id),
        "p_blocked_user_id": str(blocked_id),
        "p_blocked": blocked,
    })
    return rows


def report_direct_message(settings: Settings, reporter_id: UUID, target_id: UUID,
                          message_id: UUID | None, category: str, details: str = ""):
    rows = _request(settings, "POST", "rpc/report_direct_message", payload={
        "p_reporter_user_id": str(reporter_id),
        "p_target_user_id": str(target_id),
        "p_message_id": str(message_id) if message_id else None,
        "p_category": category,
        "p_details": details.strip()[:2000],
    })
    if isinstance(rows, str):
        return rows
    if isinstance(rows, list) and rows:
        value = rows[0]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("report_direct_message") or value.get("id")
    raise DirectMessagingUnavailable("Could not submit safety report.")


def list_admin_reports(settings: Settings, status: str | None = None, limit: int = 100):
    params={"select":"id,reporter_user_id,target_user_id,message_id,category,details,status,created_at,reviewed_at",
            "order":"created_at.desc","limit":str(max(1,min(limit,200)))}
    if status: params["status"]=f"eq.{status}"
    rows=_request(settings,"GET","direct_message_reports",params=params)
    if not isinstance(rows,list): raise DirectMessagingUnavailable("Invalid report queue.")
    return rows


def list_admin_appeals(settings: Settings, status: str = "pending", limit: int = 100):
    rows=_request(settings,"GET","direct_moderation_appeals",params={
        "select":"id,user_id,reason,status,created_at,reviewed_at,decision_reason",
        "status":f"eq.{status}","order":"created_at.asc","limit":str(max(1,min(limit,200)))})
    if not isinstance(rows,list): raise DirectMessagingUnavailable("Invalid appeal queue.")
    return rows


def list_moderation_events(settings: Settings, user_id: UUID, limit: int = 50):
    rows=_request(settings,"GET","direct_moderation_events",params={
        "select":"id,target_user_id,actor_user_id,action,reason,expires_at,created_at",
        "target_user_id":f"eq.{user_id}","order":"created_at.desc","limit":str(max(1,min(limit,100)))})
    if not isinstance(rows,list): raise DirectMessagingUnavailable("Invalid moderation history.")
    return rows


def apply_user_moderation(settings: Settings,target_id: UUID,actor_id: UUID,action: str,reason: str,expires_at=None):
    rows=_request(settings,"POST","rpc/apply_direct_user_moderation",payload={
        "p_target_user_id":str(target_id),"p_actor_user_id":str(actor_id),"p_action":action,
        "p_reason":reason,"p_expires_at":expires_at.isoformat() if expires_at else None})
    if isinstance(rows,str): return rows
    if isinstance(rows,list) and rows:
        return rows[0] if isinstance(rows[0],str) else rows[0].get("apply_direct_user_moderation")
    raise DirectMessagingUnavailable("Could not apply moderation action.")


def update_report_status(settings: Settings,report_id: UUID,reviewer_id: UUID,status: str):
    rows=_request(settings,"POST","rpc/review_direct_message_report",payload={
        "p_report_id":str(report_id),"p_reviewer_user_id":str(reviewer_id),"p_status":status})
    return rows is True or rows == [True]


def create_moderation_appeal(settings: Settings,user_id: UUID,reason: str):
    rows=_request(settings,"POST","rpc/create_direct_moderation_appeal",payload={
        "p_user_id":str(user_id),"p_reason":reason})
    if isinstance(rows,str): return rows
    if isinstance(rows,list) and rows:
        return rows[0] if isinstance(rows[0],str) else rows[0].get("create_direct_moderation_appeal")
    raise DirectMessagingUnavailable("Could not submit appeal.")


def list_my_moderation_appeals(settings: Settings,user_id: UUID):
    rows=_request(settings,"GET","direct_moderation_appeals",params={
        "select":"id,reason,status,created_at,reviewed_at,decision_reason",
        "user_id":f"eq.{user_id}","order":"created_at.desc","limit":"20"})
    if not isinstance(rows,list): raise DirectMessagingUnavailable("Invalid appeal history.")
    return rows


def review_moderation_appeal(settings: Settings,appeal_id: UUID,reviewer_id: UUID,status: str,decision_reason: str):
    rows=_request(settings,"POST","rpc/review_direct_moderation_appeal",payload={
        "p_appeal_id":str(appeal_id),"p_reviewer_user_id":str(reviewer_id),
        "p_status":status,"p_decision_reason":decision_reason})
    return rows is True or rows == [True]


def get_admin_report_detail(settings: Settings, report_id: UUID):
    reports=_request(settings,"GET","direct_message_reports",params={
        "select":"id,reporter_user_id,target_user_id,message_id,category,details,status,created_at,reviewed_at",
        "id":f"eq.{report_id}","limit":"1"})
    if not isinstance(reports,list) or not reports:
        return None
    report=reports[0]
    message=None
    if report.get("message_id"):
        rows=_request(settings,"GET","direct_messages",params={
            "select":"id,conversation_id,sender_user_id,body,created_at",
            "id":f"eq.{report['message_id']}","limit":"1"})
        message=rows[0] if isinstance(rows,list) and rows else None
    return {"report":report,"message":message}
