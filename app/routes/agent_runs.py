"""V4b: AgentRun REST routes.

Two endpoints:

* ``POST /api/v1/agent-runs/process-next`` — admin-only.  Calls
  :meth:`AgentRunQueue.process_one` on the in-process queue.  Returns
  ``{"run_id": <uuid | null>, "status": "done" | "error" | "empty"}``.
* ``GET /api/v1/agent-runs?ticket_id=<uuid>`` — list of agent runs for
  a ticket (ordered newest-first), used by the frontend banner.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.bearer_auth import get_actor, get_admin_actor
from app.models.agent_account import AgentAccount
from app.models.agent_run import AgentRun
from app.services.agent_run_queue import get_default_queue
from app.services.context import Actor

router = APIRouter(prefix="/v1/agent-runs", tags=["agent-runs"])


class ProcessNextResponse(BaseModel):
    """Outcome of a single ``process-next`` invocation."""

    run_id: UUID | None
    status: str  # "done" | "error" | "empty"


class AgentRunRead(BaseModel):
    id: UUID
    agent_id: UUID
    agent_handle: str | None
    ticket_id: UUID
    comment_id: UUID | None
    status: str
    response_body: str | None
    error: str | None
    enqueued_at: str | None
    started_at: str | None
    finished_at: str | None


class AgentRunList(BaseModel):
    items: list[AgentRunRead]
    total: int


@router.post(
    "/process-next",
    status_code=status.HTTP_200_OK,
    response_model=ProcessNextResponse,
)
async def process_next(
    actor: Actor = Depends(get_admin_actor),
    db: AsyncSession = Depends(get_db),
) -> ProcessNextResponse:
    """Pop and process the oldest pending agent_run, if any."""
    _ = actor  # admin gate only — actor identity isn't recorded on the run
    queue = get_default_queue(db)
    run_id = await queue.process_one(db)
    if run_id is None:
        return ProcessNextResponse(run_id=None, status="empty")

    row = (
        await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    ).scalar_one_or_none()
    if row is None:
        # Defensive — the queue just touched it, so this should not happen.
        return ProcessNextResponse(run_id=run_id, status="empty")
    return ProcessNextResponse(run_id=row.id, status=row.status)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=AgentRunList,
)
async def list_agent_runs(
    ticket_id: Optional[UUID] = Query(default=None),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> AgentRunList:
    """List agent_run rows, optionally filtered by ticket_id (newest first)."""
    _ = actor  # any authenticated caller may read
    stmt = (
        select(AgentRun, AgentAccount.handle)
        .join(AgentAccount, AgentAccount.id == AgentRun.agent_id, isouter=True)
        .order_by(AgentRun.enqueued_at.desc(), AgentRun.id.desc())
    )
    if ticket_id is not None:
        stmt = stmt.where(AgentRun.ticket_id == ticket_id)

    rows = (await db.execute(stmt)).all()
    items: list[AgentRunRead] = []
    for run, handle in rows:
        items.append(
            AgentRunRead(
                id=run.id,
                agent_id=run.agent_id,
                agent_handle=handle,
                ticket_id=run.ticket_id,
                comment_id=run.comment_id,
                status=run.status,
                response_body=run.response_body,
                error=run.error,
                enqueued_at=(
                    run.enqueued_at.isoformat() if run.enqueued_at else None
                ),
                started_at=(
                    run.started_at.isoformat() if run.started_at else None
                ),
                finished_at=(
                    run.finished_at.isoformat() if run.finished_at else None
                ),
            )
        )
    return AgentRunList(items=items, total=len(items))
