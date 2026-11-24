"""Validated request/response contracts for the future owner-scoped Media Library API.

These models intentionally do not create routes or storage behavior by themselves.
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_ALLOWED_MIME_TYPES = {
    "image": {"image/jpeg", "image/png", "image/webp", "image/gif"},
    "video": {"video/mp4", "video/webm", "video/quicktime"},
    "audio": {"audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/webm", "audio/flac"},
    "voice": {"audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/webm", "audio/flac"},
    "document": {"text/plain", "text/markdown", "application/pdf", "application/rtf"},
}



class AssetUploadInitRequest(BaseModel):
    """Client declaration only; the server must verify the uploaded object later."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^(image|video|audio|voice|document)$")
    filename: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("filename must be a plain file name without path components")
        return value

    @field_validator("mime_type")
    @classmethod
    def normalize_mime_type(cls, value: str) -> str:
        value = value.strip().lower()
        if "/" not in value or ";" in value or " " in value:
            raise ValueError("mime_type must be a bare media type")
        return value

    @model_validator(mode="after")
    def validate_kind_mime_pair(self) -> "AssetUploadInitRequest":
        allowed = _ALLOWED_MIME_TYPES[self.kind]
        if self.mime_type not in allowed:
            raise ValueError("mime_type does not match the selected media kind")
        return self


class ProjectAssetAttachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    role: str = Field(pattern=r"^(cover|storyboard_reference|character_reference|background|soundtrack|voice_track|narration|script|export|other)$")
    slot: str | None = Field(default=None, max_length=80)
    position: int = Field(default=0, ge=0, le=999)

    @field_validator("slot")
    @classmethod
    def normalize_slot(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("slot must be a non-empty printable label")
        return value


class AssetListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(default=None, pattern=r"^(image|video|audio|voice|document)$")
    status: str | None = Field(default=None, pattern=r"^(pending|processing|ready|failed|quarantined|unavailable)$")
    usage: str | None = Field(default=None, pattern=r"^(used|unused|all)$")
    limit: int = Field(default=30, ge=1, le=100)


class AssetSafeResponse(BaseModel):
    """Safe metadata only; never include a raw bucket path or permanent signed URL."""

    id: UUID
    kind: str
    status: str
    display_name: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    created_at: str
    updated_at: str
    thumbnail_available: bool = False
    usage_count: int = Field(default=0, ge=0)


__all__ = [
    "AssetUploadInitRequest",
    "ProjectAssetAttachRequest",
    "AssetListQuery",
    "AssetSafeResponse",
]
