"""Ticketing v2.4 WP30 — Backfill agent_accounts.created_by from oldest admin user.

Revision ID: a16
Revises: a15
Create Date: 2026-05-19

Best-effort backfill: for legacy ``agent_accounts`` rows where
``created_by IS NULL``, set the value to the oldest admin user (by
``created_at ASC``, where ``role = 'admin'``).  If no admin user exists
in the target environment the UPDATE is skipped entirely and the
migration still succeeds.

DO NOT add a NOT NULL constraint here — some environments may legitimately
have no admin, leaving NULLs.  That tightening is deferred to a future WP.

Downgrade: no-op.  We cannot un-set the backfill cleanly (we don't know
which rows were NULL before), and the data is safe to keep.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a16"
down_revision: Union[str, None] = "a15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Best-effort: only run the UPDATE when at least one admin user exists.
    # Wrapped in a DO block so the migration never raises even in stripped
    # test environments with no admin rows.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE role = 'admin') THEN
                UPDATE agent_accounts
                SET created_by = (
                    SELECT id FROM users
                    WHERE role = 'admin'
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                WHERE created_by IS NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # No-op: backfill is not reversible without a pre-migration snapshot.
    pass
