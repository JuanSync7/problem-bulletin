"""Ticketing v2.2 WP17 — Real ``handle`` columns on ``users`` + ``agent_accounts``.

Revision ID: a12
Revises: a11_ticket_notifications
Create Date: 2026-05-18

Today handles are derived in Python by ``PeopleService`` (email-local-part
for users, slugified ``name`` for agents). This is fragile (cross-kind
collisions undetected by the DB; not editable). WP17 materialises the
handle as a real column with a unique index per kind.

Algorithm (mirrors the Python derivation used pre-WP17 so behaviour is
functionally identical for existing data):
  1. Lowercase the source (``email`` or ``name``).
  2. For users: take the local-part (everything before the first ``@``).
  3. Replace any character outside ``[a-z0-9_]`` with ``_``.
  4. Collapse runs of ``_`` to a single ``_``.
  5. Strip leading/trailing ``_``.
  6. Resolve collisions *within the same kind* by appending ``_2``,
     ``_3``, ... — ordered by ``created_at`` ascending then ``id`` for
     stability. The FIRST row wins the bare handle.

Cross-kind collisions are explicitly ALLOWED — a user ``alice`` and an
agent ``alice`` may coexist. ``resolve_mention`` discriminates by
``(kind, handle)``.

The whole upgrade runs inside Alembic's default per-migration transaction
so a backfill failure rolls the column add back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a12"
down_revision: Union[str, None] = "a11_ticket_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Backfill SQL — shared shape for users and agents. Each does:
#   1. Compute the raw derived handle (regex_replace + trim).
#   2. ROW_NUMBER OVER (PARTITION BY derived ORDER BY created_at, id) to
#      pick a stable tiebreak.
#   3. UPDATE: row #1 keeps the bare derived handle; rows #N (N>1) get
#      ``derived || '_' || N``.
# ---------------------------------------------------------------------------
_BACKFILL_USERS = """
WITH derived AS (
    SELECT
        id,
        NULLIF(
            TRIM(BOTH '_' FROM
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        SPLIT_PART(LOWER(email), '@', 1),
                        '[^a-z0-9_]', '_', 'g'
                    ),
                    '_+', '_', 'g'
                )
            ),
            ''
        ) AS h,
        created_at
    FROM users
),
ranked AS (
    SELECT
        id,
        -- Fallback to 'user' if the derivation collapsed to empty.
        COALESCE(h, 'user') AS h,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(h, 'user')
            ORDER BY created_at NULLS FIRST, id
        ) AS rn
    FROM derived
)
UPDATE users u
SET handle = CASE WHEN r.rn = 1 THEN r.h ELSE r.h || '_' || r.rn END
FROM ranked r
WHERE u.id = r.id;
"""


_BACKFILL_AGENTS = """
WITH derived AS (
    SELECT
        id,
        NULLIF(
            TRIM(BOTH '_' FROM
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        LOWER(name),
                        '[^a-z0-9_]', '_', 'g'
                    ),
                    '_+', '_', 'g'
                )
            ),
            ''
        ) AS h,
        created_at
    FROM agent_accounts
),
ranked AS (
    SELECT
        id,
        COALESCE(h, 'agent') AS h,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(h, 'agent')
            ORDER BY created_at NULLS FIRST, id
        ) AS rn
    FROM derived
)
UPDATE agent_accounts a
SET handle = CASE WHEN r.rn = 1 THEN r.h ELSE r.h || '_' || r.rn END
FROM ranked r
WHERE a.id = r.id;
"""


# ---------------------------------------------------------------------------
# Auto-derive triggers — keep ``handle`` populated on INSERT when callers
# (e.g. existing test fixtures, legacy auth flows) don't supply it. Mirrors
# the backfill algorithm so behaviour is consistent. Handles uniqueness
# collisions by appending ``_N`` until a free slot is found.
#
# Without these triggers every caller of ``INSERT INTO users (...)`` outside
# the application layer (notably the 30+ test files that build users via
# raw SQL) would need to be updated. The trigger keeps the migration
# functionally backward-compatible at the SQL contract.
# ---------------------------------------------------------------------------
_USERS_HANDLE_FN = """
CREATE OR REPLACE FUNCTION _users_fill_handle() RETURNS trigger AS $$
DECLARE
    base TEXT;
    candidate TEXT;
    n INT;
BEGIN
    IF NEW.handle IS NOT NULL AND NEW.handle <> '' THEN
        RETURN NEW;
    END IF;
    base := NULLIF(
        TRIM(BOTH '_' FROM
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    SPLIT_PART(LOWER(COALESCE(NEW.email, '')), '@', 1),
                    '[^a-z0-9_]', '_', 'g'
                ),
                '_+', '_', 'g'
            )
        ),
        ''
    );
    IF base IS NULL THEN
        base := 'user';
    END IF;
    candidate := base;
    n := 1;
    WHILE EXISTS (SELECT 1 FROM users WHERE handle = candidate AND id <> NEW.id) LOOP
        n := n + 1;
        candidate := base || '_' || n;
    END LOOP;
    NEW.handle := candidate;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_AGENTS_HANDLE_FN = """
CREATE OR REPLACE FUNCTION _agents_fill_handle() RETURNS trigger AS $$
DECLARE
    base TEXT;
    candidate TEXT;
    n INT;
BEGIN
    IF NEW.handle IS NOT NULL AND NEW.handle <> '' THEN
        RETURN NEW;
    END IF;
    base := NULLIF(
        TRIM(BOTH '_' FROM
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    LOWER(COALESCE(NEW.name, '')),
                    '[^a-z0-9_]', '_', 'g'
                ),
                '_+', '_', 'g'
            )
        ),
        ''
    );
    IF base IS NULL THEN
        base := 'agent';
    END IF;
    candidate := base;
    n := 1;
    WHILE EXISTS (SELECT 1 FROM agent_accounts WHERE handle = candidate AND id <> NEW.id) LOOP
        n := n + 1;
        candidate := base || '_' || n;
    END LOOP;
    NEW.handle := candidate;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column("users", sa.Column("handle", sa.Text(), nullable=True))
    op.add_column("agent_accounts", sa.Column("handle", sa.Text(), nullable=True))

    op.execute(_BACKFILL_USERS)
    op.execute(_BACKFILL_AGENTS)

    op.alter_column("users", "handle", nullable=False)
    op.alter_column("agent_accounts", "handle", nullable=False)

    op.create_index(
        "uq_users_handle", "users", ["handle"], unique=True,
    )
    op.create_index(
        "uq_agent_accounts_handle", "agent_accounts", ["handle"], unique=True,
    )

    # Auto-fill triggers — fire BEFORE INSERT to derive handle when NULL.
    op.execute(_USERS_HANDLE_FN)
    op.execute(_AGENTS_HANDLE_FN)
    op.execute(
        "CREATE TRIGGER trg_users_fill_handle BEFORE INSERT ON users "
        "FOR EACH ROW EXECUTE FUNCTION _users_fill_handle();"
    )
    op.execute(
        "CREATE TRIGGER trg_agents_fill_handle BEFORE INSERT ON agent_accounts "
        "FOR EACH ROW EXECUTE FUNCTION _agents_fill_handle();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agents_fill_handle ON agent_accounts;")
    op.execute("DROP TRIGGER IF EXISTS trg_users_fill_handle ON users;")
    op.execute("DROP FUNCTION IF EXISTS _agents_fill_handle();")
    op.execute("DROP FUNCTION IF EXISTS _users_fill_handle();")
    op.drop_index("uq_agent_accounts_handle", table_name="agent_accounts")
    op.drop_index("uq_users_handle", table_name="users")
    op.drop_column("agent_accounts", "handle")
    op.drop_column("users", "handle")
