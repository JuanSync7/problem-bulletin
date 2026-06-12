"""V6a: project_lesson table — append-only project-scoped lessons.

Revision ID: v6a_project_lesson_table
Revises: v4a_agent_run_table
Create Date: 2026-06-02

Adds:
- ``project_lesson`` table with FK to projects(id), users(id) nullable,
  agent_accounts(id) nullable.
- Source CHECK constraint pinning {'user','agent'}.
- BTREE index on (project_id, created_at DESC) for newest-first list.

Append-only: no PATCH/DELETE flow planned. Downgrade drops the table.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision: str = "v6a_project_lesson_table"
down_revision: Union[str, None] = "v4a_agent_run_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_lesson",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_project_lesson_project_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_project_lesson_author_user_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "author_agent_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_accounts.id",
                ondelete="SET NULL",
                name="fk_project_lesson_author_agent_id",
            ),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "source IN ('user','agent')",
            name="ck_project_lesson_source",
        ),
    )
    op.create_index(
        "ix_project_lesson_project_created",
        "project_lesson",
        ["project_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_lesson_project_created", table_name="project_lesson"
    )
    op.drop_table("project_lesson")
