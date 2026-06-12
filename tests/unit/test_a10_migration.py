"""Live-DB smoke checks for the ``a10_ticket_last_actor`` migration.

Skipped when Postgres is unreachable. Assumes the migration has already
been applied at HEAD (matches the style of
``test_ticketing_v2_migration.py``).
"""
from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:28432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(_dsn(TEST_DB_URL))


async def _check_db() -> bool:
    try:
        c = await _connect()
        await c.execute("SELECT 1")
        await c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not asyncio.run(_check_db()),
    reason=f"live postgres unreachable at {TEST_DB_URL}",
)


async def _scalar(sql: str):
    conn = await _connect()
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


async def _fetch(sql: str):
    conn = await _connect()
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


def test_tickets_has_last_actor_columns():
    rows = asyncio.run(
        _fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tickets'"
        )
    )
    cols = {r["column_name"] for r in rows}
    for c in (
        "last_actor_type",
        "last_actor_id",
        "last_activity_at",
        "last_agent_step_id",
    ):
        assert c in cols, f"missing tickets.{c}"


def test_ix_tickets_last_activity_at_exists():
    """Backfill sort-index is present."""
    count = asyncio.run(
        _scalar(
            "SELECT count(*) FROM pg_indexes "
            "WHERE tablename = 'tickets' AND indexname = 'ix_tickets_last_activity_at'"
        )
    )
    assert count == 1


def test_last_actor_check_constraints_present():
    rows = asyncio.run(
        _fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'tickets'::regclass"
        )
    )
    names = {r["conname"] for r in rows}
    assert "ck_tickets_last_actor_type" in names
    assert "ck_tickets_last_agent_step_id" in names


def test_backfill_sets_last_actor_for_every_ticket():
    """Every existing row gets a non-null last_actor_type / last_activity_at."""
    bad = asyncio.run(
        _scalar(
            "SELECT count(*) FROM tickets "
            "WHERE last_actor_type IS NULL OR last_activity_at IS NULL"
        )
    )
    assert bad == 0


def test_backfill_matches_latest_transition_or_comment_or_reporter():
    """For rows with at least one transition/comment, last_actor_type
    equals the actor_type of the most recent of the two; otherwise it
    equals reporter_type."""
    mismatch = asyncio.run(
        _scalar(
            """
            WITH activity AS (
                SELECT ticket_id, created_at,
                       actor_type AS actor_type
                  FROM ticket_transitions
                UNION ALL
                SELECT ticket_id, created_at,
                       author_type AS actor_type
                  FROM ticket_comments
            ),
            latest AS (
                SELECT DISTINCT ON (ticket_id) ticket_id, actor_type
                  FROM activity
                 ORDER BY ticket_id, created_at DESC
            )
            SELECT count(*) FROM tickets t
              LEFT JOIN latest l ON l.ticket_id = t.id
             WHERE
               (l.actor_type IS NOT NULL AND t.last_actor_type <> l.actor_type)
               OR (l.actor_type IS NULL
                   AND t.last_actor_type <> t.reporter_type)
            """
        )
    )
    assert mismatch == 0
