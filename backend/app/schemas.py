from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


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

