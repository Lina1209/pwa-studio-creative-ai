"""Authenticated character passport CRUD routes; guest libraries remain browser-local."""
from uuid import UUID
from fastapi import APIRouter, Depends, Response, Query
from pydantic import BaseModel, ConfigDict, Field
from app.services.auth import StudioUser, get_current_user
from app.services.character_repository import (
    list_owned_characters, create_owned_character, get_owned_character, update_owned_character,
)

class CharacterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_local_id: UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    reference_data: dict = Field(default_factory=dict)

class CharacterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    reference_data: dict | None = None

def build_character_router(settings):
    router = APIRouter()
    @router.get("/characters")
    def list_characters(response: Response, cursor: str | None = Query(default=None, max_length=2048), limit: int = Query(default=50, ge=1, le=100), user: StudioUser = Depends(get_current_user)):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return list_owned_characters(settings, user.user_id, cursor=cursor, page_size=limit)
    @router.post("/characters", status_code=201)
    def create_character(payload: CharacterCreate, response: Response, user: StudioUser = Depends(get_current_user)):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return create_owned_character(settings, user.user_id, str(payload.source_local_id), payload.name, payload.description, payload.reference_data)
    @router.get("/characters/{character_id}")
    def read_character(character_id: str, response: Response, user: StudioUser = Depends(get_current_user)):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return get_owned_character(settings, user.user_id, character_id)
    @router.patch("/characters/{character_id}")
    def patch_character(character_id: str, payload: CharacterPatch, response: Response, user: StudioUser = Depends(get_current_user)):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
        return update_owned_character(settings, user.user_id, character_id, payload.expected_version, changes)
    return router
