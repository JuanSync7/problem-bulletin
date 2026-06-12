"""A2a migration idempotency test.

Verifies:
  1. upgrade head is clean (includes pg_trgm extension + GIN indexes)
  2. downgrade base then upgrade head is clean (idempotent roundtrip)
  3. The pg_trgm extension is present after upgrade
  4. The expected GIN trigram indexes exist after upgrade

Pattern mirrors tests/migrations/test_migration_roundtrip.py (v2.10-WP06).
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


async def _fetch_extension_names() -> set[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        rows = await conn.fetch(
            "SELECT extname FROM pg_extension"
        )
    finally:
        await conn.close()
    return {r["extname"] for r in rows}


async def _fetch_index_names(table: str) -> set[str]:
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DB_URL))
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = $1", table
        )
    finally:
        await conn.close()
    return {r["indexname"] for r in rows}


def test_pg_trgm_upgrade_is_clean():
    """alembic upgrade head succeeds and ends at the expected revision."""
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"upgrade failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_pg_trgm_downgrade_upgrade_roundtrip():
    """downgrade base then upgrade head is idempotent — no errors."""
    up1 = _alembic("upgrade", "head")
    assert up1.returncode == 0, f"initial upgrade failed: {up1.stderr}"

    down = _alembic("downgrade", "base")
    assert down.returncode == 0, f"downgrade failed:\nSTDOUT: {down.stdout}\nSTDERR: {down.stderr}"

    up2 = _alembic("upgrade", "head")
    assert up2.returncode == 0, f"re-upgrade failed:\nSTDOUT: {up2.stdout}\nSTDERR: {up2.stderr}"


def test_pg_trgm_extension_present_after_upgrade():
    """pg_trgm extension is registered after upgrade head."""
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    extensions = asyncio.run(_fetch_extension_names())
    assert "pg_trgm" in extensions, (
        f"pg_trgm extension not found after upgrade. Present extensions: {extensions}"
    )


def test_gin_trgm_indexes_present_after_upgrade():
    """GIN trigram indexes exist on tickets, problems, components, labels, users."""
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, res.stderr

    # Check each table has a trgm index
    expected = {
        "tickets": "gin_tickets_title_trgm",
        "problems": "gin_problems_title_trgm",
        "components": "gin_components_name_trgm",
        "tags": "gin_tags_name_trgm",
        "users": "gin_users_handle_trgm",
    }
    for table, index_name in expected.items():
        idx = asyncio.run(_fetch_index_names(table))
        assert index_name in idx, (
            f"Expected GIN trgm index {index_name!r} on {table!r} not found. "
            f"Present indexes: {idx}"
        )
