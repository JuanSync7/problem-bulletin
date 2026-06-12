"""ComponentService — Ticketing v2 per-project component buckets.

Components categorise tickets within a project (e.g. "Frontend", "API").
Unique on ``(project_id, name)`` via DB constraint. See spec §2.4.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ValidationError
from app.models.project import Component
from app.services.projects import project_service

if TYPE_CHECKING:
    from app.models.user import User


class ComponentNotFoundError(ValidationError):
    def __init__(self, ident):
        super().__init__([{"name": "component", "reason": f"not found: {ident!r}"}])


class ComponentNameConflictError(ValidationError):
    def __init__(self, name: str):
        super().__init__(
            [{"name": "name", "reason": f"name {name!r} already in use in this project"}]
        )


class ComponentService:
    async def get(
        self, session: AsyncSession, component_id: UUID
    ) -> Component | None:
        res = await session.execute(
            select(Component).where(Component.id == component_id)
        )
        return res.scalar_one_or_none()

    async def get_or_raise(
        self, session: AsyncSession, component_id: UUID
    ) -> Component:
        c = await self.get(session, component_id)
        if c is None:
            raise ComponentNotFoundError(component_id)
        return c

    async def list_by_project(
        self, session: AsyncSession, project_id: UUID | str
    ) -> list[Component]:
        proj = await project_service.get_or_raise(session, project_id)
        res = await session.execute(
            select(Component)
            .where(Component.project_id == proj.id)
            .order_by(Component.name.asc())
        )
        return list(res.scalars().all())

    async def create(
        self,
        session: AsyncSession,
        *,
        project_id: UUID | str,
        name: str,
        description: str | None = None,
        lead_id: UUID | None = None,
        lead_type: str | None = None,
    ) -> Component:
        if not name or not name.strip():
            raise ValidationError([{"name": "name", "reason": "required"}])
        if (lead_id is None) != (lead_type is None):
            raise ValidationError(
                [{"name": "lead_type", "reason": "must be paired with lead_id"}]
            )
        if lead_type is not None and lead_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "lead_type", "reason": "must be 'user' or 'agent'"}]
            )
        proj = await project_service.get_or_raise(session, project_id)
        c = Component(
            project_id=proj.id,
            name=name,
            description=description,
            lead_id=lead_id,
            lead_type=lead_type,
        )
        session.add(c)
        try:
            await session.flush([c])
        except IntegrityError as exc:
            raise ComponentNameConflictError(name) from exc
        return c

    async def update(
        self,
        session: AsyncSession,
        component_id: UUID,
        *,
        patch: dict[str, Any],
        acting_user: "User",
    ) -> Component:
        mutable = {"name", "description", "lead_id", "lead_type"}
        unknown = set(patch) - mutable
        if unknown:
            raise ValidationError(
                [{"name": k, "reason": "not updatable via update()"} for k in unknown]
            )
        c = await self.get_or_raise(session, component_id)
        # Permission check: component is project-scoped; use the project's lead rule.
        await project_service._check_project_edit_permission(session, c.project_id, acting_user)
        new_lead_id = patch.get("lead_id", c.lead_id)
        new_lead_type = patch.get("lead_type", c.lead_type)
        if (new_lead_id is None) != (new_lead_type is None):
            raise ValidationError(
                [{"name": "lead_type", "reason": "must be paired with lead_id"}]
            )
        for k, v in patch.items():
            setattr(c, k, v)
        try:
            await session.flush([c])
        except IntegrityError as exc:
            raise ComponentNameConflictError(patch.get("name", c.name)) from exc
        await session.refresh(c)
        return c

    async def delete(
        self,
        session: AsyncSession,
        component_id: UUID,
        *,
        acting_user: "User",
    ) -> None:
        c = await self.get_or_raise(session, component_id)
        await project_service._check_project_edit_permission(session, c.project_id, acting_user)
        await session.delete(c)
        await session.flush()


component_service = ComponentService()
