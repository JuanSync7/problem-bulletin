"""Ticketing v2.1 WP6 — ``tickets.last_actor_*`` aggregate.

Revision ID: a10_ticket_last_actor
Revises: a9_ticketing_v2
Create Date: 2026-05-18

WP6 of the Ticketing v2.1 polish initiative. Adds a "last touched by"
aggregate to ``tickets`` so the Kanban card can render the agent-activity
badge precisely (the WP5 board fell back to ``reporter_type``, which only
catches agent-*created* tickets — not subsequent agent activity).

Columns added:

  * ``last_actor_type   TEXT NULL`` — CHECK in ('user','agent').
  * ``last_actor_id     UUID NULL``.
  * ``last_activity_at  TIMESTAMPTZ NULL`` (indexed for sort).
  * ``last_agent_step_id TEXT NULL``.

Maintenance is SERVICE-LAYER, per v2 Lesson §5 — triggers are reserved
for cross-row CHECKs; aggregates are a service concern. The migration
performs a one-shot backfill from the union of ``ticket_transitions`` and
``ticket_comments`` (latest row wins per ticket); tickets with neither
fall back to their ``reporter_*`` + ``created_at``.

Downgrade is clean: drop the four columns and the index, no enum churn.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv  # v2.12-WP08: short-circuit ck convention


revision: str = "a10_ticket_last_actor"
down_revision: Union[str, None] = "a9_ticketing_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------
    op.add_column(
        "tickets",
        sa.Column("last_actor_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "last_actor_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("last_agent_step_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        conv("ck_tickets_last_actor_type"),
        "tickets",
        "last_actor_type IS NULL OR last_actor_type IN ('user','agent')",
    )
    op.create_check_constraint(
        conv("ck_tickets_last_agent_step_id"),
        "tickets",
        "last_actor_type = 'agent' OR last_agent_step_id IS NULL",
    )
    op.create_index(
        "ix_tickets_last_activity_at",
        "tickets",
        ["last_activity_at"],
        postgresql_where=sa.text("last_activity_at IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # Backfill — union latest transition/comment per ticket; fall back
    # to reporter_* + created_at when neither exists.
    # ------------------------------------------------------------------
    op.execute(
        """
        WITH activity AS (
            SELECT ticket_id, created_at, actor_id AS actor_id,
                   actor_type AS actor_type, agent_step_id
              FROM ticket_transitions
            UNION ALL
            SELECT ticket_id, created_at, author_id AS actor_id,
                   author_type AS actor_type, agent_step_id
              FROM ticket_comments
        ),
        latest AS (
            SELECT DISTINCT ON (ticket_id)
                   ticket_id, created_at, actor_id, actor_type, agent_step_id
              FROM activity
             ORDER BY ticket_id, created_at DESC
        )
        UPDATE tickets t
           SET last_actor_type    = l.actor_type,
               last_actor_id      = l.actor_id,
               last_activity_at   = l.created_at,
               last_agent_step_id = CASE
                                      WHEN l.actor_type = 'agent'
                                        THEN l.agent_step_id
                                      ELSE NULL
                                    END
          FROM latest l
         WHERE t.id = l.ticket_id
        """
    )

    # Fallback: tickets with no transition AND no comment row. Stamp
    # from reporter side + created_at.
    op.execute(
        """
        UPDATE tickets
           SET last_actor_type    = reporter_type,
               last_actor_id      = reporter_id,
               last_activity_at   = created_at,
               last_agent_step_id = CASE
                                      WHEN reporter_type = 'agent'
                                        THEN created_agent_step_id
                                      ELSE NULL
                                    END
         WHERE last_activity_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_last_activity_at", table_name="tickets")
    op.drop_constraint(
        conv("ck_tickets_last_agent_step_id"), "tickets", type_="check"
    )
    op.drop_constraint(
        conv("ck_tickets_last_actor_type"), "tickets", type_="check"
    )
    op.drop_column("tickets", "last_agent_step_id")
    op.drop_column("tickets", "last_activity_at")
    op.drop_column("tickets", "last_actor_id")
    op.drop_column("tickets", "last_actor_type")
