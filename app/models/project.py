"""Project / Sprint / Component / ProjectMember models — Ticketing v2.

Maps to the ``projects``, ``sprints``, ``components`` and
``project_members`` tables created in ``a9_ticketing_v2``. See
``docs/specs/ticketing-v2.md`` for the design.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ENUM as PgENUM,
    JSONB,
    UUID as PgUUID,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.enums import ProjectRole, SprintState


class Project(Base):
    """A bucket that owns tickets, sprints, components and members.

    DB invariants:
    - ``key`` matches ``^[A-Z][A-Z0-9]{1,9}$``.
    - ``lead_id`` and ``lead_type`` are co-null.
    - ``lead_type`` (when set) is one of ``user`` / ``agent``.
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("key", name="uq_projects_key"),
        CheckConstraint(
            "key ~ '^[A-Z][A-Z0-9]{1,9}$'",
            name="key_format",
        ),
        CheckConstraint(
            "lead_type IS NULL OR lead_type IN ('user','agent')",
            name="lead_type",
        ),
        CheckConstraint(
            "(lead_id IS NULL AND lead_type IS NULL) OR "
            "(lead_id IS NOT NULL AND lead_type IS NOT NULL)",
            name="lead_pair",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    lead_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    wip_limits: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    state_change_coalesce_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper only
        return f"<Project key={self.key!r} name={self.name!r}>"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "lead_id": str(self.lead_id) if self.lead_id else None,
            "lead_type": self.lead_type,
            "archived": self.archived,
            "wip_limits": dict(self.wip_limits or {}),
            "state_change_coalesce_seconds": self.state_change_coalesce_seconds,
            "version": self.version,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


class Sprint(Base):
    """Time-boxed delivery window scoped to a single project."""

    __tablename__ = "sprints"
    __table_args__ = (
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
            name="date_order",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
            name="fk_sprints_project_id",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[SprintState] = mapped_column(
        PgENUM(SprintState, name="sprint_state", create_type=False),
        nullable=False,
        default=SprintState.planned,
        server_default="planned",
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sprint name={self.name!r} state={self.state}>"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "name": self.name,
            "goal": self.goal,
            "state": self.state.value if self.state else None,
            "start_date": (
                self.start_date.isoformat() if self.start_date else None
            ),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


class Component(Base):
    """Per-project bucket (e.g. "Frontend", "API") for ticket categorisation."""

    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", name="uq_components_project_name"
        ),
        CheckConstraint(
            "lead_type IS NULL OR lead_type IN ('user','agent')",
            name="lead_type",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
            name="fk_components_project_id",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    lead_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Component name={self.name!r}>"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "name": self.name,
            "description": self.description,
            "lead_id": str(self.lead_id) if self.lead_id else None,
            "lead_type": self.lead_type,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


class ProjectMember(Base):
    """Membership row binding a user or agent to a project with a role."""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "member_id",
            "member_type",
            name="uq_project_members",
        ),
        CheckConstraint(
            "member_type IN ('user','agent')",
            name="member_type",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
            name="fk_project_members_project_id",
        ),
        nullable=False,
    )
    member_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    member_type: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[ProjectRole] = mapped_column(
        PgENUM(ProjectRole, name="project_role", create_type=False),
        nullable=False,
        default=ProjectRole.member,
        server_default="member",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ProjectMember project={self.project_id} "
            f"member={self.member_id} role={self.role}>"
        )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id) if self.id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "member_id": str(self.member_id) if self.member_id else None,
            "member_type": self.member_type,
            "role": self.role.value if self.role else None,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
