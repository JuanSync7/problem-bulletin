"""Admin service layer — user management, moderation, config.  REQ-450 family."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import UserRole
from app.exceptions import ValidationError
from app.logging import log_event
from app.models.app_config import ALLOWED_CONFIG_KEYS, AppConfig
from app.models.audit_log import AuditLog
from app.models.flag import Flag
from app.models.problem import Problem
from app.models.user import User

# Canonical role allow-list, sourced from ``app.enums.UserRole`` so the
# service layer cannot drift from the schema/route Literal.  v2.11-WP03.
_ALLOWED_ROLES: frozenset[str] = frozenset(r.value for r in UserRole)


# ---------------------------------------------------------------------------
# User management  (REQ-466)
# ---------------------------------------------------------------------------

async def search_users(db: AsyncSession, query: str | None) -> list[User]:
    """Case-insensitive search on display_name and email."""
    stmt = select(User).order_by(User.created_at.desc())
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            User.display_name.ilike(pattern) | User.email.ilike(pattern)
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_user_role(
    db: AsyncSession,
    user_id: UUID,
    new_role: str,
    *,
    actor_id: UUID | None = None,
) -> User:
    """Update a user's role.

    v2.11-WP03: ``new_role`` is validated against ``app.enums.UserRole`` at
    the service boundary so non-route callers (background jobs, agent
    actions, other services) cannot write garbage values.  Raises the
    domain ``ValidationError`` on unknown roles.

    ``actor_id`` is the caller's principal id (audit-actor convention).
    When omitted we fall back to the target user id for backward
    compatibility with legacy call sites; routes MUST thread the admin's
    own id.
    """
    if new_role not in _ALLOWED_ROLES:
        raise ValidationError([
            {"name": "role", "reason": f"must be one of {sorted(_ALLOWED_ROLES)}"}
        ])
    user = await _get_user_or_404(db, user_id)
    user.role = new_role
    await db.flush()
    actor = str(actor_id) if actor_id is not None else str(user_id)
    log_event("user.role_changed", "user", str(user_id), actor, "update_role", {"new_role": new_role})
    return user


async def update_user_status(
    db: AsyncSession,
    user_id: UUID,
    is_active: bool,
    *,
    actor_id: UUID | None = None,
) -> User:
    """Toggle a user's active status.

    v2.11-WP03: accepts ``actor_id`` (caller principal) for audit-log
    consistency; falls back to target ``user_id`` when omitted.
    """
    user = await _get_user_or_404(db, user_id)
    user.is_active = is_active
    await db.flush()
    actor = str(actor_id) if actor_id is not None else str(user_id)
    log_event("user.status_changed", "user", str(user_id), actor, "update_status", {"is_active": is_active})
    return user


# ---------------------------------------------------------------------------
# Moderation  (REQ-468, REQ-470, REQ-472)
# ---------------------------------------------------------------------------

async def get_flagged_content(db: AsyncSession, status_filter: str | None) -> list[Flag]:
    """Return flags, optionally filtered by status, ordered by newest first."""
    stmt = select(Flag).order_by(Flag.created_at.desc())
    if status_filter:
        stmt = stmt.where(Flag.status == status_filter)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def resolve_flag(db: AsyncSession, flag_id: UUID, admin_id: UUID, note: str) -> Flag:
    """Mark a flag as resolved with a resolution note."""
    stmt = select(Flag).where(Flag.id == flag_id)
    result = await db.execute(stmt)
    flag = result.scalar_one_or_none()
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    flag.status = "resolved"
    flag.resolution_note = note
    flag.resolved_by = admin_id
    await db.flush()

    log_event("flag.resolved", "flag", str(flag_id), str(admin_id), "resolve", {"note": note})
    return flag


async def de_anonymize(db: AsyncSession, problem_id: UUID, admin_id: UUID) -> dict:
    """Reveal the author of an anonymous problem; write an audit log entry.  REQ-474."""
    stmt = select(Problem).where(Problem.id == problem_id)
    result = await db.execute(stmt)
    problem = result.scalar_one_or_none()
    if problem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Problem not found")
    if not problem.is_anonymous:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Problem is not anonymous")

    # Write audit log *before* revealing — ensures traceability even on crash.
    audit = AuditLog(
        admin_id=admin_id,
        action="de_anonymize",
        target_type="problem",
        target_id=problem_id,
        metadata_={"author_id": str(problem.author_id)},
    )
    db.add(audit)
    await db.flush()

    log_event(
        "admin.de_anonymize", "problem", str(problem_id), str(admin_id), "de_anonymize",
        {"author_id": str(problem.author_id)},
    )
    return {"author_id": problem.author_id}


# ---------------------------------------------------------------------------
# Runtime config  (REQ-476)
# ---------------------------------------------------------------------------

async def get_config(db: AsyncSession) -> list[AppConfig]:
    """Return all runtime config key-value pairs."""
    result = await db.execute(select(AppConfig).order_by(AppConfig.key))
    return list(result.scalars().all())


async def update_config(
    db: AsyncSession,
    key: str,
    value: str,
    *,
    actor_id: UUID | None = None,
) -> AppConfig:
    """Upsert a config value; key must be in the allowlist.

    v2.11-WP03: accepts ``actor_id`` (caller principal) so the audit log
    records *who* performed the change.  Previously the audit slot held
    the literal string ``"admin"``, which broke the audit-actor
    convention applied elsewhere in this service.  When ``actor_id`` is
    not supplied we fall back to ``"system"`` (clearly non-user) rather
    than the misleading ``"admin"`` sentinel.
    """
    if key not in ALLOWED_CONFIG_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key '{key}' is not an allowed config key. Allowed: {sorted(ALLOWED_CONFIG_KEYS)}",
        )

    stmt = select(AppConfig).where(AppConfig.key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        config = AppConfig(key=key, value=value)
        db.add(config)
    else:
        config.value = value

    await db.flush()
    actor = str(actor_id) if actor_id is not None else "system"
    log_event("config.updated", "app_config", key, actor, "update_config", {"value": value})
    return config


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_user_or_404(db: AsyncSession, user_id: UUID) -> User:
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
