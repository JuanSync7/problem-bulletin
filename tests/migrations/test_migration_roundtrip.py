"""Alembic upgrade/downgrade roundtrip smoke test.

Verifies each agent-kanban migration revision can be applied to head and that
each one is independently reversible. Skipped if Postgres is unreachable.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
import asyncio

import asyncpg
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:28432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)

# All agent-kanban revisions plus the Step 1/3 renames, in chain order.
AGENT_KANBAN_REVS = [
    "a1_agent_kanban",
    "a2_agent_kanban",
    "a3_agent_kanban",
    "a4_agent_kanban",
    "a5_agent_kanban",
    "a6_rename_tickets_to_problems",
    "a7_create_work_items",
    "a8_finalize_ticket_split",
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
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )


def _current_head_revision() -> str:
    """Return the actual head revision id reported by ``alembic heads``.

    The roundtrip suite was originally pinned to ``a8_finalize_ticket_split``
    (the last agent-kanban rev at v2.10 inception). The chain has since
    extended (a9..a18+); rather than relock on every new revision, ask
    alembic for its current head.
    """
    res = _alembic("heads")
    assert res.returncode == 0, res.stderr
    # Output looks like "a18_project_coalesce_seconds (head)\n"
    out = (res.stdout or "").strip().splitlines()
    assert out, f"alembic heads returned no output: {res.stdout!r} {res.stderr!r}"
    return out[0].split()[0]


def test_chain_reaches_head_rename():
    """Confirms alembic upgrade head lands on the live head revision."""
    head = _current_head_revision()
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr
    res2 = _alembic("current")
    assert head in res2.stdout + res2.stderr


def test_each_agent_kanban_revision_is_reversible():
    """Walk the whole chain down to base then back up to head.

    Confirms every revision (including each agent-kanban a1..a8 plus the
    later additions) is independently reversible. Originally only counted
    ``len(AGENT_KANBAN_REVS)`` downgrade steps, which left later revs above
    a8 unwalked and therefore did not exercise a1..a8 at all once the chain
    grew past a8.
    """
    head = _current_head_revision()
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    final = _alembic("current")
    assert head in final.stdout + final.stderr


def test_new_tables_exist_at_head():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    names = asyncio.run(_fetch_table_names())
    assert "problems" in names  # bulletin table
    assert "agent_accounts" in names
    assert "audit_log" in names
    # Step 3: work_items renamed to tickets; legacy ticket_* tables are
    # gone and the work_item_* tables took their names.
    assert "tickets" in names
    assert "ticket_comments" in names
    assert "ticket_transitions" in names
    assert "ticket_links" in names
    assert "work_items" not in names


def test_search_indexes_present_at_head():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr
    idx = asyncio.run(_fetch_index_names("tickets"))
    assert "gin_tickets_labels" in idx
    assert "gin_tickets_search_tsv" in idx
    assert "ix_tickets_status_assignee" in idx
    assert "ix_tickets_parent_id" in idx
