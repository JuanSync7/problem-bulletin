"""Agent activity endpoint (G2).

Frontend ``AgentActivityFeed`` calls ``GET /api/agents/activity`` for a
projection of the audit_log filtered to agent-actors. Read-only,
paginated by ``limit``/``offset``. Joins to ``tickets`` for ``ticket_key``
when the audited entity is a ticket (or a ticket comment/link with a
discoverable parent ticket).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit_log_event import AuditLogEvent
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink

router = APIRouter(prefix="/v1/agents", tags=["agents"])
# Compat alias used by the frontend (no /v1 prefix). Both are mounted from main.py.
compat_router = APIRouter(prefix="/agents", tags=["agents"])


async def _resolve_ticket_key(
    db: AsyncSession, entity_type: str, entity_id
) -> Optional[str]:
    if entity_type == "ticket":
        row = await db.execute(select(Ticket.key).where(Ticket.id == entity_id))
        return row.scalar_one_or_none()
    if entity_type == "ticket_comment":
        row = await db.execute(
            select(Ticket.key)
            .join(TicketComment, TicketComment.ticket_id == Ticket.id)
            .where(TicketComment.id == entity_id)
        )
        return row.scalar_one_or_none()
    if entity_type == "ticket_link":
        row = await db.execute(
            select(Ticket.key)
            .join(TicketLink, TicketLink.source_id == Ticket.id)
            .where(TicketLink.id == entity_id)
        )
        return row.scalar_one_or_none()
    return None


async def _list_activity(
    db: AsyncSession,
    *,
    actor_type: Optional[str],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    stmt = select(AuditLogEvent)
    if actor_type:
        stmt = stmt.where(AuditLogEvent.actor_type == actor_type)
    stmt = stmt.order_by(AuditLogEvent.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    items: list[dict[str, Any]] = []
    for r in rows:
        ticket_key = await _resolve_ticket_key(db, r.entity_type, r.entity_id)
        items.append(
            {
                "id": str(r.id),
                "occurred_at": r.created_at.isoformat() if r.created_at else None,
                "actor_id": str(r.actor_id),
                "actor_type": r.actor_type,
                "actor_name": None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": str(r.entity_id),
                "ticket_key": ticket_key,
                "correlation_id": r.correlation_id or None,
                "details": r.diff or None,
            }
        )
    return items


@router.get("/activity")
async def list_activity(
    db: AsyncSession = Depends(get_db),
    actor_type: Optional[str] = Query(default="agent"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project_id: Optional[str] = Query(default=None),  # accepted but unused (no project model yet)
) -> dict[str, Any]:
    items = await _list_activity(db, actor_type=actor_type, limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@compat_router.get("/activity")
async def list_activity_compat(
    db: AsyncSession = Depends(get_db),
    actor_type: Optional[str] = Query(default="agent"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    return await list_activity(
        db=db, actor_type=actor_type, limit=limit, offset=offset, project_id=project_id
    )
