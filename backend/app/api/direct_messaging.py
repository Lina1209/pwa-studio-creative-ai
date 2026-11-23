"""Authenticated API for private one-to-one conversations."""
from uuid import UUID, uuid4
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.auth import StudioUser, get_current_user, require_permission
from app.services.direct_messaging import (
    DirectMessagingUnavailable, create_conversation, list_conversations,
    read_messages, send_message, mark_read,
    create_message_notification, list_user_notifications, mark_user_notification_read,
    set_user_block, report_direct_message, list_admin_reports, list_admin_appeals,
    list_moderation_events, apply_user_moderation, update_report_status,
    create_moderation_appeal, list_my_moderation_appeals, review_moderation_appeal,
)

from app.services.admin_audit_service import record_admin_audit_event, AdminAuditUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messages/direct", tags=["private-messaging"])
settings = get_settings()


class ConversationCreate(BaseModel):
    model_config = {"extra": "forbid"}
    recipient_user_id: UUID


class DirectMessageCreate(BaseModel):
    model_config = {"extra": "forbid"}
    body: str = Field(min_length=1, max_length=5000)
    idempotency_key: UUID = Field(default_factory=uuid4)


class DirectMessageReportCreate(BaseModel):
    model_config = {"extra": "forbid"}
    target_user_id: UUID
    message_id: UUID | None = None
    category: str = Field(pattern="^(spam|harassment|scam|threats|inappropriate|other)$")
    details: str = Field(default="", max_length=2000)


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
        try:
            create_message_notification(settings, message)
        except DirectMessagingUnavailable:
            # Saving the message is primary; notification persistence is best-effort.
            logger.warning("Direct message saved but notification persistence failed.")
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


@router.get("/notifications")
def get_my_direct_notifications(user: StudioUser = Depends(get_current_user)):
    try:
        return {"notifications": list_user_notifications(settings, UUID(user.user_id))}
    except DirectMessagingUnavailable:
        _unavailable()


@router.patch("/notifications/{notification_id}/read")
def mark_direct_notification_read(notification_id: UUID,
                                  user: StudioUser = Depends(get_current_user)):
    try:
        if not mark_user_notification_read(settings, notification_id, UUID(user.user_id)):
            raise HTTPException(status_code=404, detail="Уведомление не найдено.")
        return {"status": "read"}
    except DirectMessagingUnavailable:
        _unavailable()



@router.put("/users/{target_user_id}/block")
def block_direct_user(target_user_id: UUID, user: StudioUser = Depends(get_current_user)):
    actor_id = UUID(user.user_id)
    if target_user_id == actor_id:
        raise HTTPException(status_code=422, detail="Нельзя заблокировать самого себя.")
    try:
        set_user_block(settings, actor_id, target_user_id, True)
        return {"status": "blocked"}
    except DirectMessagingUnavailable:
        _unavailable()


@router.delete("/users/{target_user_id}/block")
def unblock_direct_user(target_user_id: UUID, user: StudioUser = Depends(get_current_user)):
    actor_id = UUID(user.user_id)
    if target_user_id == actor_id:
        raise HTTPException(status_code=422, detail="Некорректный пользователь.")
    try:
        set_user_block(settings, actor_id, target_user_id, False)
        return {"status": "unblocked"}
    except DirectMessagingUnavailable:
        _unavailable()


@router.post("/reports", status_code=201)
def submit_direct_message_report(payload: DirectMessageReportCreate,
                                 user: StudioUser = Depends(get_current_user)):
    actor_id = UUID(user.user_id)
    if payload.target_user_id == actor_id:
        raise HTTPException(status_code=422, detail="Нельзя пожаловаться на самого себя.")
    try:
        report_id = report_direct_message(
            settings, actor_id, payload.target_user_id, payload.message_id,
            payload.category, payload.details,
        )
        return {"report_id": str(report_id)}
    except DirectMessagingUnavailable:
        _unavailable()


class ModerationActionCreate(BaseModel):
    model_config = {"extra": "forbid"}
    action: str = Field(pattern="^(warn|mute|ban|unmute|unban)$")
    reason: str = Field(min_length=1,max_length=500)
    duration_hours: int | None = Field(default=None,ge=1,le=8760)

class ReportReviewUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status: str = Field(pattern="^(reviewing|resolved|dismissed)$")

class AppealCreate(BaseModel):
    model_config = {"extra": "forbid"}
    reason: str = Field(min_length=10,max_length=2000)

class AppealReviewUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status: str = Field(pattern="^(accepted|rejected)$")
    decision_reason: str = Field(min_length=1,max_length=500)


@router.get("/moderation/appeals")
def get_my_moderation_appeals(user: StudioUser = Depends(get_current_user)):
    try:
        return {"appeals":list_my_moderation_appeals(settings,UUID(user.user_id))}
    except DirectMessagingUnavailable:
        _unavailable()


@router.post("/moderation/appeals",status_code=201)
def submit_moderation_appeal(payload: AppealCreate,user: StudioUser = Depends(get_current_user)):
    try:
        appeal_id=create_moderation_appeal(settings,UUID(user.user_id),payload.reason)
        return {"appeal_id":str(appeal_id),"status":"pending"}
    except DirectMessagingUnavailable:
        _unavailable()


@router.get("/admin/reports")
def admin_list_message_reports(status: str | None = None,user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    if status not in (None,"open","reviewing","resolved","dismissed"):
        raise HTTPException(status_code=422,detail="Некорректный фильтр жалоб.")
    try:
        rows=list_admin_reports(settings,status=status)
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.report.view",outcome="allowed",
            resource_type="direct_message_report",reason="Admin opened private message report queue")
        return {"reports":rows}
    except (DirectMessagingUnavailable,AdminAuditUnavailable):
        _unavailable()


@router.patch("/admin/reports/{report_id}")
def admin_review_message_report(report_id: UUID,payload: ReportReviewUpdate,
    user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    try:
        if not update_report_status(settings,report_id,payload.status):
            raise HTTPException(status_code=404,detail="Жалоба не найдена.")
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.moderation.action",outcome="executed",
            resource_type="direct_message_report",resource_id=report_id,
            reason=f"Report status changed to {payload.status}")
        return {"status":payload.status}
    except (DirectMessagingUnavailable,AdminAuditUnavailable):
        _unavailable()


@router.post("/admin/users/{target_user_id}/actions",status_code=201)
def admin_moderate_direct_user(target_user_id: UUID,payload: ModerationActionCreate,
    user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    if target_user_id==UUID(user.user_id):
        raise HTTPException(status_code=422,detail="Нельзя применять модерацию к собственному аккаунту.")
    if payload.action in ("unmute","unban") and payload.duration_hours is not None:
        raise HTTPException(status_code=422,detail="Для снятия ограничения срок не указывается.")
    from datetime import datetime,timedelta,timezone
    expires_at=datetime.now(timezone.utc)+timedelta(hours=payload.duration_hours) if payload.duration_hours else None
    try:
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.moderation.action",outcome="requested",
            resource_type="user",resource_id=target_user_id,
            reason=f"Requested {payload.action}: {payload.reason[:350]}")
        event_id=apply_user_moderation(settings,target_user_id,UUID(user.user_id),
            payload.action,payload.reason.strip(),expires_at)
        try:
            record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
                action="admin.direct_message.moderation.action",outcome="executed",
                resource_type="user",resource_id=target_user_id,
                reason=f"Applied {payload.action}: {payload.reason[:350]}")
        except AdminAuditUnavailable:
            logger.error("Moderation action applied but completion audit failed.")
        return {"event_id":str(event_id),"action":payload.action,
                "expires_at":expires_at.isoformat() if expires_at else None}
    except (DirectMessagingUnavailable,AdminAuditUnavailable):
        _unavailable()


@router.get("/admin/users/{target_user_id}/history")
def admin_get_direct_user_moderation_history(target_user_id: UUID,
    user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    try:
        return {"events":list_moderation_events(settings,target_user_id)}
    except DirectMessagingUnavailable:
        _unavailable()


@router.get("/admin/appeals")
def admin_list_moderation_appeals(user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    try:
        rows=list_admin_appeals(settings)
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.appeal.review",outcome="allowed",
            resource_type="direct_moderation_appeal",reason="Admin opened appeal queue")
        return {"appeals":rows}
    except (DirectMessagingUnavailable,AdminAuditUnavailable):
        _unavailable()


@router.patch("/admin/appeals/{appeal_id}")
def admin_decide_moderation_appeal(appeal_id: UUID,payload: AppealReviewUpdate,
    user: StudioUser = Depends(require_permission("admin.direct_messages.moderate"))):
    try:
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.appeal.review",outcome="requested",
            resource_type="direct_moderation_appeal",resource_id=appeal_id,
            reason=f"Appeal decision requested: {payload.status}")
        if not review_moderation_appeal(settings,appeal_id,UUID(user.user_id),
            payload.status,payload.decision_reason):
            raise HTTPException(status_code=404,detail="Апелляция не найдена или уже рассмотрена.")
        record_admin_audit_event(settings,actor_user_id=UUID(user.user_id),
            action="admin.direct_message.appeal.review",outcome="executed",
            resource_type="direct_moderation_appeal",resource_id=appeal_id,
            reason=f"Appeal {payload.status}: {payload.decision_reason[:350]}")
        return {"status":payload.status}
    except (DirectMessagingUnavailable,AdminAuditUnavailable):
        _unavailable()
