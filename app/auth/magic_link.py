"""Passwordless magic-link email authentication.  REQ-104, REQ-106."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import aiosmtplib
from email.message import EmailMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import UserRole
from app.exceptions import MagicLinkExpiredError
from app.models.magic_link import MagicLink
from app.models.user import User

MAGIC_LINK_EXPIRY_MINUTES = 15


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def send_magic_link(db: AsyncSession, email: str, settings: Settings) -> None:
    """Generate a magic-link token, persist it, and email it to the user.  REQ-104."""

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES)

    # Look up or pre-create user
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    user_id = user.id if user else None

    record = MagicLink(
        token_hash=token_hash,
        user_id=user_id,
        email=email,
        expires_at=expires_at,
        consumed=False,
    )
    db.add(record)
    await db.flush()

    # Build verification URL
    base = str(settings.BASE_URL).rstrip("/")
    verify_url = f"{base}/auth/magic/verify?token={raw_token}"

    # Send email
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = email
    msg["Subject"] = f"{settings.APP_NAME} — Sign-in link"
    msg.set_content(
        f"Click this link to sign in to {settings.APP_NAME}:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in {MAGIC_LINK_EXPIRY_MINUTES} minutes."
    )

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        start_tls=True,
    )


async def verify_magic_link(db: AsyncSession, raw_token: str) -> User:
    """Verify a magic-link token and return the authenticated user.  REQ-106.

    Raises:
        MagicLinkExpiredError: Token is expired, consumed, or not found.
    """
    token_hash = _hash_token(raw_token)

    stmt = select(MagicLink).where(MagicLink.token_hash == token_hash)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        raise MagicLinkExpiredError()

    now = datetime.now(timezone.utc)
    if record.consumed or record.expires_at.replace(tzinfo=timezone.utc) < now:
        raise MagicLinkExpiredError()

    # Mark consumed
    record.consumed = True
    db.add(record)

    # Provision user if not exists
    if record.user_id is not None:
        stmt_user = select(User).where(User.id == record.user_id)
        result_user = await db.execute(stmt_user)
        user = result_user.scalar_one_or_none()
        if user is not None:
            return user

    # Lookup or create by email
    stmt_user = select(User).where(User.email == record.email)
    result_user = await db.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    if user is None:
        user = User(
            email=record.email,
            display_name=record.email.split("@")[0],
            role=UserRole.user,
            is_active=True,
        )
        db.add(user)
        await db.flush()

    # Back-fill user_id on the magic link record
    record.user_id = user.id
    await db.flush()

    return user
