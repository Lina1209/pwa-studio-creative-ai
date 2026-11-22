import json
from uuid import UUID
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class SceneImageJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)

    @field_validator("width", "height")
    @classmethod
    def dimensions_must_be_multiple_of_64(cls, value: int) -> int:
        if value % 64:
            raise ValueError("Image dimensions must be multiples of 64.")
        return value


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
    scope_key: str | None = Field(default=None, min_length=1, max_length=200)
    valid_until: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("scope_key", "reason")
    @classmethod
    def reject_untrimmed_values(cls, value):
        if value is not None and value.strip() != value:
            raise ValueError("Value must not contain surrounding whitespace.")
        if value == "":
            raise ValueError("Value must not be empty.")
        return value

    @field_validator("valid_until")
    @classmethod
    def expiry_must_be_timezone_aware(cls, value):
        if value is not None and value.tzinfo is None:
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
