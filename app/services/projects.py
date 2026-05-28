"""ProjectService — Ticketing v2 project CRUD + per-project sequences.

A project is the top-level container for tickets, sprints, components and
members. See ``docs/specs/ticketing-v2.md`` §2.1.

The service is the only place that knows how to:

* create a Postgres `SEQUENCE seq_<lowercased_key>` alongside the project
  row (in the same transaction);
* drop the sequence on hard-delete;
* allocate the next display id via `nextval('seq_<lowercased_key>')`
  and return ``f"{KEY}-{n}"``.

Per Cross-WP Rule #6 we use the lowercased key as the sequence suffix to
sidestep PG identifier case-folding; the display id still renders the
project key in uppercase via `projects.key`.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ProjectRole, UserRole
from app.exceptions import (
    OptimisticConcurrencyError,
    ValidationError,
)
from app.models.project import Component, Project, ProjectMember
from app.models.ticket import Ticket
from app.services import audit_log as _audit_log
from app.services.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from app.models.user import User


_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
# Project keys are uppercase and limited by the DB CHECK; lowercased + length
# bound is safe in `seq_<key>` identifiers (PG ident max 63).
_VALID_KEY_FOR_SEQUENCE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class ProjectNotFoundError(ValidationError):
    """Raised when a project cannot be resolved by id-or-key."""

    def __init__(self, ident):
        super().__init__([{"name": "project", "reason": f"not found: {ident!r}"}])


class ProjectKeyConflictError(ValidationError):
    def __init__(self, key: str):
        super().__init__([{"name": "key", "reason": f"key {key!r} already in use"}])


class ProjectHasTicketsError(ValidationError):
    def __init__(self, count: int):
        super().__init__(
            [{"name": "id", "reason": f"project has {count} ticket(s); archive instead"}]
        )


def _seq_name(key: str) -> str:
    """Per-project sequence name. Always lowercased; safe as PG identifier."""
    if not _VALID_KEY_FOR_SEQUENCE_RE.match(key):
        raise ValidationError(
            [{"name": "key", "reason": f"invalid project key: {key!r}"}]
        )
    return f"seq_{key.lower()}"


class ProjectService:
    """Project CRUD + sequence lifecycle. Stateless; share freely."""

    # -- key + lookup -------------------------------------------------------

    @staticmethod
    def _validate_key(key: str) -> str:
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise ValidationError(
                [
                    {
                        "name": "key",
                        "reason": "must match ^[A-Z][A-Z0-9]{1,9}$",
                    }
                ]
            )
        return key

    @staticmethod
    def _is_uuid(value: Any) -> bool:
        if isinstance(value, UUID):
            return True
        if not isinstance(value, str):
            return False
        try:
            UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    async def get(
        self, session: AsyncSession, id_or_key: UUID | str
    ) -> Project | None:
        """Return a project by UUID or by KEY. None if not found."""
        if isinstance(id_or_key, UUID) or self._is_uuid(id_or_key):
            pid = id_or_key if isinstance(id_or_key, UUID) else UUID(str(id_or_key))
            res = await session.execute(select(Project).where(Project.id == pid))
            return res.scalar_one_or_none()
        res = await session.execute(
            select(Project).where(Project.key == str(id_or_key))
        )
        return res.scalar_one_or_none()

    async def get_or_raise(
        self, session: AsyncSession, id_or_key: UUID | str
    ) -> Project:
        proj = await self.get(session, id_or_key)
        if proj is None:
            raise ProjectNotFoundError(id_or_key)
        return proj

    async def list_all(
        self, session: AsyncSession, *, include_archived: bool = False
    ) -> list[Project]:
        stmt = select(Project)
        if not include_archived:
            stmt = stmt.where(Project.archived.is_(False))
        stmt = stmt.order_by(Project.key.asc())
        return list((await session.execute(stmt)).scalars().all())

    # -- permission check ---------------------------------------------------

    async def _check_project_edit_permission(
        self,
        session: AsyncSession,
        project_id: UUID | str,
        user: "User",
    ) -> "Project":
        """Raise PermissionDeniedError unless user is admin OR project's user-lead.

        Returns the fetched Project so callers can avoid a second fetch.
        """
        proj = await self.get_or_raise(session, project_id)
        if user.role == UserRole.admin:
            return proj
        if proj.lead_type == "user" and proj.lead_id == user.id:
            return proj
        raise PermissionDeniedError("You do not have permission to edit this project.")

    # -- create / update / archive / delete --------------------------------

    async def create(
        self,
        session: AsyncSession,
        *,
        key: str,
        name: str,
        description: str | None = None,
        lead_id: UUID | None = None,
        lead_type: str | None = None,
        wip_limits: dict | None = None,
        acting_user: "User | None" = None,
    ) -> Project:
        if acting_user is not None and acting_user.role != UserRole.admin:
            raise PermissionDeniedError("Only admins can create projects")
        key = self._validate_key(key)
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

        existing = await session.execute(
            select(Project.id).where(Project.key == key)
        )
        if existing.scalar_one_or_none() is not None:
            raise ProjectKeyConflictError(key)

        proj = Project(
            key=key,
            name=name,
            description=description,
            lead_id=lead_id,
            lead_type=lead_type,
            archived=False,
            wip_limits=dict(wip_limits or {}),
            version=1,
        )
        session.add(proj)
        try:
            await session.flush([proj])
        except IntegrityError as exc:
            raise ProjectKeyConflictError(key) from exc

        # Sequence creation inside the same TX. IF NOT EXISTS is safe if the
        # migration already created seq_def or a prior partial create raced.
        await session.execute(text(f'CREATE SEQUENCE IF NOT EXISTS {_seq_name(key)}'))
        await session.refresh(proj)

        # Best-effort audit trail — failure is swallowed by the service.
        actor_id = acting_user.id if acting_user is not None else None
        await _audit_log.record(
            session,
            event="project.created",
            actor_user_id=actor_id,
            target_type="project",
            target_id=proj.id,
            metadata={"slug": proj.key},
        )

        return proj

    async def update(
        self,
        session: AsyncSession,
        project_id: UUID | str,
        *,
        expected_version: int,
        patch: dict[str, Any],
        acting_user: "User",
    ) -> Project:
        mutable = {"name", "description", "lead_id", "lead_type", "wip_limits", "state_change_coalesce_seconds"}
        unknown = set(patch) - mutable
        if unknown:
            raise ValidationError(
                [{"name": k, "reason": "not updatable via update()"} for k in unknown]
            )
        # Permission check also fetches the project, avoiding a second load.
        proj = await self._check_project_edit_permission(session, project_id, acting_user)
        if proj.version != expected_version:
            raise OptimisticConcurrencyError(
                current_version=proj.version, current=proj.to_dict()
            )
        # Re-validate lead pair if either side is in the patch.
        new_lead_id = patch.get("lead_id", proj.lead_id)
        new_lead_type = patch.get("lead_type", proj.lead_type)
        if (new_lead_id is None) != (new_lead_type is None):
            raise ValidationError(
                [{"name": "lead_type", "reason": "must be paired with lead_id"}]
            )
        if new_lead_type is not None and new_lead_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "lead_type", "reason": "must be 'user' or 'agent'"}]
            )
        for k, v in patch.items():
            setattr(proj, k, v)
        proj.version = proj.version + 1
        await session.flush([proj])
        # v2.1-WP11: refresh so server-side ``updated_at`` (onupdate) is
        # loaded eagerly; the route's ``to_dict()`` would otherwise trigger
        # a lazy IO outside the async greenlet context when serialising.
        await session.refresh(proj)
        return proj

    async def archive(
        self, session: AsyncSession, project_id: UUID | str
    ) -> Project:
        proj = await self.get_or_raise(session, project_id)
        proj.archived = True
        proj.version = proj.version + 1
        await session.flush([proj])
        return proj

    async def unarchive(
        self, session: AsyncSession, project_id: UUID | str
    ) -> Project:
        proj = await self.get_or_raise(session, project_id)
        proj.archived = False
        proj.version = proj.version + 1
        await session.flush([proj])
        return proj

    async def delete(
        self, session: AsyncSession, project_id: UUID | str
    ) -> None:
        proj = await self.get_or_raise(session, project_id)
        # Refuse delete if the project still has tickets — spec §8.
        count_res = await session.execute(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.project_id == proj.id)
        )
        count = int(count_res.scalar_one())
        if count > 0:
            raise ProjectHasTicketsError(count)
        await session.delete(proj)
        await session.flush()
        await session.execute(text(f'DROP SEQUENCE IF EXISTS {_seq_name(proj.key)}'))

    # -- members ------------------------------------------------------------

    async def add_member(
        self,
        session: AsyncSession,
        project_id: UUID | str,
        *,
        member_id: UUID,
        member_type: str,
        role: ProjectRole | str = ProjectRole.member,
    ) -> ProjectMember:
        if member_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "member_type", "reason": "must be 'user' or 'agent'"}]
            )
        proj = await self.get_or_raise(session, project_id)
        r = role if isinstance(role, ProjectRole) else ProjectRole(role)
        existing = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.member_id == member_id,
                ProjectMember.member_type == member_type,
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            prior.role = r
            await session.flush([prior])
            return prior
        m = ProjectMember(
            project_id=proj.id,
            member_id=member_id,
            member_type=member_type,
            role=r,
        )
        session.add(m)
        await session.flush([m])
        return m

    async def remove_member(
        self,
        session: AsyncSession,
        project_id: UUID | str,
        *,
        member_id: UUID,
        member_type: str = "user",
        acting_user: "User",
    ) -> None:
        proj = await self._check_project_edit_permission(session, project_id, acting_user)
        res = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.member_id == member_id,
                ProjectMember.member_type == member_type,
            )
        )
        m = res.scalar_one_or_none()
        if m is None:
            return
        await session.delete(m)
        await session.flush()

    async def update_member_role(
        self,
        session: AsyncSession,
        project_id: UUID | str,
        *,
        member_id: UUID,
        member_type: str,
        role: ProjectRole | str,
        acting_user: "User",
    ) -> ProjectMember:
        proj = await self._check_project_edit_permission(session, project_id, acting_user)
        r = role if isinstance(role, ProjectRole) else ProjectRole(role)
        res = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.member_id == member_id,
                ProjectMember.member_type == member_type,
            )
        )
        m = res.scalar_one_or_none()
        if m is None:
            raise ValidationError(
                [{"name": "member_id", "reason": "not a member of this project"}]
            )
        m.role = r
        await session.flush([m])
        return m

    async def list_members(
        self, session: AsyncSession, project_id: UUID | str
    ) -> list[ProjectMember]:
        proj = await self.get_or_raise(session, project_id)
        res = await session.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == proj.id)
            .order_by(ProjectMember.created_at.asc())
        )
        return list(res.scalars().all())

    # -- display_id helpers -------------------------------------------------

    async def next_display_id(
        self, session: AsyncSession, project_key: str
    ) -> str:
        """Allocate the next ``{KEY}-{n}`` for the given project key.

        Calls ``nextval('seq_<lc_key>')`` and formats. Caller is responsible
        for setting both ``tickets.seq_number`` (from nextval) and
        ``tickets.display_id`` (from this helper) in the same TX as the
        INSERT. (We expose two helpers because the migration is loath to
        re-fetch the nextval.)
        """
        seq = _seq_name(project_key)
        res = await session.execute(text(f"SELECT nextval('{seq}')"))
        n = int(res.scalar_one())
        return f"{project_key}-{n}"

    async def next_seq_number(
        self, session: AsyncSession, project_key: str
    ) -> int:
        """Allocate the next integer from ``seq_<lc_key>``.

        Use this when you need the raw integer (e.g. to set
        ``tickets.seq_number``) without formatting.
        """
        seq = _seq_name(project_key)
        res = await session.execute(text(f"SELECT nextval('{seq}')"))
        return int(res.scalar_one())


# Module-level singleton (the service is stateless).
project_service = ProjectService()
