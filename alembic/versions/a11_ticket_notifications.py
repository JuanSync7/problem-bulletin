"""Ticketing v2.1 WP9 — ``ticket_notifications`` table for @mention fanout.

Revision ID: a11_ticket_notifications
Revises: a10_ticket_last_actor
Create Date: 2026-05-18

WP9 of the Ticketing v2.1 polish initiative. Adds a parallel notification
surface for ticket-domain events (initially: ``ticket_mention``), independent
of the bulletin-domain ``notifications`` table.

Why a parallel table (and not extending ``notifications``)?
- The existing ``notifications`` row keys recipient/actor on ``users.id``
  (FK, NOT NULL) and target on ``problems.id`` / ``solutions.id``. Ticket
  mentions need agent recipients/actors AND a ticket target — three FK
  shape mismatches.
- Cross-WP Rule (v2 Lessons): the v2 codebase already adopted "parallel
  table" for ``ticket_watchers`` (vs the bulletin ``watches`` table) and
  ``ticket_attachments`` (vs ``attachments``) for the same reason
  (independent lifecycles). This migration follows that precedent.

Idempotency
-----------
Unique constraint ``uq_ticket_notifications_mention_per_comment`` over
``(comment_id, recipient_type, recipient_id)`` (partial, where ``kind =
'ticket_mention'``). A comment edit that doesn't change its mention set
will not re-notify — the insert collides and is swallowed by the
service-layer ``ON CONFLICT DO NOTHING`` (or caller catch).

Downgrade is clean: drop the table + its indices.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv  # v2.13-WP02: short-circuit ck convention


revision: str = "a11_ticket_notifications"
down_revision: Union[str, None] = "a10_ticket_last_actor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_notifications",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recipient_type", sa.Text(), nullable=False),
        sa.Column(
            "recipient_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column(
            "actor_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column(
            "target_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("target_display_id", sa.Text(), nullable=True),
        sa.Column(
            "comment_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ticket_comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "recipient_type IN ('user','agent')",
            name=conv("ck_ticket_notifications_recipient_type"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user','agent')",
            name=conv("ck_ticket_notifications_actor_type"),
        ),
        sa.CheckConstraint(
            "target_type IN ('ticket')",
            name=conv("ck_ticket_notifications_target_type"),
        ),
    )
    op.create_index(
        "ix_ticket_notifications_recipient",
        "ticket_notifications",
        ["recipient_type", "recipient_id", "created_at"],
    )
    # Idempotency key — at most one mention notification per
    # (comment, recipient). Partial so future ``kind``s (e.g.
    # ticket_assigned) can have their own dedup story without colliding
    # with mentions.
    op.create_index(
        "uq_ticket_notifications_mention_per_comment",
        "ticket_notifications",
        ["comment_id", "recipient_type", "recipient_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'ticket_mention'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ticket_notifications_mention_per_comment",
        table_name="ticket_notifications",
    )
    op.drop_index(
        "ix_ticket_notifications_recipient",
        table_name="ticket_notifications",
    )
    op.drop_table("ticket_notifications")
