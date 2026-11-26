from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    reply: str
    provider: str
    model: str


class PromptRequest(BaseModel):
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


class SuspensionResponse(BaseModel):
    id: str
    user_id: str
    reason: str
    scope: str
    expires_at: str | None = None
    created_at: str


class SuspensionRevokeRequest(BaseModel):
    suspension_id: str = Field(min_length=36, max_length=36)


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


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_.]+$")
    display_name: str | None = Field(default=None, min_length=2, max_length=40)
    bio: str | None = Field(default=None, max_length=500)
    visibility: str | None = Field(default=None, pattern=r"^(public|private)$")
    show_in_directory: bool | None = None
