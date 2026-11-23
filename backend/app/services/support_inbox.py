"""Private support-ticket persistence. Access is mediated by the API and service-role key."""
from uuid import UUID
from datetime import datetime, timezone
import httpx
from app.core.config import Settings

class SupportUnavailable(RuntimeError):
    pass

def _headers(settings: Settings):
    key=settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise SupportUnavailable("Support storage is not configured.")
    h={"apikey":key,"Content-Type":"application/json","Accept":"application/json"}
    if key.startswith("eyJ"): h["Authorization"]=f"Bearer {key}"
    return h

def _request(settings: Settings, method: str, table: str, *, params=None, payload=None, prefer=None):
    try:
        with httpx.Client(timeout=8.0) as client:
            response=client.request(method, f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}",
                params=params, json=payload, headers={**_headers(settings), **({"Prefer":prefer} if prefer else {})})
            response.raise_for_status()
            return response.json() if response.content else []
    except SupportUnavailable: raise
    except Exception as exc: raise SupportUnavailable("Support inbox is temporarily unavailable.") from exc

def create_ticket(settings: Settings, user_id: UUID, subject: str, body: str):
    rows=_request(settings,"POST","support_tickets",payload={"user_id":str(user_id),"subject":subject},
                  prefer="return=representation")
    if not isinstance(rows,list) or len(rows)!=1 or not rows[0].get("id"):
        raise SupportUnavailable("Could not create support ticket.")
    ticket=rows[0]
    _request(settings,"POST","support_ticket_messages",payload={
        "ticket_id":ticket["id"],"sender_user_id":str(user_id),"sender_role":"user","body":body})
    return ticket

def list_tickets(settings: Settings, *, user_id: UUID|None=None, limit: int=50):
    params={"select":"id,user_id,subject,status,created_at,updated_at,last_message_at",
            "order":"last_message_at.desc","limit":str(limit)}
    if user_id is not None: params["user_id"]=f"eq.{user_id}"
    rows=_request(settings,"GET","support_tickets",params=params)
    if not isinstance(rows,list): raise SupportUnavailable("Invalid support ticket list.")
    return rows

def get_ticket(settings: Settings, ticket_id: UUID):
    rows=_request(settings,"GET","support_tickets",params={"select":"id,user_id,subject,status,created_at,updated_at,last_message_at","id":f"eq.{ticket_id}","limit":"1"})
    if not isinstance(rows,list) or not rows: return None
    return rows[0]

def list_messages(settings: Settings, ticket_id: UUID):
    rows=_request(settings,"GET","support_ticket_messages",params={"select":"id,ticket_id,sender_user_id,sender_role,body,created_at","ticket_id":f"eq.{ticket_id}","order":"created_at.asc","limit":"200"})
    if not isinstance(rows,list): raise SupportUnavailable("Invalid support message list.")
    return rows

def add_message(settings: Settings, ticket_id: UUID, user_id: UUID, role: str, body: str):
    _request(settings,"POST","support_ticket_messages",payload={"ticket_id":str(ticket_id),"sender_user_id":str(user_id),"sender_role":role,"body":body})
    _request(settings,"PATCH","support_tickets",params={"id":f"eq.{ticket_id}"},
             payload={"last_message_at":datetime.now(timezone.utc).isoformat(),"updated_at":datetime.now(timezone.utc).isoformat(),
                      **({"status":"in_progress"} if role=="admin" else {"status":"waiting_user"})})

def update_ticket_status(settings: Settings, ticket_id: UUID, status: str):
    if status not in {"open","in_progress","waiting_user","resolved","closed"}:
        raise ValueError("Invalid support status.")
    _request(settings,"PATCH","support_tickets",params={"id":f"eq.{ticket_id}"},
             payload={"status":status,"updated_at":datetime.now(timezone.utc).isoformat()})
