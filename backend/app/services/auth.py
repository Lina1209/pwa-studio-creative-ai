from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

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
    return PyJWKClient(
        f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        timeout=5,
        cache_jwk_set=True,
        lifespan=300,
    )


def _configured_owner_ids(raw_value: str | None) -> set[str]:
    """Parse the server-only UUID allowlist; malformed entries grant no access."""
    owner_ids: set[str] = set()
    for item in (raw_value or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            owner_ids.add(str(UUID(candidate)))
        except (ValueError, TypeError, AttributeError):
            continue
    return owner_ids


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> StudioUser:
    settings = get_settings()
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="Authentication is not configured yet.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A valid sign-in token is required.")

    token = credentials.credentials
    # Bound untrusted bearer input before parsing or making a JWKS network request.
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="The sign-in session is invalid or expired.")
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

    # Supabase user access tokens carry role=authenticated. Reject service-role
    # and other project JWTs even if their signature and audience are valid.
    if claims.get("role") != "authenticated":
        raise HTTPException(status_code=401, detail="The sign-in token is not a user session.")

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="The sign-in token has no user identity.")
    try:
        user_id = str(UUID(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=401, detail="The sign-in token has an invalid user identity.") from exc

    email = claims.get("email")
    email = email.lower() if isinstance(email, str) else None
    # Authorization is bound to the immutable Supabase Auth subject UUID.
    # Email is display/contact data only and cannot grant or retain admin access.
    role = "admin" if user_id in _configured_owner_ids(settings.owner_user_ids) else "creator"
    return StudioUser(user_id=user_id, email=email, role=role)


def require_admin(user: StudioUser = Depends(get_current_user)) -> StudioUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user
