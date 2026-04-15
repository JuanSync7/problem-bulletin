"""JWT creation, decoding, and cookie management.  REQ-108."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from starlette.responses import Response

from app.config import get_settings
from app.schemas import TokenPayload

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8


def create_access_token(user) -> str:
    """Create a signed JWT for the given user.

    The token carries ``sub`` (user id), ``role``, and ``exp`` claims.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "role": user.role if isinstance(user.role, str) else user.role.value,
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT, returning a ``TokenPayload``.

    Raises:
        jose.JWTError: On any validation failure (expiry, signature, structure).
    """
    settings = get_settings()
    data = jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=[ALGORITHM])
    return TokenPayload(sub=data["sub"], role=data["role"], exp=data["exp"])


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the ``access_token`` HttpOnly cookie on the response."""
    settings = get_settings()
    secure = settings.ENVIRONMENT != "development"
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the ``access_token`` cookie."""
    response.delete_cookie(key="access_token", path="/")
