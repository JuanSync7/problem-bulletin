"""Ticketing v2.4 WP28 — Expression index for ticket activity ordering.

Revision ID: a13
Revises: a12
Create Date: 2026-05-19

WP22 added ``order_by=last_activity_at`` to ``GET /api/v1/tickets``.  The
resulting ORDER BY clause is:

    COALESCE(tickets.last_activity_at, tickets.created_at) DESC, tickets.id DESC

Without a supporting index this degrades to a full table scan + filesort on
large datasets.  This migration adds a matching expression index so Postgres
can satisfy the sort using an index-only scan.

``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction.  Alembic 1.13+
exposes ``op.get_context().autocommit_block()`` for exactly this use-case.
The downgrade mirrors the upgrade pattern (``DROP INDEX CONCURRENTLY``).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a13"
down_revision: Union[str, None] = "a12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tickets_activity_order
              ON tickets (COALESCE(last_activity_at, created_at) DESC, id DESC)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_tickets_activity_order"
        )
