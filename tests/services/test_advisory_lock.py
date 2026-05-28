"""v2.7-WP46 — Tests for the shared ``with_advisory_lock`` helper.

Requires a live Postgres reachable via ``PB_TEST_DATABASE_URL`` (skipped
otherwise via the shared ``pg_engine`` fixture in
``tests/services/conftest.py``).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services._advisory import advisory_lock_key, with_advisory_lock


@pytest.mark.asyncio
async def test_key_is_deterministic_and_in_range():
    """Same ``key_str`` yields the same 63-bit positive bigint key."""
    a = advisory_lock_key("wp46.test.deterministic")
    b = advisory_lock_key("wp46.test.deterministic")
    assert a == b
    assert 0 <= a <= 0x7FFFFFFFFFFFFFFF
    # Different inputs hash to (almost certainly) distinct keys.
    assert advisory_lock_key("wp46.test.a") != advisory_lock_key("wp46.test.b")


@pytest.mark.asyncio
async def test_acquires_and_yields_true(session_factory):
    """When the lock is free, the manager yields True and releases on exit."""
    key_str = "wp46.test.acquire"
    async with session_factory() as session:
        async with with_advisory_lock(session, key_str) as acquired:
            assert acquired is True


@pytest.mark.asyncio
async def test_contention_yields_false(session_factory):
    """If another session holds the lock, the helper yields False (no raise)."""
    key_str = "wp46.test.contention"
    key = advisory_lock_key(key_str)

    async with session_factory() as holder:
        got = (
            await holder.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            )
        ).scalar()
        assert got is True, "holder must acquire first"

        try:
            async with session_factory() as session:
                async with with_advisory_lock(session, key_str) as acquired:
                    assert acquired is False
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": key}
            )


@pytest.mark.asyncio
async def test_releases_on_normal_exit(session_factory):
    """After the ``async with`` body, the lock is released — a fresh session
    can immediately re-acquire it."""
    key_str = "wp46.test.release"
    async with session_factory() as first:
        async with with_advisory_lock(first, key_str) as acquired:
            assert acquired is True
        # After exit, a separate session must be able to acquire.
        async with session_factory() as second:
            async with with_advisory_lock(second, key_str) as reacquired:
                assert reacquired is True


@pytest.mark.asyncio
async def test_releases_on_exception(session_factory):
    """Exceptions inside the body must still release the lock."""
    key_str = "wp46.test.exception"

    class _Boom(Exception):
        pass

    async with session_factory() as first:
        with pytest.raises(_Boom):
            async with with_advisory_lock(first, key_str) as acquired:
                assert acquired is True
                raise _Boom("body failed")

        # Lock must be free again — re-acquire from a fresh session.
        async with session_factory() as second:
            async with with_advisory_lock(second, key_str) as reacquired:
                assert reacquired is True


@pytest.mark.asyncio
async def test_no_unlock_when_not_acquired(session_factory):
    """When yielding False (contention), exiting the manager must NOT issue
    an unlock that would steal the holder's lock."""
    key_str = "wp46.test.no_unlock_on_false"
    key = advisory_lock_key(key_str)

    async with session_factory() as holder:
        got = (
            await holder.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            )
        ).scalar()
        assert got is True

        try:
            async with session_factory() as session:
                async with with_advisory_lock(session, key_str) as acquired:
                    assert acquired is False
                # Holder must still own the lock; a third session must see
                # contention.
                async with session_factory() as third:
                    third_got = (
                        await third.execute(
                            text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": key},
                        )
                    ).scalar()
                    assert third_got is False, (
                        "false-yield must not have released the holder's lock"
                    )
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": key}
            )
