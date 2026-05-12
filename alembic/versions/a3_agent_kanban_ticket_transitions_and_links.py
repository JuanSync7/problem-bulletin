"""agent-kanban A3: add ticket_transitions and ticket_links tables

Revision ID: a3_agent_kanban
Revises: a2_agent_kanban
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a3_agent_kanban"
down_revision: Union[str, None] = "a2_agent_kanban"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_transitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
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
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user','agent')",
            name="ck_ticket_transitions_actor_type",
        ),
    )
    op.create_index(
        "ix_ticket_transitions_ticket_created",
        "ticket_transitions",
        ["ticket_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "ticket_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "link_type",
            postgresql.ENUM(name="ticket_link_type", create_type=False),
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
            name="uq_ticket_links",
        ),
        sa.CheckConstraint(
            "source_id <> target_id", name="ck_ticket_links_no_self"
        ),
        sa.CheckConstraint(
            "created_by_type IN ('user','agent')",
            name="ck_ticket_links_created_by_type",
        ),
    )
    op.create_index("ix_ticket_links_source", "ticket_links", ["source_id"])
    op.create_index("ix_ticket_links_target", "ticket_links", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_links_target", table_name="ticket_links")
    op.drop_index("ix_ticket_links_source", table_name="ticket_links")
    op.drop_table("ticket_links")
    op.drop_index(
        "ix_ticket_transitions_ticket_created", table_name="ticket_transitions"
    )
    op.drop_table("ticket_transitions")
