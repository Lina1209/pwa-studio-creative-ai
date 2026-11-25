from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12000)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=8000)
    purpose: str = Field(default="video", max_length=80)
    language: str = Field(default="English", max_length=40)
    style: str | None = Field(default=None, max_length=300)


class PromptResponse(BaseModel):
    prompt: str
    provider: str
    model: str


class ReportCreateRequest(BaseModel):
    category: str = Field(pattern=r"^(harassment|impersonation|spam|copyright|unsafe_content|privacy|other)$")
    description: str = Field(min_length=10, max_length=4000)
    reported_user_id: str | None = Field(default=None, max_length=64)
    content_reference: str | None = Field(default=None, max_length=500)

    @field_validator("reported_user_id")
    @classmethod
    def validate_reported_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("reported_user_id must be a valid account UUID") from exc


class ReportResponse(BaseModel):
    id: str
    status: str
    created_at: str


class ReportListItem(BaseModel):
    id: str
    reporter_user_id: str
    reported_user_id: str | None = None
    category: str
    description: str
    content_reference: str | None = None
    status: str
    moderator_note: str | None = None
    created_at: str


class ReportReviewRequest(BaseModel):
    status: str = Field(pattern=r"^(reviewing|resolved|rejected)$")
    moderator_note: str | None = Field(default=None, max_length=2000)


class SuspensionCreateRequest(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=5, max_length=1000)
    scope: str = Field(default="platform", pattern=r"^(platform|assistant|community)$")
    expires_at: str | None = Field(default=None, max_length=40)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("user_id must be a valid account UUID") from exc

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be an ISO 8601 timestamp") from exc
        if expiry.tzinfo is None or expiry.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return expiry.astimezone(timezone.utc).isoformat()


class SuspensionResponse(BaseModel):
    id: str
    user_id: str
    reason: str
    scope: str
    expires_at: str | None = None
    created_at: str


class SuspensionRevokeRequest(BaseModel):
    suspension_id: str = Field(min_length=36, max_length=36)

    @field_validator("suspension_id")
    @classmethod
    def validate_suspension_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("suspension_id must be a valid UUID") from exc


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str
    data: dict = Field(default_factory=dict)
    read_at: str | None = None
    created_at: str


class DirectMessageCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class DirectMessageEditRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class UserBlockRequest(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("user_id must be a valid account UUID") from exc


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_.]+$")
    display_name: str | None = Field(default=None, min_length=2, max_length=40)
    bio: str | None = Field(default=None, max_length=500)
    visibility: str | None = Field(default=None, pattern=r"^(public|private)$")
    show_in_directory: bool | None = None


class AssistantReplyPersistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    content: str = Field(min_length=1, max_length=12000)
