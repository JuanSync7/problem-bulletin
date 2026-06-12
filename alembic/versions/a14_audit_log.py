"""Ticketing v2.4 WP28 — Admin / privileged-action audit log table.

Revision ID: a14
Revises: a13
Create Date: 2026-05-19

Provides an append-only ``activity_audit_log`` table to record who did what
for admin-gated operations (project creation, handle changes, etc.).

Note: ``audit_log`` is already in use by the kanban event journal
(``a2_agent_kanban``).  ``audit_logs`` is used by the legacy admin AuditLog
model.  This table is therefore named ``activity_audit_log`` to avoid
collision.  The service layer refers to it as the "audit log" for WP28.

Indexes:
  - ``ix_activity_audit_log_created_at``       — time-range queries
  - ``ix_activity_audit_log_event_created_at`` — event + time queries
  - ``ix_activity_audit_log_actor``            — "what did actor X do" queries
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "a14"
down_revision: Union[str, None] = "a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_audit_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_activity_audit_log_created_at",
        "activity_audit_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_activity_audit_log_event_created_at",
        "activity_audit_log",
        ["event", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_activity_audit_log_actor",
        "activity_audit_log",
        ["actor_user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_audit_log_actor", table_name="activity_audit_log")
    op.drop_index(
        "ix_activity_audit_log_event_created_at", table_name="activity_audit_log"
    )
    op.drop_index(
        "ix_activity_audit_log_created_at", table_name="activity_audit_log"
    )
    op.drop_table("activity_audit_log")
