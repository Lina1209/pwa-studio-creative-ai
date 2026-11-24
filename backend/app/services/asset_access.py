"""Owner-scope helpers for future Media Library database operations.

All owner IDs must come from the verified StudioUser returned by Supabase Auth.
Never pass an owner ID from a request body, query string, or client-side project data.
These helpers are deliberately not wired to routes until live schema/RLS is reconciled.
"""
from uuid import UUID

from fastapi import HTTPException


def canonical_owner_id(authenticated_user_id: str) -> str:
    """Validate and canonicalize the ID from the verified auth principal."""
    try:
        return str(UUID(authenticated_user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="The authenticated account identity is invalid.",
        ) from exc


def owner_filter(authenticated_user_id: str) -> dict[str, str]:
    """Return a PostgREST owner equality filter from the verified principal."""
    return {"owner_id": f"eq.{canonical_owner_id(authenticated_user_id)}"}


def owner_scoped_params(authenticated_user_id: str, *, extra: dict | None = None) -> dict:
    """Build query params without allowing caller-supplied owner scope overrides."""
    params = dict(extra or {})
    if "owner_id" in params:
        raise ValueError("owner_id must come from the authenticated principal")
    params.update(owner_filter(authenticated_user_id))
    return params
