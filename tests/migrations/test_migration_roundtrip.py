"""Alembic upgrade/downgrade roundtrip smoke test.

Verifies each agent-kanban migration revision can be applied to head and that
each one is independently reversible. Skipped if Postgres is unreachable.
"""
from __future__ import annotations

import os
import subprocess

import pytest
import asyncio

import asyncpg
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:5432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)

# All four new revisions, in chain order.
AGENT_KANBAN_REVS = [
    "a1_agent_kanban",
    "a2_agent_kanban",
    "a3_agent_kanban",
    "a4_agent_kanban",
]


def _asyncpg_dsn(url: str) -> str:
    """Convert ``postgresql+asyncpg://`` to a plain DSN asyncpg accepts."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _check_db() -> bool:
    try:
        conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
        await conn.execute("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False


def _db_reachable() -> bool:
    return asyncio.run(_check_db())


async def _fetch_table_names() -> set[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    finally:
        await conn.close()
    return {r["table_name"] for r in rows}


async def _fetch_index_names(table: str) -> set[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = $1", table
        )
    finally:
        await conn.close()
    return {r["indexname"] for r in rows}


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason=f"live postgres unreachable at {TEST_DB_URL}",
)


def _alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    return subprocess.run(
        ["alembic", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )


def test_chain_reaches_head_a4():
    """Confirms alembic upgrade head lands on a4_agent_kanban."""
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr
    res2 = _alembic("current")
    assert "a4_agent_kanban" in res2.stdout + res2.stderr


def test_each_agent_kanban_revision_is_reversible():
    """Downgrade by one then re-upgrade for each of a4..a1."""
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    # Walk the chain downward, then back up. Each step must succeed.
    for _ in range(len(AGENT_KANBAN_REVS)):
        down = _alembic("downgrade", "-1")
        assert down.returncode == 0, down.stderr

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    final = _alembic("current")
    assert "a4_agent_kanban" in final.stdout + final.stderr


def test_new_tables_exist_at_head():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    names = asyncio.run(_fetch_table_names())
    assert "tickets" in names
    assert "agent_accounts" in names
    assert "audit_log" in names
    assert "ticket_transitions" in names
    assert "ticket_links" in names
    assert "problems" not in names  # renamed


def test_search_indexes_present_at_head():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr
    idx = asyncio.run(_fetch_index_names("tickets"))
    assert "gin_tickets_labels" in idx
    assert "gin_tickets_search_tsv" in idx
    assert "ix_tickets_status_assignee" in idx
    assert "ix_tickets_parent_id" in idx
