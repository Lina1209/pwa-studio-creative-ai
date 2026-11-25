import httpx
from uuid import UUID
from fastapi import HTTPException

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


def _base(settings: Settings) -> str:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Assistant history storage is not configured.")
    return f"{settings.supabase_url.rstrip('/')}/rest/v1"


def save_assistant_reply(settings: Settings, user_id: str, conversation_id: str, content: str):
    """Persist an assistant message only after verifying its parent belongs to the JWT user."""
    try:
        owner_id = str(UUID(user_id))
        conversation_uuid = str(UUID(conversation_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="A valid conversation ID is required.") from exc
    if not content or not content.strip() or len(content) > 12000:
        raise HTTPException(status_code=422, detail="Assistant reply must contain 1–12000 characters.")

    base = _base(settings)
    headers = supabase_headers(settings)
    try:
        with httpx.Client(timeout=10.0) as client:
            parent = client.get(
                f"{base}/assistant_conversations",
                params={"select": "id", "id": f"eq.{conversation_uuid}", "user_id": f"eq.{owner_id}", "limit": "1"},
                headers=headers,
            )
            parent.raise_for_status()
            if not parent.json():
                raise HTTPException(status_code=404, detail="Conversation not found.")
            response = client.post(
                f"{base}/assistant_messages",
                params={"select": "id,conversation_id,user_id,role,content,created_at"},
                json={"conversation_id": conversation_uuid, "user_id": owner_id,
                      "role": "assistant", "content": content.strip()},
                headers=supabase_headers(settings, prefer="return=representation"),
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                raise HTTPException(status_code=502, detail="Assistant reply could not be saved.")
            return rows[0]
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="Assistant history storage rejected the write.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Assistant history storage is temporarily unavailable.") from exc
