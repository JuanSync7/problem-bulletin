"""V4a migration round-trip: agent_run table.

upgrade head → downgrade -1 → upgrade head succeeds with no errors.
Verifies the new table + unique index exist after upgrade.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import asyncpg
import pytest


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:28432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)


def _asyncpg_dsn(url: str) -> str:
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


async def _table_exists(name: str) -> bool:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        row = await conn.fetchrow(
            "SELECT to_regclass($1) AS oid", name
        )
    finally:
        await conn.close()
    return row is not None and row["oid"] is not None


async def _index_names(table: str) -> set[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = $1", table
        )
    finally:
        await conn.close()
    return {r["indexname"] for r in rows}


def test_agent_run_upgrade_clean():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"upgrade failed:\n{res.stdout}\n{res.stderr}"


def test_agent_run_roundtrip_idempotent():
    up1 = _alembic("upgrade", "head")
    assert up1.returncode == 0, up1.stderr
    down = _alembic("downgrade", "-1")
    assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"
    up2 = _alembic("upgrade", "head")
    assert up2.returncode == 0, f"re-upgrade failed:\n{up2.stdout}\n{up2.stderr}"


def test_agent_run_table_present_after_upgrade():
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr
    assert asyncio.run(_table_exists("agent_run"))
    idx = asyncio.run(_index_names("agent_run"))
    assert any("idempotency" in n for n in idx), (
        f"expected unique idempotency index on agent_run, got {idx}"
    )
