"""Shared async-DB fixtures for agent-kanban service-layer tests.

These tests require a live Postgres reachable at ``PB_TEST_DATABASE_URL``
(default: the dev container URL). When unreachable, tests using these
fixtures are skipped at the function fixture level so unit-only runs are
unaffected.

The fixtures NEVER commit. Each test runs inside a single rollback'd
transaction so state never leaks. Where a test needs to observe what would
be committed (e.g. cross-task race tests), we use ``session.flush()`` and
read back within the same TX.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.enums import ActorType
from app.services.context import Actor


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:5432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)


@pytest_asyncio.fixture
async def pg_engine():
    """Module-ish engine; created per-test to keep teardown simple."""
    eng = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (OperationalError, ConnectionRefusedError, OSError) as exc:
        await eng.dispose()
        pytest.skip(f"live postgres not reachable at {TEST_DB_URL}: {exc}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(pg_engine) -> AsyncSession:
    """Single function-scoped session, rolled back on teardown."""
    SessionLocal = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def session_factory(pg_engine):
    """Yield an async_sessionmaker for tests that need parallel sessions
    (claim race, transition race)."""
    yield async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest.fixture
def user_actor() -> Actor:
    return Actor(
        id=uuid.uuid4(),
        type=ActorType.user,
        label="alice@example.com",
        scopes=(),
    )


@pytest.fixture
def agent_actor() -> Actor:
    return Actor(
        id=uuid.uuid4(),
        type=ActorType.agent,
        label="claude-bot",
        scopes=("tickets:read", "tickets:write"),
    )
