"""V8b: bounties — the Bounty space (v2.29-S4).

Revision ID: v8b
Revises: v8a
Create Date: 2026-06-12

Adds ``bounties``: user-posted points rewards on problems/tickets or
standalone ideas. Claimant is a polymorphic (claimant_id, claimant_type)
pair with a co-null CHECK (mirrors tickets.assignee_*). Status lifecycle:
open → claimed → awarded, open → withdrawn, claimed → open (unclaim).

Index on (status, created_at DESC) for the status-filtered newest-first
feed. Downgrade drops the table.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.sql.elements import conv


revision: str = "v8b"
down_revision: Union[str, None] = "v8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bounties",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "poster_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name=conv("fk_bounties_poster_user_id_users"),
            ),
            nullable=True,
        ),
        sa.Column(
            "ticket_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "tickets.id",
                ondelete="SET NULL",
                name=conv("fk_bounties_ticket_id_tickets"),
            ),
            nullable=True,
        ),
        sa.Column(
            "problem_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "problems.id",
                ondelete="SET NULL",
                name=conv("fk_bounties_problem_id_problems"),
            ),
            nullable=True,
        ),
        sa.Column("claimant_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("claimant_type", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "points > 0",
            name=conv("ck_bounties_points_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('open','claimed','awarded','withdrawn')",
            name=conv("ck_bounties_status"),
        ),
        sa.CheckConstraint(
            "(claimant_id IS NULL) = (claimant_type IS NULL)",
            name=conv("ck_bounties_claimant_pair"),
        ),
        sa.CheckConstraint(
            "claimant_type IS NULL OR claimant_type IN ('user','agent')",
            name=conv("ck_bounties_claimant_type"),
        ),
    )
    op.create_index(
        "ix_bounties_status_created_at",
        "bounties",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_bounties_status_created_at", table_name="bounties")
    op.drop_table("bounties")
