"""v2.7-WP51 — Per-event-type audit-log retention policy tests.

Covers ``AUDIT_LOG_RETENTION_OVERRIDES``:

  1. Empty overrides → identical behaviour to WP44 single-cutoff global prune.
  2. Single override → that event uses its own days; others use global.
  3. Multiple overrides → each event uses its own days; non-overridden use global.
  4. Validator clamps invalid values (0 → 1, 99999 → 3650).
  5. Validator rejects malformed JSON env.

Requires live Postgres via ``PB_TEST_DATABASE_URL`` (skipped otherwise via
the shared ``pg_engine`` fixture).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError
from sqlalchemy import text

from app.config import Settings, get_settings
from app.services.audit_log_retention import GLOBAL_BUCKET, prune_once


# ---------------------------------------------------------------------------
# Helpers (mirror WP44 helpers; kept local to avoid coupling test files)
# ---------------------------------------------------------------------------


async def _insert_audit_row(
    session, *, event: str, created_at: datetime
) -> uuid.UUID:
    """Insert an activity_audit_log row with a controllable ``created_at``."""
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
    """Return True iff the given audit-log row still exists post-prune."""
    res = await session.execute(
        text("SELECT 1 FROM activity_audit_log WHERE id = :id"),
        {"id": row_id},
    )
    return res.scalar() is not None


async def _delete_rows(session, ids: list[uuid.UUID]) -> None:
    """Remove test-inserted rows so state never leaks between tests."""
    if not ids:
        return
    for rid in ids:
        await session.execute(
            text("DELETE FROM activity_audit_log WHERE id = :id"),
            {"id": rid},
        )
    await session.commit()


# ---------------------------------------------------------------------------
# Patched-settings fixture (extended over WP44 to include OVERRIDES)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_settings(monkeypatch):
    """Mutable settings proxy for the retention module — extends WP44 with
    ``AUDIT_LOG_RETENTION_OVERRIDES``."""
    base = get_settings()

    class _Proxy:
        def __init__(self):
            self.AUDIT_LOG_RETENTION_ENABLED = True
            self.AUDIT_LOG_RETENTION_DAYS = 365
            self.AUDIT_LOG_RETENTION_OVERRIDES: dict[str, int] = {}

        def __getattr__(self, item):
            return getattr(base, item)

    cfg = _Proxy()
    from app.services import audit_log_retention as mod

    monkeypatch.setattr(mod, "get_settings", lambda: cfg)
    return cfg


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_overrides_matches_wp44_global_prune(
    session_factory, patched_settings
):
    """Empty overrides → global cutoff applies to every event type (WP44 parity)."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30
    patched_settings.AUDIT_LOG_RETENTION_OVERRIDES = {}

    inserted: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(days=60)  # past 30d global cutoff
    new_ts = now - timedelta(days=5)   # within 30d cutoff

    async with session_factory() as setup:
        old_a = await _insert_audit_row(setup, event="wp51.empty.a", created_at=old_ts)
        old_b = await _insert_audit_row(setup, event="wp51.empty.b", created_at=old_ts)
        new_a = await _insert_audit_row(setup, event="wp51.empty.a", created_at=new_ts)
        await setup.commit()
        inserted.extend([old_a, old_b, new_a])

    try:
        async with session_factory() as session:
            result = await prune_once(session)
            # PruneResult is int-coercible; per_event has a single global bucket.
            assert int(result) >= 2
            assert GLOBAL_BUCKET in result.per_event
            # No override buckets present when overrides is empty.
            assert set(result.per_event.keys()) == {GLOBAL_BUCKET}

        async with session_factory() as check:
            assert not await _row_exists(check, old_a)
            assert not await _row_exists(check, old_b)
            assert await _row_exists(check, new_a)
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_single_override_uses_own_days_others_use_global(
    session_factory, patched_settings
):
    """One override event_type ages out at its own days; others use global."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 365
    patched_settings.AUDIT_LOG_RETENTION_OVERRIDES = {"wp51.single.fast": 7}

    inserted: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)

    # 'fast' event: 14d old → past 7d override cutoff → DELETE
    fast_old_ts = now - timedelta(days=14)
    # 'fast' event: 3d old → within 7d → KEEP
    fast_new_ts = now - timedelta(days=3)
    # 'slow' event: 90d old → within 365d global → KEEP
    slow_within_global_ts = now - timedelta(days=90)
    # 'slow' event: 400d old → past 365d global → DELETE
    slow_past_global_ts = now - timedelta(days=400)

    async with session_factory() as setup:
        fast_old = await _insert_audit_row(
            setup, event="wp51.single.fast", created_at=fast_old_ts
        )
        fast_new = await _insert_audit_row(
            setup, event="wp51.single.fast", created_at=fast_new_ts
        )
        slow_keep = await _insert_audit_row(
            setup, event="wp51.single.slow", created_at=slow_within_global_ts
        )
        slow_del = await _insert_audit_row(
            setup, event="wp51.single.slow", created_at=slow_past_global_ts
        )
        await setup.commit()
        inserted.extend([fast_old, fast_new, slow_keep, slow_del])

    try:
        async with session_factory() as session:
            result = await prune_once(session)
            assert "wp51.single.fast" in result.per_event
            assert GLOBAL_BUCKET in result.per_event
            assert result.per_event["wp51.single.fast"] >= 1
            assert result.per_event[GLOBAL_BUCKET] >= 1

        async with session_factory() as check:
            assert not await _row_exists(check, fast_old), "14d-old fast row past 7d override"
            assert await _row_exists(check, fast_new), "3d-old fast row within 7d override"
            assert await _row_exists(check, slow_keep), "90d-old slow row within 365d global"
            assert not await _row_exists(check, slow_del), "400d-old slow row past 365d global"
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_multiple_overrides_each_uses_own_days(
    session_factory, patched_settings
):
    """Multiple overrides → each event type ages out at its own cutoff."""
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 365
    patched_settings.AUDIT_LOG_RETENTION_OVERRIDES = {
        "wp51.multi.short": 7,
        "wp51.multi.mid": 30,
    }

    inserted: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)

    # short: 10d > 7d cutoff → DELETE
    short_old = now - timedelta(days=10)
    # short: 3d < 7d cutoff → KEEP
    short_new = now - timedelta(days=3)
    # mid: 60d > 30d cutoff → DELETE
    mid_old = now - timedelta(days=60)
    # mid: 15d < 30d cutoff → KEEP
    mid_new = now - timedelta(days=15)
    # other: 60d < 365d global → KEEP (would have been DELETED if grouped with mid)
    other_keep = now - timedelta(days=60)

    async with session_factory() as setup:
        short_d = await _insert_audit_row(
            setup, event="wp51.multi.short", created_at=short_old
        )
        short_k = await _insert_audit_row(
            setup, event="wp51.multi.short", created_at=short_new
        )
        mid_d = await _insert_audit_row(
            setup, event="wp51.multi.mid", created_at=mid_old
        )
        mid_k = await _insert_audit_row(
            setup, event="wp51.multi.mid", created_at=mid_new
        )
        other_k = await _insert_audit_row(
            setup, event="wp51.multi.other", created_at=other_keep
        )
        await setup.commit()
        inserted.extend([short_d, short_k, mid_d, mid_k, other_k])

    try:
        async with session_factory() as session:
            result = await prune_once(session)
            assert result.per_event.get("wp51.multi.short", 0) >= 1
            assert result.per_event.get("wp51.multi.mid", 0) >= 1
            # Each override has its own bucket key.
            assert "wp51.multi.short" in result.per_event
            assert "wp51.multi.mid" in result.per_event
            assert GLOBAL_BUCKET in result.per_event

        async with session_factory() as check:
            assert not await _row_exists(check, short_d)
            assert await _row_exists(check, short_k)
            assert not await _row_exists(check, mid_d)
            assert await _row_exists(check, mid_k)
            # The unrelated event_type uses global 365d → preserved.
            assert await _row_exists(check, other_k)
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


def test_validator_clamps_invalid_override_values(monkeypatch):
    """Validator clamps out-of-range override values to [1, 3650]."""
    monkeypatch.setenv(
        "AUDIT_LOG_RETENTION_OVERRIDES",
        '{"too.small": 0, "too.big": 99999, "ok": 90}',
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    s = Settings()
    assert s.AUDIT_LOG_RETENTION_OVERRIDES["too.small"] == 1
    assert s.AUDIT_LOG_RETENTION_OVERRIDES["too.big"] == 3650
    assert s.AUDIT_LOG_RETENTION_OVERRIDES["ok"] == 90


def test_validator_rejects_malformed_json(monkeypatch):
    """Malformed JSON in env → settings construction fails loudly.

    pydantic-settings JSON-decodes complex (dict-typed) env values before
    handing them to our ``mode='before'`` field_validator, so the error
    surfaces as ``SettingsError`` (wrapping ``JSONDecodeError``) rather than
    our own ``ValueError``-derived ``ValidationError``. Either is acceptable
    — the contract is "do not silently fall back".
    """
    monkeypatch.setenv("AUDIT_LOG_RETENTION_OVERRIDES", "not-a-json{")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    with pytest.raises((ValidationError, SettingsError)):
        Settings()
