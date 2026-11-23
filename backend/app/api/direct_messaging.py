"""Authenticated API for private one-to-one conversations."""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.auth import StudioUser, get_current_user
from app.services.direct_messaging import (
    DirectMessagingUnavailable, create_conversation, list_conversations,
    read_messages, send_message, mark_read,
)

router = APIRouter(prefix="/api/messages/direct", tags=["private-messaging"])
settings = get_settings()


class ConversationCreate(BaseModel):
    model_config = {"extra": "forbid"}
    recipient_user_id: UUID


class DirectMessageCreate(BaseModel):
    model_config = {"extra": "forbid"}
    body: str = Field(min_length=1, max_length=5000)
    idempotency_key: UUID = Field(default_factory=uuid4)


def _unavailable():
    raise HTTPException(status_code=503, detail="Личные сообщения временно недоступны.")


@router.get("/conversations")
def get_my_conversations(user: StudioUser = Depends(get_current_user)):
    try:
        return {"conversations": list_conversations(settings, UUID(user.user_id))}
    except DirectMessagingUnavailable:
        _unavailable()


@router.post("/conversations", status_code=201)
def open_conversation(payload: ConversationCreate, user: StudioUser = Depends(get_current_user)):
    actor_id = UUID(user.user_id)
    if payload.recipient_user_id == actor_id:
        raise HTTPException(status_code=422, detail="Нельзя создать диалог с самим собой.")
    try:
        conversation_id = create_conversation(settings, actor_id, payload.recipient_user_id)
        return {"conversation_id": str(conversation_id)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Некорректный участник диалога.") from exc
    except DirectMessagingUnavailable:
        _unavailable()


@router.get("/conversations/{conversation_id}")
def get_conversation_messages(conversation_id: UUID, user: StudioUser = Depends(get_current_user)):
    try:
        messages = read_messages(settings, conversation_id, UUID(user.user_id))
        if messages is None:
            raise HTTPException(status_code=404, detail="Диалог не найден.")
        return {"messages": messages}
    except DirectMessagingUnavailable:
        _unavailable()


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def post_conversation_message(conversation_id: UUID, payload: DirectMessageCreate,
                              user: StudioUser = Depends(get_current_user)):
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Сообщение не может быть пустым.")
    try:
        message = send_message(settings, conversation_id, UUID(user.user_id),
                               body, payload.idempotency_key)
        if message is None:
            raise HTTPException(status_code=404, detail="Диалог не найден.")
        return {"message": message}
    except DirectMessagingUnavailable:
        _unavailable()


@router.patch("/conversations/{conversation_id}/read")
def mark_conversation_read(conversation_id: UUID, user: StudioUser = Depends(get_current_user)):
    try:
        if not mark_read(settings, conversation_id, UUID(user.user_id)):
            raise HTTPException(status_code=404, detail="Диалог не найден.")
        return {"status": "read"}
    except DirectMessagingUnavailable:
        _unavailable()
