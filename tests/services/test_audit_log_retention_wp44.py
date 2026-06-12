"""v2.6-WP44 — Tests for ``audit_log_retention.prune_once`` / ``run_loop``.

Requires a live Postgres reachable via ``PB_TEST_DATABASE_URL`` (skipped
otherwise via the shared ``pg_engine`` fixture in ``tests/services/conftest.py``).

Because ``prune_once`` issues its own ``session.commit()``, these tests use
``session_factory`` to manufacture sessions independent of the ``db``
rollback fixture, and clean up inserted rows in a finally-block.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.services.audit_log_retention import _LOCK_KEY, prune_once, run_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_audit_row(session, *, event: str, created_at: datetime) -> uuid.UUID:
    row_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO activity_audit_log "
            "(id, event, actor_user_id, target_type, target_id, metadata, created_at) "
            "VALUES (:id, :ev, NULL, NULL, NULL, '{}'::jsonb, :ts)"
        ),
        {"id": row_id, "ev": event, "ts": created_at},
    )
    return row_id


async def _row_exists(session, row_id: uuid.UUID) -> bool:
    res = await session.execute(
        text("SELECT 1 FROM activity_audit_log WHERE id = :id"),
        {"id": row_id},
    )
    return res.scalar() is not None


async def _delete_rows(session, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    for rid in ids:
        await session.execute(
            text("DELETE FROM activity_audit_log WHERE id = :id"),
            {"id": rid},
        )
    await session.commit()


# ---------------------------------------------------------------------------
# Settings override helper
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_settings(monkeypatch):
    """Patch ``get_settings`` in the retention module to return a controllable
    Settings instance. Returns the (mutable) Settings — tests mutate fields
    before calling prune_once.
    """
    # Snapshot the real settings, then expose a mutable proxy whose attrs
    # the tests can change without affecting other tests.
    base = get_settings()

    class _Proxy:
        def __init__(self):
            self.AUDIT_LOG_RETENTION_ENABLED = True
            self.AUDIT_LOG_RETENTION_DAYS = 365

        def __getattr__(self, item):
            # Fallback to real settings for any field we haven't overridden.
            return getattr(base, item)

    cfg = _Proxy()

    from app.services import audit_log_retention as mod

    monkeypatch.setattr(mod, "get_settings", lambda: cfg)
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_deletes_old_preserves_new(session_factory, patched_settings):
    """Rows older than retention cutoff are deleted; newer rows preserved."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30

    inserted: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(days=60)   # well past 30d cutoff
    new_ts = now - timedelta(days=5)    # within cutoff

    async with session_factory() as setup:
        old_id = await _insert_audit_row(setup, event="wp44.test.old", created_at=old_ts)
        new_id = await _insert_audit_row(setup, event="wp44.test.new", created_at=new_ts)
        await setup.commit()
        inserted.extend([old_id, new_id])

    try:
        async with session_factory() as session:
            deleted = await prune_once(session)
            assert deleted >= 1

        async with session_factory() as check:
            assert not await _row_exists(check, old_id), "old row should be deleted"
            assert await _row_exists(check, new_id), "new row must be preserved"
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_prune_returns_exact_deleted_count(session_factory, patched_settings):
    """``prune_once`` returns the exact number of rows it deleted."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30

    # First, baseline: prune anything already old in the DB so our delta is
    # measurable.
    async with session_factory() as warm:
        await prune_once(warm)

    inserted: list[uuid.UUID] = []
    old_ts = datetime.now(timezone.utc) - timedelta(days=90)
    n = 3
    async with session_factory() as setup:
        for i in range(n):
            rid = await _insert_audit_row(
                setup, event=f"wp44.test.count.{i}", created_at=old_ts
            )
            inserted.append(rid)
        await setup.commit()

    try:
        async with session_factory() as session:
            deleted = await prune_once(session)
            assert deleted == n, f"expected {n} deletions, got {deleted}"
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_prune_returns_zero_under_lock_contention(
    session_factory, patched_settings
):
    """When another session holds the prune lock, ``prune_once`` returns 0
    and leaves rows intact."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30

    inserted: list[uuid.UUID] = []
    old_ts = datetime.now(timezone.utc) - timedelta(days=90)

    async with session_factory() as setup:
        rid = await _insert_audit_row(
            setup, event="wp44.test.contention", created_at=old_ts
        )
        await setup.commit()
        inserted.append(rid)

    try:
        async with session_factory() as holder:
            got = (
                await holder.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
                )
            ).scalar()
            assert got is True, "holder session must acquire lock first"

            try:
                async with session_factory() as session:
                    deleted = await prune_once(session)
                    assert deleted == 0, "must short-circuit under contention"

                async with session_factory() as check:
                    assert await _row_exists(check, rid), (
                        "row must NOT be deleted while another worker holds lock"
                    )
            finally:
                await holder.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY}
                )
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_disabled_setting_makes_prune_a_noop(session_factory, patched_settings):
    """``AUDIT_LOG_RETENTION_ENABLED=False`` → ``prune_once`` is a no-op and
    ``run_loop`` exits immediately without scanning."""
    patched_settings.AUDIT_LOG_RETENTION_ENABLED = False
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30

    inserted: list[uuid.UUID] = []
    old_ts = datetime.now(timezone.utc) - timedelta(days=90)
    async with session_factory() as setup:
        rid = await _insert_audit_row(
            setup, event="wp44.test.disabled", created_at=old_ts
        )
        await setup.commit()
        inserted.append(rid)

    try:
        # prune_once is a no-op when disabled.
        async with session_factory() as session:
            deleted = await prune_once(session)
            assert deleted == 0

        async with session_factory() as check:
            assert await _row_exists(check, rid), (
                "row must be preserved when retention is disabled"
            )

        # run_loop exits immediately (does not block) when disabled.
        import asyncio
        await asyncio.wait_for(run_loop(session_factory), timeout=1.0)
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)
