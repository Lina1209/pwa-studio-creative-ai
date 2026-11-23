"""Authenticated creator profile and public directory API."""
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.auth import StudioUser, get_current_user
from app.services.profiles import (
    ProfileUnavailable, get_my_profile, update_my_profile,
    search_public_profiles, get_public_profile,
)

router = APIRouter(prefix="/api/profiles", tags=["creator-profiles"])
settings = get_settings()
logger = logging.getLogger(__name__)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None, min_length=3, max_length=24, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str | None = Field(default=None, min_length=2, max_length=40)
    bio: str | None = Field(default=None, max_length=160)
    profile_visibility: str | None = None
    discoverable: bool | None = None
    allow_direct_messages: bool | None = None


def _unavailable():
    raise HTTPException(status_code=503, detail="Профили временно недоступны.")


@router.get("/me")
def my_profile(user: StudioUser = Depends(get_current_user)):
    try:
        profile = get_my_profile(settings, UUID(user.user_id))
        if profile is None:
            raise HTTPException(status_code=404, detail="Профиль ещё не создан.")
        return {"profile": profile}
    except ProfileUnavailable:
        _unavailable()


@router.patch("/me")
def patch_my_profile(payload: ProfileUpdate, user: StudioUser = Depends(get_current_user)):
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not values:
        raise HTTPException(status_code=422, detail="Укажите хотя бы одно поле профиля.")
    try:
        profile = update_my_profile(settings, UUID(user.user_id), values)
        if profile is None:
            raise HTTPException(status_code=404, detail="Профиль ещё не создан.")
        return {"profile": profile}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProfileUnavailable:
        _unavailable()


@router.get("/search")
def search_profiles(q: str = Query(min_length=2, max_length=24, pattern=r"^[a-zA-Z0-9_]+$"),
                    user: StudioUser = Depends(get_current_user)):
    try:
        return {"profiles": search_public_profiles(settings, UUID(user.user_id), q)}
    except ProfileUnavailable:
        _unavailable()


@router.get("/{username}")
def public_profile(username: str, user: StudioUser = Depends(get_current_user)):
    if len(username) < 3 or len(username) > 24:
        raise HTTPException(status_code=404, detail="Профиль не найден.")
    try:
        profile = get_public_profile(settings, username)
        if profile is None:
            raise HTTPException(status_code=404, detail="Профиль не найден.")
        return {"profile": profile}
    except ProfileUnavailable:
        _unavailable()
