"""Admin-only audit-log read endpoint — WP33.

GET /api/v1/audit-log
  Returns a paginated :class:`AuditLogPage` of ``activity_audit_log`` rows.
  Admin-only: 403 if the current user is not an admin.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser
from app.database import get_db
from app.schemas.audit_log import AuditLogPage
from app.services import audit_log as audit_log_svc
from app.services._admin import require_admin

router = APIRouter(prefix="/v1/audit-log", tags=["audit-log"])


@router.get("", response_model=AuditLogPage)
async def list_audit_log(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    event: str | None = Query(None),
    actor_user_id: UUID | None = Query(None),
    target_type: str | None = Query(None),
) -> AuditLogPage:
    """Return a paginated list of audit-log entries.

    Requires admin role. Filters combine with AND; omitted filters are
    not applied. ``total`` is set only on the first page (cursor absent).
    """
    require_admin(current_user)
    return await audit_log_svc.list_entries(
        db,
        cursor=cursor,
        limit=limit,
        event=event,
        actor_user_id=actor_user_id,
        target_type=target_type,
    )
