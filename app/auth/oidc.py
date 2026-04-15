"""Azure AD OIDC integration.  REQ-100, REQ-102, REQ-110, REQ-112, REQ-116."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from authlib.integrations.starlette_client import OAuth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import UserRole
from app.exceptions import TenantMismatchError
from app.models.user import User

if TYPE_CHECKING:
    from starlette.requests import Request

_oauth: OAuth | None = None


def _get_oauth() -> OAuth:
    """Lazily initialise the OAuth registry so settings are read at runtime."""
    global _oauth
    if _oauth is not None:
        return _oauth

    settings = get_settings()
    _oauth = OAuth()
    _oauth.register(
        name="azure",
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET.get_secret_value(),
        server_metadata_url=(
            f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}/v2.0"
            "/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )
    return _oauth


async def initiate_login(request: Request) -> str:
    """Store a ``state`` nonce in the session and return the Azure AD redirect URL.

    Returns the authorisation URL to which the caller should redirect.
    """
    settings = get_settings()
    oauth = _get_oauth()
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    redirect_uri = str(settings.BASE_URL).rstrip("/") + "/auth/callback"
    redirect = await oauth.azure.authorize_redirect(request, redirect_uri, state=state)
    return redirect


async def handle_callback(request: Request, db: AsyncSession) -> User:
    """Exchange the authorisation code for tokens, validate tenant, and provision user.

    Raises:
        TenantMismatchError: If the ``tid`` claim does not match the configured tenant.
    """
    settings = get_settings()
    oauth = _get_oauth()

    token = await oauth.azure.authorize_access_token(request)
    id_token_claims = token.get("userinfo") or token.get("id_token", {})

    # Tenant enforcement — REQ-102
    tid = id_token_claims.get("tid")
    if tid != settings.AZURE_TENANT_ID:
        raise TenantMismatchError()

    oid = id_token_claims.get("oid") or id_token_claims.get("sub")
    email = id_token_claims.get("email") or id_token_claims.get("preferred_username", "")
    display_name = id_token_claims.get("name") or email.split("@")[0]

    user = await _provision_user(db, oid=oid, email=email, display_name=display_name)
    return user


async def _provision_user(
    db: AsyncSession,
    *,
    oid: str,
    email: str,
    display_name: str,
) -> User:
    """Look up or create a user based on Azure OID / email.  REQ-110, REQ-112, REQ-116.

    Lookup order:
    1. ``azure_oid`` match
    2. ``email`` match (link existing account)
    3. Create new user with ``role=user``
    """
    # 1. Lookup by azure_oid
    stmt = select(User).where(User.azure_oid == oid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    # 2. Lookup by email (link OID to existing account)
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        user.azure_oid = oid
        if display_name:
            user.display_name = display_name
        db.add(user)
        await db.flush()
        return user

    # 3. Create new user
    user = User(
        email=email,
        display_name=display_name,
        role=UserRole.user,
        azure_oid=oid,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user
