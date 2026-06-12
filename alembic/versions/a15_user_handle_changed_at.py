"""Ticketing v2.4 WP29 — Add handle_changed_at column to users.

Revision ID: a15
Revises: a14
Create Date: 2026-05-19

Tracks when a user last changed their handle so the service layer can
enforce the 24-hour cooldown.  NULL means the user has never changed
their handle and may change it immediately.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a15"
down_revision: Union[str, None] = "a14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "handle_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "handle_changed_at")
