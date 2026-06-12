"""V7a: ticket_comments.parent_comment_id — nested reply hierarchy.

Revision ID: v7a_ticket_comment_parent
Revises: v6b_agent_run_lesson_idx
Create Date: 2026-06-03

Adds a nullable self-referential FK ``parent_comment_id`` to
``ticket_comments`` so the ticket comment thread can match the problem
comment hierarchy (``comments.parent_comment_id``). Append-only intent
preserved — no edit/delete flows are implied by this column.

Index: ``(ticket_id, parent_comment_id, created_at)`` to keep the
tree-rendering query (children of a parent, in chronological order)
on a single index scan.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision: str = "v7a_ticket_comment_parent"
down_revision: Union[str, None] = "v6b_agent_run_lesson_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ticket_comments",
        sa.Column(
            "parent_comment_id",
            pg.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_ticket_comments_parent_comment_id",
        "ticket_comments",
        "ticket_comments",
        ["parent_comment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_ticket_comments_ticket_parent_created",
        "ticket_comments",
        ["ticket_id", "parent_comment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ticket_comments_ticket_parent_created",
        table_name="ticket_comments",
    )
    op.drop_constraint(
        "fk_ticket_comments_parent_comment_id",
        "ticket_comments",
        type_="foreignkey",
    )
    op.drop_column("ticket_comments", "parent_comment_id")
