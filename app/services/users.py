"""UserService — user-profile mutations (v2.3-WP24 / v2.4-WP29 / v2.5-WP35).

Thin service that owns user-row writes that are too small to warrant their
own service module. Today it contains only ``update_handle``.

v2.4-WP29 adds a 24-hour cooldown enforced via the ``handle_changed_at``
column.  Idempotent no-ops (new_handle == current_handle) bypass both the
cooldown check and the timestamp bump.

v2.5-WP35 adds a lightweight profanity filter (``is_profane``) applied
before the rate-limit check. Admin callers may bypass both the profanity
check and the cooldown via explicit kwargs.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.users import RESERVED_HANDLES, _HANDLE_RE
from app.services import audit_log as _audit_log
from app.services._handle_filter import is_profane
from app.services.exceptions import (
    HandleChangeTooSoonError,
    HandleTakenError,
    ProfaneHandleError,
)

# ---------------------------------------------------------------------------
# Rate-limit constant — do NOT move to config (WP29 constraint).
# ---------------------------------------------------------------------------
HANDLE_CHANGE_COOLDOWN_SECONDS: int = 24 * 3600


async def update_handle(
    session: AsyncSession,
    user_id: UUID,
    new_handle: str,
    *,
    bypass_profanity: bool = False,
    bypass_cooldown: bool = False,
    acting_user_id: UUID | None = None,
) -> User:
    """Change the handle for *user_id* to *new_handle*.

    Server-side normalisation and defence-in-depth validation happen here
    even though ``HandleUpdate`` already validates the input — the service
    layer must not trust callers blindly.

    Parameters
    ----------
    session:
        Caller-owned async session.
    user_id:
        UUID of the user whose handle to change.
    new_handle:
        The desired handle (will be lowercased/stripped).
    bypass_profanity:
        When True (admin only), skip the profanity filter check.
    bypass_cooldown:
        When True (admin only), skip the 24-hour cooldown check.
    acting_user_id:
        UUID of the admin performing the override; used for audit logging.
        When None, ``user_id`` is used as the actor (self-service path).

    Raises:
        ValueError: if *new_handle* fails format / reserved-word rules.
        ProfaneHandleError: if *new_handle* is profane (unless bypassed).
        HandleTakenError: if *new_handle* is already owned by another user.
        HandleChangeTooSoonError: if the user changed their handle within the
            last ``HANDLE_CHANGE_COOLDOWN_SECONDS`` seconds (24 h, unless bypassed).

    Returns:
        The refreshed :class:`~app.models.user.User` instance.
    """
    # 1. Normalise.
    handle = new_handle.lower().strip()

    # 2. Defence-in-depth validation (mirrors HandleUpdate validators).
    if len(handle) < 3 or len(handle) > 32:
        raise ValueError("handle must be 3–32 characters")
    if not _HANDLE_RE.match(handle):
        raise ValueError(
            "handle may only contain lowercase letters, digits, and underscores"
        )
    if handle[0] == "_":
        raise ValueError("handle must not start with an underscore")
    if handle[0].isdigit():
        raise ValueError("handle must not start with a digit")
    if handle in RESERVED_HANDLES:
        raise ValueError(f"handle {handle!r} is reserved")

    # 3. Profanity check — before rate-limit, after format/reserved checks.
    if not bypass_profanity and is_profane(handle):
        raise ProfaneHandleError()

    # 4. Load the current user row so we can check handle + cooldown together.
    cur_res = await session.execute(
        select(User.handle, User.handle_changed_at).where(User.id == user_id)
    )
    cur_row = cur_res.one_or_none()
    if cur_row is None:
        raise ValueError(f"user {user_id!r} not found")

    current_handle, handle_changed_at = cur_row

    # 5. Idempotent no-op: skip cooldown check AND timestamp bump.
    if handle == (current_handle or "").lower():
        res = await session.execute(select(User).where(User.id == user_id))
        return res.scalar_one()

    # 6. Rate-limit check (only for actual changes; skipped if bypassed).
    if not bypass_cooldown and handle_changed_at is not None:
        # Normalise to UTC-aware for comparison.
        if handle_changed_at.tzinfo is None:
            handle_changed_at = handle_changed_at.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - handle_changed_at).total_seconds()
        if elapsed < HANDLE_CHANGE_COOLDOWN_SECONDS:
            next_allowed_at = handle_changed_at + timedelta(
                seconds=HANDLE_CHANGE_COOLDOWN_SECONDS
            )
            raise HandleChangeTooSoonError(next_allowed_at)

    # 7. Uniqueness check — allow the user to re-set their current handle.
    conflict_res = await session.execute(
        select(User.id).where(User.handle == handle, User.id != user_id)
    )
    if conflict_res.scalar_one_or_none() is not None:
        raise HandleTakenError(handle)

    # 8. Apply the update, bumping handle_changed_at in the same statement.
    await session.execute(
        text(
            "UPDATE users "
            "SET handle = :h, handle_changed_at = NOW() "
            "WHERE id = :id"
        ),
        {"h": handle, "id": user_id},
    )

    # 9. Return the refreshed user.
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one()

    # 10. Best-effort audit trail — failure is swallowed by the service.
    #     Admin overrides use a distinct event so they are easily filtered.
    if acting_user_id is not None:
        # Admin override path.
        await _audit_log.record(
            session,
            event="user.handle_changed_by_admin",
            actor_user_id=acting_user_id,
            target_type="user",
            target_id=user_id,
            metadata={"old_handle": current_handle, "new_handle": handle},
        )
    else:
        # Self-service path.
        await _audit_log.record(
            session,
            event="user.handle_changed",
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            metadata={"old_handle": current_handle, "new_handle": handle},
        )

    return user
