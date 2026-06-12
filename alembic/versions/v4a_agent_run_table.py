"""V4a: agent_run table — durable agent provider execution journal.

Revision ID: v4a_agent_run_table
Revises: z_pg_trgm_indexes
Create Date: 2026-06-02

Adds:
- ``agent_run`` table with FK to agent_accounts(id), tickets(id), and
  ticket_comments(id) (nullable).
- Status CHECK constraint pinning {pending,running,done,error}.
- UNIQUE index on idempotency_key so re-enqueue is a no-op.

Downgrade: drops the table.  No data-preservation concerns at this layer
— the queue is transient/operational state.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision: str = "v4a_agent_run_table"
down_revision: Union[str, None] = "z_pg_trgm_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_accounts.id",
                ondelete="CASCADE",
                name="fk_agent_run_agent_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "ticket_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "tickets.id",
                ondelete="CASCADE",
                name="fk_agent_run_ticket_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "ticket_comments.id",
                ondelete="SET NULL",
                name="fk_agent_run_comment_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','done','error')",
            name="status",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_agent_run_idempotency_key",
        ),
    )
    op.create_index(
        "ix_agent_run_status_enqueued_at",
        "agent_run",
        ["status", "enqueued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_status_enqueued_at", table_name="agent_run")
    op.drop_table("agent_run")
