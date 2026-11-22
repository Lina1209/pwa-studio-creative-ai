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
