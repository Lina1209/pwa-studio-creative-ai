import json
from decimal import Decimal
from uuid import UUID
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CharacterVisualPassport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    face: str = Field(default="", max_length=600)
    profile: str = Field(default="", max_length=600)
    fullBody: str = Field(default="", max_length=600)
    wardrobe: str = Field(default="", max_length=800)
    palette: str = Field(default="", max_length=300)
    expressions: str = Field(default="", max_length=500)


class VisualContinuityReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["character", "scene"]
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=3000)
    passport: CharacterVisualPassport | None = None


class ChatProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    idea: str = Field(default="", max_length=2000)
    genre: str = Field(default="", max_length=80)
    duration_minutes: int | None = Field(default=None, strict=True, ge=1, le=30)
    frame: Literal["16:9", "9:16", "1:1"] | None = None
    story: str = Field(default="", max_length=6000)
    storyboard: str = Field(default="", max_length=6000)
    characters: str = Field(default="", max_length=3000)
    visual_continuity: list[VisualContinuityReference] = Field(default_factory=list, max_length=12)
    voices: str = Field(default="", max_length=2000)
    edit: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def limit_total_context(self):
        data = self.model_dump()
        total = sum(len(value) for value in data.values() if isinstance(value, str))
        total += sum(
            len(ref.name) + len(ref.description)
            + (sum(len(value) for value in ref.passport.model_dump().values()) if ref.passport else 0)
            for ref in self.visual_continuity
        )
        if total > 18000:
            raise ValueError("Project context is too large.")
        return self


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12000)
    project_context: ChatProjectContext | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def limit_total_chat_context(self):
        total = sum(len(turn.content) for turn in self.history)
        if total > 12000:
            raise ValueError("Conversation history is too large.")
        return self


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
    project_context: ChatProjectContext | None = None


class PromptResponse(BaseModel):
    prompt: str
    provider: str
    model: str


class MovieScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    idea: str = Field(min_length=1, max_length=8000)
    genre: str = Field(default="Приключения", min_length=1, max_length=60)
    duration_minutes: int = Field(default=5, strict=True, ge=1, le=30)
    frame: Literal["16:9", "9:16", "1:1"] = "16:9"
    language: Literal["Русский", "English", "Қазақша"] = "Русский"

    @field_validator("title", "idea", "genre")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Text fields must not contain surrounding whitespace.")
        return value


class MovieScriptResponse(BaseModel):
    story: str = Field(min_length=1, max_length=30000)
    storyboard: str = Field(min_length=1, max_length=30000)
    provider: str
    model: str


class MovieDirectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    story: str = Field(min_length=50, max_length=30000)
    genre: str = Field(default="Приключения", min_length=1, max_length=60)
    duration_minutes: int = Field(default=5, strict=True, ge=1, le=30)
    frame: Literal["16:9", "9:16", "1:1"] = "16:9"
    language: Literal["Русский", "English", "Қазақша"] = "Русский"

    @field_validator("title", "story", "genre")
    @classmethod
    def require_trimmed_director_text(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Text fields must not contain surrounding whitespace.")
        return value


class MovieDirectorScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_number: int = Field(ge=1, le=100)
    title: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=240)
    time_of_day: str = Field(min_length=1, max_length=80)
    estimated_seconds: int = Field(ge=1, le=1800)
    characters: list[str] = Field(max_length=20)
    action: str = Field(min_length=1, max_length=3000)
    visual_description: str = Field(min_length=1, max_length=3000)
    camera_shots: list[str] = Field(min_length=1, max_length=8)
    lighting: str = Field(min_length=1, max_length=500)
    transition: str = Field(min_length=1, max_length=300)


class MovieDirectorResponse(BaseModel):
    scenes: list[MovieDirectorScene] = Field(min_length=1, max_length=100)
    provider: str
    model: str


class MovieStoryboardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    scenes: list[MovieDirectorScene] = Field(min_length=1, max_length=50)
    frame: Literal["16:9", "9:16", "1:1"] = "16:9"
    visual_style: str = Field(default="Кинематографичный реализм", min_length=1, max_length=120)
    language: Literal["Русский", "English", "Қазақша"] = "Русский"

    @field_validator("title", "visual_style")
    @classmethod
    def require_trimmed_storyboard_text(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Text fields must not contain surrounding whitespace.")
        return value

    @model_validator(mode="after")
    def require_sequential_input_scenes(self):
        if [scene.scene_number for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("Input scene numbers must be sequential.")
        return self


class MovieCharacterReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    appearance: str = Field(min_length=1, max_length=600)
    wardrobe: str = Field(min_length=1, max_length=400)
    signature_details: str = Field(min_length=1, max_length=400)
    reference_prompt: str = Field(min_length=1, max_length=1600)


class MovieStoryboardFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_number: int = Field(ge=1, le=20)
    duration_seconds: int = Field(ge=1, le=600)
    characters: list[str] = Field(default_factory=list, max_length=20)
    shot_type: str = Field(min_length=1, max_length=100)
    camera_angle: str = Field(min_length=1, max_length=160)
    camera_movement: str = Field(min_length=1, max_length=160)
    composition: str = Field(min_length=1, max_length=600)
    subject_focus: str = Field(min_length=1, max_length=300)
    visual_prompt: str = Field(min_length=1, max_length=1800)
    continuity_notes: str = Field(min_length=1, max_length=600)


class MovieStoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_number: int = Field(ge=1, le=50)
    frames: list[MovieStoryboardFrame] = Field(min_length=1, max_length=20)


class MovieStoryboardResponse(BaseModel):
    characters: list[MovieCharacterReference] = Field(max_length=100)
    scenes: list[MovieStoryboardScene] = Field(min_length=1, max_length=50)
    provider: str
    model: str


class SceneImageJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    quote_snapshot: dict | None = Field(default=None)

    @field_validator("width", "height")
    @classmethod
    def dimensions_must_be_multiple_of_64(cls, value: int) -> int:
        if value % 64:
            raise ValueError("Image dimensions must be multiples of 64.")
        return value



class VideoGenerationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)
    duration_seconds: int = Field(ge=1, le=600)
    resolution: Literal["480p", "720p", "1080p", "4k"] = "720p"
    quote_snapshot: dict | None = None


class AudioGenerationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=8000)
    duration_seconds: int = Field(ge=1, le=600)
    format: Literal["mp3", "wav", "flac"] = "mp3"
    quote_snapshot: dict | None = None


class SpeechGenerationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    voice: str | None = Field(default=None, min_length=1, max_length=100)
    language: str = Field(default="ru", min_length=2, max_length=16)
    quote_snapshot: dict | None = None


class PricingQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    project_id: UUID | None = None
    studio_scene_id: UUID | None = None
    request_snapshot: dict = Field()
    quantity: int = Field(default=1, strict=True, ge=1, le=10000)

    @field_validator("request_snapshot")
    @classmethod
    def bound_request_snapshot_size(cls, value: dict) -> dict:
        try:
            encoded = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("Pricing request snapshot must be valid JSON.") from exc
        if len(encoded) > 32 * 1024:
            raise ValueError("Pricing request snapshot must not exceed 32 KiB.")
        return value

    @model_validator(mode="after")
    def allow_only_one_generation_target(self):
        if self.project_id is not None and self.studio_scene_id is not None:
            raise ValueError("A pricing quote cannot target both a project and a scene.")
        return self

    @field_validator("job_type", "provider", "model")
    @classmethod
    def reject_whitespace_only_identity(cls, value: str) -> str:
        if not value.strip() or value.strip() != value:
            raise ValueError("Pricing identity fields must be trimmed and non-empty.")
        return value


class SiteVisitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    visitor_token: str = Field(min_length=20, max_length=128, pattern=r"^[a-f0-9]+$")
    route_group: str = Field(default="other", min_length=1, max_length=32)


class CreditHoldResponse(BaseModel):
    id: UUID
    job_id: UUID
    amount: int = Field(ge=1)
    status: Literal["held"]
    created_at: datetime


class CreditLedgerEntryResponse(BaseModel):
    id: int = Field(ge=1)
    operation_type: Literal["grant", "reserve", "capture", "release", "refund", "adjustment"]
    operation_key: str = Field(min_length=8, max_length=240)
    delta_available: int
    delta_reserved: int
    balance_available_after: int = Field(ge=0)
    balance_reserved_after: int = Field(ge=0)
    created_at: datetime


class CreditLotResponse(BaseModel):
    id: UUID
    lot_type: Literal["free", "subscription", "purchased", "bonus", "adjustment", "legacy"]
    granted_credits: int = Field(ge=1)
    available_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    expires_at: datetime | None = None
    created_at: datetime


class CreditHoldAllocationResponse(BaseModel):
    id: UUID
    hold_id: UUID
    lot_id: UUID
    amount: int = Field(ge=1)
    status: Literal["held"]
    created_at: datetime


class CreditWalletResponse(BaseModel):
    user_id: UUID
    currency_unit: Literal["credit"] = "credit"
    available_credits: int = Field(ge=0)
    reserved_credits: int = Field(ge=0)
    total_credits: int = Field(ge=0)
    holds: list[CreditHoldResponse]
    ledger: list[CreditLedgerEntryResponse]
    lots: list[CreditLotResponse]
    allocations: list[CreditHoldAllocationResponse]


class FinanceRoleGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: UUID
    role_code: Literal[
        "finance_operator", "finance_approver", "finance_executor",
        "support_readonly", "auditor_readonly",
    ]
    scope_key: str = Field(min_length=1, max_length=200)
    valid_until: datetime
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("scope_key", "reason")
    @classmethod
    def reject_untrimmed_values(cls, value):
        if value.strip() != value or not value:
            raise ValueError("Value must be trimmed and non-empty.")
        return value

    @field_validator("valid_until")
    @classmethod
    def expiry_must_be_timezone_aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Finance role expiry must include a timezone.")
        return value


class FinanceRoleRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reject_untrimmed_reason(cls, value: str) -> str:
        if value.strip() != value or not value:
            raise ValueError("Reason must be trimmed and non-empty.")
        return value



class FinanceOperationRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: Literal["credit_compensation", "billing_refund"]
    target_user_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: UUID

    @field_validator("reason")
    @classmethod
    def reject_untrimmed_finance_text(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Value must not contain surrounding whitespace.")
        return value

    @model_validator(mode="after")
    def validate_finance_amount_unit(self):
        if self.request_type == "credit_compensation":
            if self.currency_code != "CRD" or self.amount != self.amount.to_integral_value():
                raise ValueError("Credit compensation requires whole credits and CRD.")
        elif self.currency_code == "CRD":
            raise ValueError("Cash refunds require a currency code, not CRD.")
        return self


class FinanceOperationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reject_untrimmed_decision_reason(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Reason must not contain surrounding whitespace.")
        return value


class FinanceOperationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reject_untrimmed_cancel_reason(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Reason must not contain surrounding whitespace.")
        return value
