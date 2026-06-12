"""agent-kanban A4: add search indexes to tickets

Revision ID: a4_agent_kanban
Revises: a3_agent_kanban
Create Date: 2026-05-12

Adds:
- GIN index on labels
- search_tsv generated column + GIN index on it
- btree index on (status, assignee_id) partial WHERE deleted_at IS NULL
- btree index on parent_id partial WHERE deleted_at IS NULL
- btree index on (project-irrelevant since no project_id here yet) updated_at DESC
- GIN index on custom_fields (jsonb_path_ops)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4_agent_kanban"
down_revision: Union[str, None] = "a3_agent_kanban"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # search_tsv generated column derived from title + description.
    op.execute(
        """
        ALTER TABLE tickets ADD COLUMN search_tsv tsvector
        GENERATED ALWAYS AS (
          setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
          setweight(to_tsvector('english', coalesce(description, '')), 'B')
        ) STORED
        """
    )

    op.create_index(
        "gin_tickets_labels",
        "tickets",
        ["labels"],
        postgresql_using="gin",
    )
    op.create_index(
        "gin_tickets_search_tsv",
        "tickets",
        ["search_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "gin_tickets_custom_fields",
        "tickets",
        ["custom_fields"],
        postgresql_using="gin",
        postgresql_ops={"custom_fields": "jsonb_path_ops"},
    )

    op.create_index(
        "ix_tickets_status_assignee",
        "tickets",
        ["status", "assignee_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tickets_parent_id",
        "tickets",
        ["parent_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tickets_updated_at",
        "tickets",
        [sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_updated_at", table_name="tickets")
    op.drop_index("ix_tickets_parent_id", table_name="tickets")
    op.drop_index("ix_tickets_status_assignee", table_name="tickets")
    op.drop_index("gin_tickets_custom_fields", table_name="tickets")
    op.drop_index("gin_tickets_search_tsv", table_name="tickets")
    op.drop_index("gin_tickets_labels", table_name="tickets")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS search_tsv")
