from uuid import UUID

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
    quantity: int = Field(default=1, ge=1, le=10000)

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
