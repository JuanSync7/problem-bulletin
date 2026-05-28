"""Shared Postgres advisory-lock context manager — v2.7-WP46.

Extracted from the duplicated ``pg_try_advisory_lock`` idiom used by
``due_soon_scanner`` (WP39) and ``audit_log_retention`` (WP44).

Design
------
* Session-scoped advisory lock: ``pg_try_advisory_lock(key)`` is non-blocking
  and returns ``true`` if the lock was acquired on the current backend
  connection. Each async SQLAlchemy ``AsyncSession`` binds to a single
  connection for its lifetime, so the matching ``pg_advisory_unlock(key)``
  pairs correctly when issued on the same session.
* On contention (lock unavailable) the context manager yields ``False`` — it
  does NOT raise. Callers must check the yielded value and short-circuit.
* Release is in ``finally`` and runs ONLY if acquisition succeeded; unlock
  failures are caught and logged, since the lock will be released
  automatically when the connection closes.

Key derivation
~~~~~~~~~~~~~~
The key is a 63-bit positive bigint derived from MD5 of the supplied
``key_str``. Deterministic across processes; collision-resistant for the
small set of advisory keys this app uses. The formula matches the inline
code being replaced byte-for-byte so existing in-flight locks remain
compatible across the refactor.
"""
from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def advisory_lock_key(key_str: str) -> int:
    """Return the 63-bit positive bigint advisory-lock key for ``key_str``.

    Stable across processes and matches the legacy inline derivation in
    ``due_soon_scanner`` / ``audit_log_retention``.
    """
    digest = hashlib.md5(key_str.encode()).digest()
    raw = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return raw & 0x7FFFFFFFFFFFFFFF


@asynccontextmanager
async def with_advisory_lock(
    session: AsyncSession, key_str: str
) -> AsyncIterator[bool]:
    """Acquire a session-scoped Postgres advisory lock, non-blocking.

    Yields ``True`` if acquired (caller should proceed), ``False`` if another
    backend holds the lock (caller should short-circuit). Never raises on
    contention. The matching unlock is issued in ``finally`` only when the
    lock was acquired; unlock failures are logged but non-fatal.
    """
    key = advisory_lock_key(key_str)
    locked_row = await session.execute(
        text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
    )
    acquired = bool(locked_row.scalar())
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": key}
                )
            except Exception:
                # Non-fatal: session-scoped locks release on connection close.
                logger.exception(
                    "with_advisory_lock(%s): pg_advisory_unlock failed (non-fatal)",
                    key_str,
                )
