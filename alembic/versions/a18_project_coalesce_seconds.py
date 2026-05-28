"""Add state_change_coalesce_seconds to projects.

Revision ID: a18_project_coalesce_seconds
Revises: a17_agent_accounts_created_by_not_null
Create Date: 2026-05-19

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv

# revision identifiers, used by Alembic.
revision = "a18_project_coalesce_seconds"
down_revision = "a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "state_change_coalesce_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )
    # v2.12-WP08: ``Base.metadata`` now declares a ``ck`` template that
    # double-wraps any full ``ck_*`` constraint name passed to
    # ``op.create_check_constraint``. Historical alembic migrations
    # carry full names by convention; wrap with ``conv()`` to short-
    # circuit substitution and keep the emitted DDL identical to
    # pre-WP08 (``CONSTRAINT ck_projects_coalesce_seconds_range``).
    op.create_check_constraint(
        conv("ck_projects_coalesce_seconds_range"),
        "projects",
        "state_change_coalesce_seconds >= 0 AND state_change_coalesce_seconds <= 3600",
    )


def downgrade() -> None:
    op.drop_constraint(
        conv("ck_projects_coalesce_seconds_range"), "projects", type_="check"
    )
    op.drop_column("projects", "state_change_coalesce_seconds")
