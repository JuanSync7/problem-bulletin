"""Admin service layer — user management, moderation, config.  REQ-450 family."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import log_event
from app.models.app_config import ALLOWED_CONFIG_KEYS, AppConfig
from app.models.audit_log import AuditLog
from app.models.flag import Flag
from app.models.problem import Problem
from app.models.user import User


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


async def update_user_role(db: AsyncSession, user_id: UUID, new_role: str) -> User:
    """Update a user's role."""
    user = await _get_user_or_404(db, user_id)
    user.role = new_role
    await db.flush()
    log_event("user.role_changed", "user", str(user_id), str(user_id), "update_role", {"new_role": new_role})
    return user


async def update_user_status(db: AsyncSession, user_id: UUID, is_active: bool) -> User:
    """Toggle a user's active status."""
    user = await _get_user_or_404(db, user_id)
    user.is_active = is_active
    await db.flush()
    log_event("user.status_changed", "user", str(user_id), str(user_id), "update_status", {"is_active": is_active})
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


async def update_config(db: AsyncSession, key: str, value: str) -> AppConfig:
    """Upsert a config value; key must be in the allowlist."""
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
    log_event("config.updated", "app_config", key, "admin", "update_config", {"value": value})
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
