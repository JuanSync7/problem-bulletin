"""Step 2: create work_items table + related tables for Kanban work-tracker.

Revision ID: a7_create_work_items
Revises: a6_rename_tickets_to_problems
Create Date: 2026-05-16

Introduces a fresh, dedicated work-tracker entity ("work item") with proper
Epic / Story / Task / Subtask hierarchy. Coexists with the legacy ``Ticket``
ORM (which still maps the ``problems`` table) until Step 3 deletes the legacy
class and renames ``work_items`` -> ``tickets``.

Reuses existing enums where compatible:
- ``ticket_type``      — values include the required {epic, story, task, subtask}
                         plus legacy ``bug``. Reused.
- ``ticket_status``    — exact match. Reused.
- ``actor_type``       — exact match. Reused.

New enums (existing ones don't match the spec):
- ``work_item_priority``  : low | medium | high | urgent
- ``work_item_link_type`` : blocks | is_blocked_by | duplicates |
                            is_duplicate_of | relates_to | parent_of | child_of

Tables created:
- ``work_items``
- ``work_item_comments``
- ``work_item_transitions``
- ``work_item_links``

A new Postgres sequence ``work_items_seq_number_seq`` mirrors the existing
``problems_seq_number_seq`` pattern for atomic seq_number allocation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv  # v2.13-WP02: short-circuit ck convention
from sqlalchemy.dialects import postgresql


revision: str = "a7_create_work_items"
down_revision: Union[str, None] = "a6_rename_tickets_to_problems"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WORK_ITEM_PRIORITY = ("low", "medium", "high", "urgent")
WORK_ITEM_LINK_TYPE = (
    "blocks",
    "is_blocked_by",
    "duplicates",
    "is_duplicate_of",
    "relates_to",
    "parent_of",
    "child_of",
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create new enums (reuse ticket_type / ticket_status / actor_type).
    postgresql.ENUM(*WORK_ITEM_PRIORITY, name="work_item_priority").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*WORK_ITEM_LINK_TYPE, name="work_item_link_type").create(
        bind, checkfirst=True
    )

    # 2. Sequence for seq_number allocation.
    op.execute("CREATE SEQUENCE IF NOT EXISTS work_items_seq_number_seq")

    # 3. work_items table.
    op.create_table(
        "work_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "seq_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("nextval('work_items_seq_number_seq')"),
        ),
        sa.Column(
            "display_id",
            sa.Text(),
            sa.Computed("'WI-' || seq_number::text", persisted=True),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "type",
            postgresql.ENUM(name="ticket_type", create_type=False),
            nullable=False,
            server_default="task",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=False,
            server_default="todo",
        ),
        sa.Column(
            "priority",
            postgresql.ENUM(name="work_item_priority", create_type=False),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "parent_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "reporter_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "reporter_type", sa.Text(), nullable=False, server_default="user"
        ),
        sa.Column(
            "assignee_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("assignee_type", sa.Text(), nullable=True),
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column(
            "due_date", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "labels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "custom_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["work_items.id"],
            name="fk_work_items_parent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name="fk_work_items_reporter_id",
        ),
        sa.UniqueConstraint("seq_number", name="uq_work_items_seq_number"),
        sa.CheckConstraint(
            "(assignee_id IS NULL AND assignee_type IS NULL) OR "
            "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
            name=conv("ck_work_items_assignee_pair"),
        ),
        sa.CheckConstraint(
            "assignee_type IS NULL OR assignee_type IN ('user','agent')",
            name=conv("ck_work_items_assignee_type"),
        ),
        sa.CheckConstraint(
            "reporter_type IN ('user','agent')",
            name=conv("ck_work_items_reporter_type"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(custom_fields) = 'object'",
            name=conv("ck_work_items_custom_fields_object"),
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name=conv("ck_work_items_hierarchy_no_self"),
        ),
    )
    op.create_index(
        "ix_work_items_status_assignee",
        "work_items",
        ["status", "assignee_id"],
    )
    op.create_index("ix_work_items_parent_id", "work_items", ["parent_id"])
    op.create_index("ix_work_items_updated_at", "work_items", ["updated_at"])
    op.create_index(
        "gin_work_items_labels",
        "work_items",
        ["labels"],
        postgresql_using="gin",
    )
    op.create_index(
        "gin_work_items_search_tsv",
        "work_items",
        ["search_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "gin_work_items_custom_fields",
        "work_items",
        ["custom_fields"],
        postgresql_using="gin",
    )

    # 4. work_item_comments.
    op.create_table(
        "work_item_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "work_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("author_type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "correlation_id",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "author_type IN ('user','agent')",
            name=conv("ck_work_item_comments_author_type"),
        ),
    )
    op.create_index(
        "ix_work_item_comments_work_item_created",
        "work_item_comments",
        ["work_item_id", sa.text("created_at ASC")],
    )

    # 5. work_item_transitions.
    op.create_table(
        "work_item_transitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "work_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "correlation_id",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user','agent')",
            name=conv("ck_work_item_transitions_actor_type"),
        ),
    )
    op.create_index(
        "ix_work_item_transitions_work_item_created",
        "work_item_transitions",
        ["work_item_id", sa.text("created_at DESC")],
    )

    # 6. work_item_links.
    op.create_table(
        "work_item_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "link_type",
            postgresql.ENUM(name="work_item_link_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_by_type",
            sa.Text(),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "source_id",
            "target_id",
            "link_type",
            name="uq_work_item_links",
        ),
        sa.CheckConstraint(
            "source_id <> target_id", name=conv("ck_work_item_links_no_self")
        ),
        sa.CheckConstraint(
            "created_by_type IN ('user','agent')",
            name=conv("ck_work_item_links_created_by_type"),
        ),
    )
    op.create_index(
        "ix_work_item_links_source", "work_item_links", ["source_id"]
    )
    op.create_index(
        "ix_work_item_links_target", "work_item_links", ["target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_work_item_links_target", table_name="work_item_links")
    op.drop_index("ix_work_item_links_source", table_name="work_item_links")
    op.drop_table("work_item_links")

    op.drop_index(
        "ix_work_item_transitions_work_item_created",
        table_name="work_item_transitions",
    )
    op.drop_table("work_item_transitions")

    op.drop_index(
        "ix_work_item_comments_work_item_created",
        table_name="work_item_comments",
    )
    op.drop_table("work_item_comments")

    op.drop_index("gin_work_items_custom_fields", table_name="work_items")
    op.drop_index("gin_work_items_search_tsv", table_name="work_items")
    op.drop_index("gin_work_items_labels", table_name="work_items")
    op.drop_index("ix_work_items_updated_at", table_name="work_items")
    op.drop_index("ix_work_items_parent_id", table_name="work_items")
    op.drop_index("ix_work_items_status_assignee", table_name="work_items")
    op.drop_table("work_items")

    op.execute("DROP SEQUENCE IF EXISTS work_items_seq_number_seq")

    bind = op.get_bind()
    postgresql.ENUM(name="work_item_link_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="work_item_priority").drop(bind, checkfirst=True)
