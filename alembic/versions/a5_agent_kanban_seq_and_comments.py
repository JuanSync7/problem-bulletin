"""agent-kanban A5: ticket seq sequence + ticket_comments table

Revision ID: a5_agent_kanban
Revises: a4_agent_kanban
Create Date: 2026-05-12

Adds:
- Postgres sequence ``tickets_seq_number_seq`` for atomic seq_number allocation
- ``ticket_comments`` append-only table (replaces legacy ``comments`` for the
  agent-kanban service layer, which keeps comments isolated by author_type and
  correlation_id)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5_agent_kanban"
down_revision: Union[str, None] = "a4_agent_kanban"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create global ticket seq_number sequence, seeded past any legacy rows.
    op.execute("CREATE SEQUENCE IF NOT EXISTS tickets_seq_number_seq")
    op.execute(
        "SELECT setval('tickets_seq_number_seq', "
        "GREATEST(COALESCE((SELECT MAX(seq_number) FROM tickets), 0), 1))"
    )

    # ticket_comments: append-only, correlation-id stamped, agent-or-user author
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_comments (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            ticket_id      UUID        NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            author_id      UUID        NOT NULL,
            author_type    TEXT        NOT NULL CHECK (author_type IN ('user','agent')),
            body           TEXT        NOT NULL,
            correlation_id TEXT        NOT NULL DEFAULT '',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_comments_ticket_created "
        "ON ticket_comments(ticket_id, created_at ASC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ticket_comments_ticket_created")
    op.execute("DROP TABLE IF EXISTS ticket_comments")
    op.execute("DROP SEQUENCE IF EXISTS tickets_seq_number_seq")
