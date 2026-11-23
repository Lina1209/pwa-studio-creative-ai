from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWTError

from app.core.config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class StudioUser:
    user_id: str
    email: str | None
    role: str


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> StudioUser:
    settings = get_settings()
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="Authentication is not configured yet.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A valid sign-in token is required.")

    token = credentials.credentials
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    try:
        signing_key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="The sign-in session is invalid or expired.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not verify the sign-in session.") from exc

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="The sign-in token has no user identity.")

    email = claims.get("email")
    email = email.lower() if isinstance(email, str) else None
    owner_user_id = (settings.owner_user_id or "").strip()
    if owner_user_id:
        # A configured immutable Supabase UUID takes precedence over mutable email.
        role = "admin" if user_id == owner_user_id else "creator"
    else:
        # Backward compatibility only. Set OWNER_USER_ID in production to avoid
        # relying on an email claim for administrator identity.
        owner_email = (settings.owner_email or "").strip().lower()
        role = "admin" if email and owner_email and email == owner_email else "creator"
    return StudioUser(user_id=user_id, email=email, role=role)


def require_admin(user: StudioUser = Depends(get_current_user)) -> StudioUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user
