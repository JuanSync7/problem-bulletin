"""agent-kanban A1: rename problems -> tickets, add core ticket fields and enums

Revision ID: a1_agent_kanban
Revises: 7f57993c9b09
Create Date: 2026-05-12

Adds:
- Enums: ticket_type, ticket_status, ticket_priority, actor_type, ticket_link_type
- Renames problems -> tickets
- New columns: ticket_type, status (new enum-typed), priority, parent_id,
  reporter_id, reporter_type, assignee_id, assignee_type, story_points, due_date,
  labels text[], custom_fields jsonb, version, closed_at, key
- Check constraints for assignee pair, actor types, custom_fields object
- Updates seq_number index name to ix_tickets_seq_number
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import conv  # v2.12-WP08: short-circuit ck convention


revision: str = "a1_agent_kanban"
down_revision: Union[str, None] = "7f57993c9b09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TICKET_TYPE = ("epic", "story", "task", "subtask", "bug")
TICKET_STATUS = ("todo", "in_progress", "in_review", "blocked", "done", "cancelled")
TICKET_PRIORITY = ("lowest", "low", "medium", "high", "highest")
ACTOR_TYPE = ("user", "agent")
TICKET_LINK_TYPE = ("blocks", "relates", "duplicates")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create enums.
    postgresql.ENUM(*TICKET_TYPE, name="ticket_type").create(bind, checkfirst=True)
    postgresql.ENUM(*TICKET_STATUS, name="ticket_status").create(bind, checkfirst=True)
    postgresql.ENUM(*TICKET_PRIORITY, name="ticket_priority").create(bind, checkfirst=True)
    postgresql.ENUM(*ACTOR_TYPE, name="actor_type").create(bind, checkfirst=True)
    postgresql.ENUM(*TICKET_LINK_TYPE, name="ticket_link_type").create(bind, checkfirst=True)

    # 2. Rename problems -> tickets.
    op.rename_table("problems", "tickets")
    # Make legacy description nullable per ticket design (description is optional).
    op.alter_column("tickets", "description", nullable=True)
    # Old index ix_problems_seq_number is auto-renamed by Postgres; rename for clarity.
    op.execute("ALTER INDEX IF EXISTS ix_problems_seq_number RENAME TO ix_tickets_seq_number")
    op.execute("ALTER INDEX IF EXISTS ix_problems_search_vector RENAME TO ix_tickets_search_vector")

    # 3. Add new ticket columns. All nullable or with server defaults so existing
    #    rows (legacy bulletin) backfill cleanly.
    op.add_column(
        "tickets",
        sa.Column(
            "ticket_type",
            postgresql.ENUM(*TICKET_TYPE, name="ticket_type", create_type=False),
            nullable=False,
            server_default="task",
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "priority",
            postgresql.ENUM(*TICKET_PRIORITY, name="ticket_priority", create_type=False),
            nullable=False,
            server_default="medium",
        ),
    )
    # New status column (enum). Legacy `status` (string) retained for backward-compat
    # under the column name `legacy_status` to avoid clobbering the legacy Problem model.
    op.alter_column("tickets", "status", new_column_name="legacy_status")
    op.add_column(
        "tickets",
        sa.Column(
            "status",
            postgresql.ENUM(*TICKET_STATUS, name="ticket_status", create_type=False),
            nullable=False,
            server_default="todo",
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("reporter_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("assignee_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tickets_parent_id",
        "tickets",
        "tickets",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("tickets", sa.Column("story_points", sa.Integer(), nullable=True))
    op.add_column("tickets", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "tickets",
        sa.Column(
            "labels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "custom_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "tickets",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("key", sa.Text(), nullable=True),
    )

    # 4. Check constraints. v2.12-WP08: wrap with conv() to short-circuit
    # the ``ck`` naming-convention template now pinned on Base.metadata.
    op.create_check_constraint(
        conv("ck_tickets_assignee_pair"),
        "tickets",
        "(assignee_id IS NULL AND assignee_type IS NULL) OR "
        "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
    )
    op.create_check_constraint(
        conv("ck_tickets_assignee_type"),
        "tickets",
        "assignee_type IS NULL OR assignee_type IN ('user','agent')",
    )
    op.create_check_constraint(
        conv("ck_tickets_reporter_type"),
        "tickets",
        "reporter_type IS NULL OR reporter_type IN ('user','agent')",
    )
    op.create_check_constraint(
        conv("ck_tickets_custom_fields_object"),
        "tickets",
        "jsonb_typeof(custom_fields) = 'object'",
    )
    op.create_check_constraint(
        conv("ck_tickets_hierarchy_no_self"),
        "tickets",
        "parent_id IS NULL OR parent_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint(conv("ck_tickets_hierarchy_no_self"), "tickets", type_="check")
    op.drop_constraint(conv("ck_tickets_custom_fields_object"), "tickets", type_="check")
    op.drop_constraint(conv("ck_tickets_reporter_type"), "tickets", type_="check")
    op.drop_constraint(conv("ck_tickets_assignee_type"), "tickets", type_="check")
    op.drop_constraint(conv("ck_tickets_assignee_pair"), "tickets", type_="check")

    op.drop_column("tickets", "key")
    op.drop_column("tickets", "deleted_at")
    op.drop_column("tickets", "closed_at")
    op.drop_column("tickets", "version")
    op.drop_column("tickets", "custom_fields")
    op.drop_column("tickets", "labels")
    op.drop_column("tickets", "due_date")
    op.drop_column("tickets", "story_points")
    op.drop_constraint("fk_tickets_parent_id", "tickets", type_="foreignkey")
    op.drop_column("tickets", "parent_id")
    op.drop_column("tickets", "assignee_type")
    op.drop_column("tickets", "assignee_id")
    op.drop_column("tickets", "reporter_type")
    op.drop_column("tickets", "reporter_id")

    # Restore status: drop new enum column, rename legacy_status back.
    op.drop_column("tickets", "status")
    op.alter_column("tickets", "legacy_status", new_column_name="status")

    op.drop_column("tickets", "priority")
    op.drop_column("tickets", "ticket_type")

    op.execute("ALTER INDEX IF EXISTS ix_tickets_search_vector RENAME TO ix_problems_search_vector")
    op.execute("ALTER INDEX IF EXISTS ix_tickets_seq_number RENAME TO ix_problems_seq_number")
    op.alter_column("tickets", "description", nullable=False)
    op.rename_table("tickets", "problems")

    bind = op.get_bind()
    postgresql.ENUM(name="ticket_link_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="actor_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_priority").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_type").drop(bind, checkfirst=True)
