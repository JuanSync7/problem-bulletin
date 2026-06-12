"""Ticket model — Kanban work-tracker core entity (Ticketing v2).

Maps to the ``tickets`` table (originally renamed from ``work_items`` in
migration ``a8_finalize_ticket_split``; extended in ``a9_ticketing_v2``).
This is the canonical work-tracker entity; the legacy Problem/bulletin
domain lives on the separate ``problems`` table.

v2 (per ``docs/specs/ticketing-v2.md``):
- Belongs to a ``Project`` via the required ``project_id``.
- May be assigned to a ``Sprint`` and/or ``Component``.
- Carries a denormalised ``epic_id`` to the first ancestor of type ``epic``
  (service-maintained on parent-change; backfilled in the migration).
- ``display_id`` is no longer ``GENERATED ALWAYS`` — it is plain TEXT,
  populated by the service layer as ``f"{project.key}-{nextval}"``.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    ENUM as PgENUM,
    JSONB,
    TSVECTOR,
    UUID as PgUUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import TicketPriority, TicketStatus, TicketType


class Ticket(Base):
    """Canonical ticket row.

    DB-level invariants (v2):
    - ck_tickets_assignee_pair: assignee_id and assignee_type co-null.
    - ck_tickets_assignee_type: assignee_type IN ('user','agent') if set.
    - ck_tickets_reporter_type: reporter_type IN ('user','agent').
    - ck_tickets_custom_fields_object: custom_fields must be a JSON object.
    - ck_tickets_hierarchy_no_self: a ticket cannot be its own parent.
    - ck_tickets_subtask_has_parent: subtask rows MUST have a parent_id.
    - ck_tickets_created_agent_step_id: created_agent_step_id is only set
      when reporter_type='agent'.
    - trg_tickets_same_project (trigger): parent.project_id must match
      child.project_id on INSERT/UPDATE of parent_id or project_id.
    - fk_tickets_project_id ON DELETE RESTRICT.
    - fk_tickets_parent_id ON DELETE RESTRICT.
    - fk_tickets_sprint_id / _component_id / _epic_id ON DELETE SET NULL.
    """

    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("seq_number", name="uq_tickets_seq_number"),
        UniqueConstraint("display_id", name="uq_tickets_display_id"),
        UniqueConstraint(
            "project_id", "seq_number", name="uq_tickets_project_seq"
        ),
        CheckConstraint(
            "(assignee_id IS NULL AND assignee_type IS NULL) OR "
            "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
            name="assignee_pair",
        ),
        CheckConstraint(
            "assignee_type IS NULL OR assignee_type IN ('user','agent')",
            name="assignee_type",
        ),
        CheckConstraint(
            "reporter_type IN ('user','agent')",
            name="reporter_type",
        ),
        CheckConstraint(
            "jsonb_typeof(custom_fields) = 'object'",
            name="custom_fields_object",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="hierarchy_no_self",
        ),
        CheckConstraint(
            "type <> 'subtask' OR parent_id IS NOT NULL",
            name="subtask_has_parent",
        ),
        CheckConstraint(
            "reporter_type = 'agent' OR created_agent_step_id IS NULL",
            name="created_agent_step_id",
        ),
        CheckConstraint(
            "last_actor_type IS NULL OR last_actor_type IN ('user','agent')",
            name="last_actor_type",
        ),
        CheckConstraint(
            "last_actor_type = 'agent' OR last_agent_step_id IS NULL",
            name="last_agent_step_id",
        ),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    seq_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # v2: plain TEXT, populated by service layer as f"{project.key}-{n}".
    display_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[TicketType] = mapped_column(
        PgENUM(TicketType, name="ticket_type", create_type=False),
        nullable=False,
        default=TicketType.task,
    )
    status: Mapped[TicketStatus] = mapped_column(
        PgENUM(TicketStatus, name="ticket_status", create_type=False),
        nullable=False,
        default=TicketStatus.todo,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        PgENUM(TicketPriority, name="ticket_priority", create_type=False),
        nullable=False,
        default=TicketPriority.medium,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "tickets.id",
            ondelete="RESTRICT",
            name="fk_tickets_parent_id",
        ),
        nullable=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="RESTRICT",
            name="fk_tickets_project_id",
        ),
        nullable=False,
    )
    sprint_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "sprints.id",
            ondelete="SET NULL",
            name="fk_tickets_sprint_id",
        ),
        nullable=True,
    )
    component_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "components.id",
            ondelete="SET NULL",
            name="fk_tickets_component_id",
        ),
        nullable=True,
    )
    epic_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "tickets.id",
            ondelete="SET NULL",
            name="fk_tickets_epic_id",
        ),
        nullable=True,
    )
    reporter_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_tickets_reporter_id"),
        nullable=False,
    )
    reporter_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user"
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    assignee_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    labels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    fix_versions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default="{}",
    )
    custom_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_agent_step_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # v2.1 WP6: "last touched by" aggregate. Service-maintained on every
    # write that produces an audit event (create, update, transition,
    # assign, claim, comment, link, watcher, attachment). The Kanban card
    # reads ``last_actor_type === 'agent'`` to render the agent badge —
    # the WP5 fallback to ``reporter_type`` is removed in v2.1.
    last_actor_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_actor_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_agent_step_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
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
    # search_tsv is a Postgres GENERATED ALWAYS column — never INSERT/UPDATE it.
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
    )

    @property
    def computed_display_id(self) -> str | None:
        """Back-compat alias for ``display_id``.

        Pre-v2 the ``display_id`` column was ``GENERATED ALWAYS`` and we
        provided this property to compute the value without round-tripping
        to PG. In v2 the column is plain TEXT populated by the service
        layer; we keep the property so existing call sites (MCP tools,
        agent-activity route, WS test) continue to work.
        """
        return self.display_id

    # Relationships (v2). All lazy by default — service layer drives loading.
    project = relationship(
        "Project", foreign_keys=[project_id], lazy="raise"
    )
    sprint = relationship(
        "Sprint", foreign_keys=[sprint_id], lazy="raise"
    )
    component = relationship(
        "Component", foreign_keys=[component_id], lazy="raise"
    )
    watchers = relationship(
        "TicketWatcher",
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    attachments = relationship(
        "TicketAttachment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def to_dict(self) -> dict:
        """Serializable dict — used for audit before/after and API responses."""
        return {
            "id": str(self.id) if self.id else None,
            "seq_number": self.seq_number,
            "display_id": self.display_id,
            "title": self.title,
            "description": self.description,
            "type": self.type.value if self.type else None,
            "status": self.status.value if self.status else None,
            "priority": self.priority.value if self.priority else None,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "sprint_id": str(self.sprint_id) if self.sprint_id else None,
            "component_id": (
                str(self.component_id) if self.component_id else None
            ),
            "epic_id": str(self.epic_id) if self.epic_id else None,
            "reporter_id": str(self.reporter_id) if self.reporter_id else None,
            "reporter_type": self.reporter_type,
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
            "assignee_type": self.assignee_type,
            "story_points": self.story_points,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "labels": list(self.labels or []),
            "fix_versions": list(self.fix_versions or []),
            "custom_fields": dict(self.custom_fields or {}),
            "resolution": self.resolution,
            "resolved_at": (
                self.resolved_at.isoformat() if self.resolved_at else None
            ),
            "created_agent_step_id": self.created_agent_step_id,
            "last_actor_type": self.last_actor_type,
            "last_actor_id": (
                str(self.last_actor_id) if self.last_actor_id else None
            ),
            "last_activity_at": (
                self.last_activity_at.isoformat()
                if self.last_activity_at
                else None
            ),
            "last_agent_step_id": self.last_agent_step_id,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
