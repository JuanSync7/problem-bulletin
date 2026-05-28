"""Ticketing v2.5 WP34 — Conditionally tighten agent_accounts.created_by NOT NULL.

Revision ID: a17
Revises: a16
Create Date: 2026-05-19

Strategy: conditional NOT NULL.

The migration checks at runtime whether any rows have a NULL ``created_by``
value.  If none exist, the column is tightened to NOT NULL.  If NULLs are
found (environments where the a16 backfill found no admin user), the ALTER is
skipped and a NOTICE is emitted instead.

This avoids hard failures in stripped test or development environments where
no admin user was present at the time of a16.

Downgrade: remove the NOT NULL constraint if it was applied (safe; adds back
the nullable marker without any data change).  If the constraint was never
applied, downgrade is a no-op.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a17"
down_revision: Union[str, None] = "a16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Conditional NOT NULL: only apply the constraint if no NULL rows remain.
    # Uses a PL/pgSQL DO block so the migration always succeeds — even in
    # environments where NULLs persist (no admin user at a16 run time).
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM agent_accounts WHERE created_by IS NULL
            ) THEN
                ALTER TABLE agent_accounts
                    ALTER COLUMN created_by SET NOT NULL;
            ELSE
                RAISE NOTICE
                    'agent_accounts has NULL created_by rows; '
                    'skipping NOT NULL constraint — re-run a16 backfill first';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Re-allow NULLs unconditionally.  Safe regardless of whether the
    # constraint was applied in upgrade (PostgreSQL is idempotent here:
    # dropping NOT NULL on an already-nullable column is a no-op).
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE agent_accounts
                ALTER COLUMN created_by DROP NOT NULL;
        EXCEPTION
            WHEN others THEN
                -- Column was already nullable — nothing to do.
                NULL;
        END $$;
        """
    )
