"""Private support-ticket persistence. Access is mediated by the API and service-role key."""
from uuid import UUID
from datetime import datetime, timezone

import httpx

from app.core.config import Settings


class SupportUnavailable(RuntimeError):
    pass


def _headers(settings: Settings):
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise SupportUnavailable("Support storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(settings: Settings, method: str, resource: str, *, params=None, payload=None):
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.request(
                method,
                f"{settings.supabase_url.rstrip('/')}/rest/v1/{resource}",
                params=params,
                json=payload,
                headers=_headers(settings),
            )
            response.raise_for_status()
            return response.json() if response.content else []
    except SupportUnavailable:
        raise
    except Exception as exc:
        raise SupportUnavailable("Support inbox is temporarily unavailable.") from exc


def create_ticket(
    settings: Settings,
    user_id: UUID,
    subject: str,
    body: str,
    *,
    category: str = "general",
    context: dict | None = None,
):
    """Create a ticket and its first message in one database transaction."""
    rows = _request(
        settings,
        "POST",
        "rpc/create_support_ticket_with_message",
        payload={
            "p_user_id": str(user_id),
            "p_subject": subject,
            "p_body": body,
            "p_category": category,
            "p_context": context or {},
        },
    )
    if not isinstance(rows, list) or len(rows) != 1 or not rows[0].get("id"):
        raise SupportUnavailable("Could not create support ticket.")
    return rows[0]


def list_tickets(settings: Settings, *, user_id: UUID | None = None, limit: int = 50):
    params = {
        "select": "id,user_id,subject,category,status,created_at,updated_at,last_message_at,first_response_at,resolved_at,closed_at",
        "order": "last_message_at.desc",
        "limit": str(limit),
    }
    if user_id is not None:
        params["user_id"] = f"eq.{user_id}"
    rows = _request(settings, "GET", "support_tickets", params=params)
    if not isinstance(rows, list):
        raise SupportUnavailable("Invalid support ticket list.")
    return rows


def get_ticket(settings: Settings, ticket_id: UUID):
    rows = _request(
        settings,
        "GET",
        "support_tickets",
        params={
            "select": "id,user_id,subject,category,context,status,created_at,updated_at,last_message_at,first_response_at,resolved_at,closed_at",
            "id": f"eq.{ticket_id}",
            "limit": "1",
        },
    )
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def list_messages(settings: Settings, ticket_id: UUID):
    rows = _request(
        settings,
        "GET",
        "support_ticket_messages",
        params={
            "select": "id,ticket_id,sender_user_id,sender_role,body,created_at",
            "ticket_id": f"eq.{ticket_id}",
            "order": "created_at.asc",
            "limit": "200",
        },
    )
    if not isinstance(rows, list):
        raise SupportUnavailable("Invalid support message list.")
    return rows


def add_message(settings: Settings, ticket_id: UUID, user_id: UUID, role: str, body: str):
    """Append a message and advance the ticket state atomically.

    User replies reopen the support queue (open); administrator replies wait
    for the user (waiting_user). The database RPC performs both writes together.
    """
    if role not in {"user", "admin"}:
        raise ValueError("Invalid support sender role.")
    _request(
        settings,
        "POST",
        "rpc/add_support_ticket_message",
        payload={
            "p_ticket_id": str(ticket_id),
            "p_sender_user_id": str(user_id),
            "p_sender_role": role,
            "p_body": body,
        },
    )


def update_ticket_status(settings: Settings, ticket_id: UUID, status: str):
    if status not in {"open", "in_progress", "waiting_user", "resolved", "closed"}:
        raise ValueError("Invalid support status.")
    now = datetime.now(timezone.utc).isoformat()
    _request(
        settings,
        "PATCH",
        "support_tickets",
        params={"id": f"eq.{ticket_id}"},
        payload={
            "status": status,
            "updated_at": now,
            "resolved_at": now if status == "resolved" else None,
            "closed_at": now if status == "closed" else None,
        },
    )
