"""SprintService — Ticketing v2 sprint lifecycle.

Sprints are project-scoped time-boxes. Lifecycle: planned -> active -> closed.
At most one active sprint per project (enforced by partial UNIQUE in WP2
migration, also defended here for friendlier 4xx). Closing a sprint moves
incomplete tickets back to backlog (ticket.sprint_id = NULL).

See ``docs/specs/ticketing-v2.md`` §2.3.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SprintState, TicketStatus
from app.exceptions import ValidationError
from app.models.project import Sprint
from app.models.ticket import Ticket
from app.services.projects import project_service


class SprintNotFoundError(ValidationError):
    def __init__(self, ident):
        super().__init__([{"name": "sprint", "reason": f"not found: {ident!r}"}])


class SprintStateError(ValidationError):
    def __init__(self, current: str, target: str):
        super().__init__(
            [{"name": "state", "reason": f"cannot move sprint from {current} to {target}"}]
        )


class SprintService:
    async def get(self, session: AsyncSession, sprint_id: UUID) -> Sprint | None:
        res = await session.execute(select(Sprint).where(Sprint.id == sprint_id))
        return res.scalar_one_or_none()

    async def get_or_raise(
        self, session: AsyncSession, sprint_id: UUID
    ) -> Sprint:
        s = await self.get(session, sprint_id)
        if s is None:
            raise SprintNotFoundError(sprint_id)
        return s

    async def list_all(
        self,
        session: AsyncSession,
        *,
        project_id: UUID | str | None = None,
        state: SprintState | str | None = None,
    ) -> list[Sprint]:
        stmt = select(Sprint)
        if project_id is not None:
            proj = await project_service.get_or_raise(session, project_id)
            stmt = stmt.where(Sprint.project_id == proj.id)
        if state is not None:
            st = state if isinstance(state, SprintState) else SprintState(state)
            stmt = stmt.where(Sprint.state == st)
        stmt = stmt.order_by(Sprint.created_at.asc())
        return list((await session.execute(stmt)).scalars().all())

    async def create(
        self,
        session: AsyncSession,
        *,
        project_id: UUID | str,
        name: str,
        goal: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Sprint:
        if not name or not name.strip():
            raise ValidationError([{"name": "name", "reason": "required"}])
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValidationError(
                [{"name": "end_date", "reason": "must be >= start_date"}]
            )
        proj = await project_service.get_or_raise(session, project_id)
        s = Sprint(
            project_id=proj.id,
            name=name,
            goal=goal,
            state=SprintState.planned,
            start_date=start_date,
            end_date=end_date,
        )
        session.add(s)
        await session.flush([s])
        await session.refresh(s)
        return s

    async def update(
        self,
        session: AsyncSession,
        sprint_id: UUID,
        *,
        patch: dict[str, Any],
    ) -> Sprint:
        mutable = {"name", "goal", "start_date", "end_date"}
        unknown = set(patch) - mutable
        if unknown:
            raise ValidationError(
                [{"name": k, "reason": "not updatable via update()"} for k in unknown]
            )
        s = await self.get_or_raise(session, sprint_id)
        for k, v in patch.items():
            setattr(s, k, v)
        await session.flush([s])
        return s

    async def start(self, session: AsyncSession, sprint_id: UUID) -> Sprint:
        s = await self.get_or_raise(session, sprint_id)
        if s.state != SprintState.planned:
            raise SprintStateError(s.state.value, "active")
        # Defend-in-depth check for the partial-UNIQUE.
        active_res = await session.execute(
            select(Sprint.id).where(
                Sprint.project_id == s.project_id,
                Sprint.state == SprintState.active,
            )
        )
        if active_res.scalar_one_or_none() is not None:
            raise ValidationError(
                [
                    {
                        "name": "state",
                        "reason": "another sprint is already active in this project",
                    }
                ]
            )
        s.state = SprintState.active
        try:
            await session.flush([s])
        except IntegrityError as exc:  # pragma: no cover — defensive
            raise ValidationError(
                [{"name": "state", "reason": "active sprint conflict"}]
            ) from exc
        return s

    async def close(self, session: AsyncSession, sprint_id: UUID) -> Sprint:
        s = await self.get_or_raise(session, sprint_id)
        if s.state != SprintState.active:
            raise SprintStateError(s.state.value, "closed")
        # Move incomplete tickets in this sprint back to the backlog.
        terminal = (TicketStatus.done, TicketStatus.cancelled)
        await session.execute(
            update(Ticket)
            .where(
                Ticket.sprint_id == s.id,
                Ticket.status.notin_(terminal),
            )
            .values(sprint_id=None)
        )
        s.state = SprintState.closed
        await session.flush([s])
        return s

    async def delete(self, session: AsyncSession, sprint_id: UUID) -> None:
        s = await self.get_or_raise(session, sprint_id)
        if s.state != SprintState.planned:
            raise SprintStateError(s.state.value, "deleted")
        await session.delete(s)
        await session.flush()

    async def add_ticket(
        self, session: AsyncSession, sprint_id: UUID, ticket_id: UUID
    ) -> None:
        s = await self.get_or_raise(session, sprint_id)
        await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id, Ticket.project_id == s.project_id)
            .values(sprint_id=s.id)
        )

    async def remove_ticket(
        self, session: AsyncSession, sprint_id: UUID, ticket_id: UUID
    ) -> None:
        await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id, Ticket.sprint_id == sprint_id)
            .values(sprint_id=None)
        )


sprint_service = SprintService()
