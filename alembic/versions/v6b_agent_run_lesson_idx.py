"""V6b: project_lesson.agent_run_id + lesson_index + partial UNIQUE.

Revision ID: v6b_agent_run_lesson_idx
Revises: v6a_project_lesson_table
Create Date: 2026-06-02

Adds:
- ``agent_run_id UUID NULL`` FK to ``agent_run.id`` (ON DELETE SET NULL).
- ``lesson_index INTEGER NULL`` — position within the
  ``AgentRunResult.lessons_emitted`` array.
- Partial UNIQUE index
  ``uq_project_lesson_agent_run_idx (agent_run_id, lesson_index)
   WHERE agent_run_id IS NOT NULL``.
  Leaves user-authored lessons (``agent_run_id IS NULL``) un-constrained
  so multiple manual entries can coexist.

The partial unique index is what makes the queue's defensive replay safe:
``ON CONFLICT DO NOTHING`` on ``(agent_run_id, lesson_index)`` collapses
double-emissions to a single row.

Downgrade drops the index and both columns.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision: str = "v6b_agent_run_lesson_idx"
down_revision: Union[str, None] = "v6a_project_lesson_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_lesson",
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_run.id",
                ondelete="SET NULL",
                name="fk_project_lesson_agent_run_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "project_lesson",
        sa.Column("lesson_index", sa.Integer(), nullable=True),
    )
    op.create_index(
        "uq_project_lesson_agent_run_idx",
        "project_lesson",
        ["agent_run_id", "lesson_index"],
        unique=True,
        postgresql_where=sa.text("agent_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_project_lesson_agent_run_idx", table_name="project_lesson"
    )
    op.drop_column("project_lesson", "lesson_index")
    op.drop_column("project_lesson", "agent_run_id")
