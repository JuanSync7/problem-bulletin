"""v2.7-WP52 — Cold-storage archival for audit_log retention.

Covers ``audit_log_archive.archive_then_prune`` and the
``audit_log_retention.prune_once`` branch that routes through it.

  1. Happy path — rows past cutoff are written to JSONL and deleted.
  2. File is created at the expected ``{event}-{UTC date}.jsonl`` path.
  3. JSONL line round-trips back to the original row data.
  4. File-write failure aborts deletion — rows survive.
  5. Master switch OFF → archiver not invoked; WP51 plain-prune path used.
  6. Batch boundary — rows greater than batch_size still all archived + deleted.

Requires live Postgres via ``PB_TEST_DATABASE_URL`` (skipped otherwise via
the shared ``pg_engine`` fixture).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.services import audit_log_archive
from app.services.audit_log_archive import (
    _archive_path,
    archive_then_prune,
)
from app.services.audit_log_retention import GLOBAL_BUCKET, prune_once


# ---------------------------------------------------------------------------
# Helpers (local copies — keep WP52 tests independent of WP51 imports)
# ---------------------------------------------------------------------------


async def _insert_audit_row(
    session,
    *,
    event: str,
    created_at: datetime,
    metadata: dict | None = None,
) -> uuid.UUID:
    """Insert one ``activity_audit_log`` row with a controllable
    ``created_at`` and JSONB ``metadata`` payload."""
    row_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO activity_audit_log "
            "(id, event, actor_user_id, target_type, target_id, metadata, created_at) "
            "VALUES (:id, :ev, NULL, NULL, NULL, CAST(:md AS jsonb), :ts)"
        ),
        {
            "id": row_id,
            "ev": event,
            "md": json.dumps(metadata or {}),
            "ts": created_at,
        },
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
# Patched-settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_settings(monkeypatch, tmp_path):
    """Mutable settings proxy used by *both* the archiver and the retention
    module — sets archive on by default with ``tmp_path`` as the dir.
    """
    base = get_settings()

    class _Proxy:
        def __init__(self):
            self.AUDIT_LOG_RETENTION_ENABLED = True
            self.AUDIT_LOG_RETENTION_DAYS = 365
            self.AUDIT_LOG_RETENTION_OVERRIDES: dict[str, int] = {}
            self.AUDIT_LOG_ARCHIVE_ENABLED = True
            self.AUDIT_LOG_ARCHIVE_DIR = str(tmp_path)
            self.AUDIT_LOG_ARCHIVE_BATCH_SIZE = 1000

        def __getattr__(self, item):
            return getattr(base, item)

    cfg = _Proxy()
    from app.services import audit_log_retention as ret_mod

    monkeypatch.setattr(ret_mod, "get_settings", lambda: cfg)
    monkeypatch.setattr(audit_log_archive, "get_settings", lambda: cfg)
    return cfg


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_rows_written_and_deleted(
    session_factory, patched_settings, tmp_path
):
    """Past-cutoff rows land in the JSONL file AND are deleted from the
    table; within-cutoff rows are untouched."""
    inserted: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=400)
    new = now - timedelta(days=10)

    async with session_factory() as setup:
        old_a = await _insert_audit_row(
            setup, event="wp52.happy", created_at=old, metadata={"x": 1}
        )
        old_b = await _insert_audit_row(
            setup, event="wp52.happy", created_at=old, metadata={"x": 2}
        )
        keep = await _insert_audit_row(
            setup, event="wp52.happy", created_at=new
        )
        await setup.commit()
        inserted.extend([old_a, old_b, keep])

    try:
        async with session_factory() as session:
            archived, deleted = await archive_then_prune(
                session, "wp52.happy", 365
            )
            assert archived >= 2
            assert deleted >= 2

        async with session_factory() as check:
            assert not await _row_exists(check, old_a)
            assert not await _row_exists(check, old_b)
            assert await _row_exists(check, keep)

        # File should exist.
        path = _archive_path(str(tmp_path), "wp52.happy")
        assert os.path.exists(path)
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_archive_path_naming(session_factory, patched_settings, tmp_path):
    """File path matches ``{event}-{UTC YYYY-MM-DD}.jsonl`` exactly."""
    inserted: list[uuid.UUID] = []
    old = datetime.now(timezone.utc) - timedelta(days=400)

    async with session_factory() as setup:
        rid = await _insert_audit_row(
            setup, event="wp52.naming", created_at=old
        )
        await setup.commit()
        inserted.append(rid)

    try:
        async with session_factory() as session:
            await archive_then_prune(session, "wp52.naming", 365)

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        expected = os.path.join(str(tmp_path), f"wp52.naming-{date}.jsonl")
        assert os.path.exists(expected), (
            f"expected archive file at {expected}; tmp_path contents: "
            f"{os.listdir(tmp_path)}"
        )
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_jsonl_line_round_trips(session_factory, patched_settings, tmp_path):
    """JSONL line parses back to the original row's event + metadata."""
    inserted: list[uuid.UUID] = []
    old = datetime.now(timezone.utc) - timedelta(days=400)
    payload = {"reason": "soc2-test", "count": 7}

    async with session_factory() as setup:
        rid = await _insert_audit_row(
            setup,
            event="wp52.roundtrip",
            created_at=old,
            metadata=payload,
        )
        await setup.commit()
        inserted.append(rid)

    try:
        async with session_factory() as session:
            await archive_then_prune(session, "wp52.roundtrip", 365)

        path = _archive_path(str(tmp_path), "wp52.roundtrip")
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        # Find our specific row by id (file is append-only across runs).
        matches = [
            json.loads(ln) for ln in lines if json.loads(ln)["id"] == str(rid)
        ]
        assert len(matches) == 1
        rec = matches[0]
        assert rec["event"] == "wp52.roundtrip"
        # JSONB → dict round-trip.
        assert rec["metadata"] == payload
        # ISO-formatted timestamp survives.
        assert isinstance(rec["created_at"], str) and "T" in rec["created_at"]
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_file_write_failure_aborts_deletion(
    session_factory, patched_settings, monkeypatch
):
    """If the JSONL append raises, no rows are deleted. Safety invariant."""
    inserted: list[uuid.UUID] = []
    old = datetime.now(timezone.utc) - timedelta(days=400)

    async with session_factory() as setup:
        rid_a = await _insert_audit_row(
            setup, event="wp52.fail", created_at=old
        )
        rid_b = await _insert_audit_row(
            setup, event="wp52.fail", created_at=old
        )
        await setup.commit()
        inserted.extend([rid_a, rid_b])

    def _boom(path, lines):
        raise OSError("disk on fire")

    monkeypatch.setattr(audit_log_archive, "_append_lines_sync", _boom)

    try:
        async with session_factory() as session:
            with pytest.raises(OSError, match="disk on fire"):
                await archive_then_prune(session, "wp52.fail", 365)

        # Both rows still present — never DELETE without a successful write.
        async with session_factory() as check:
            assert await _row_exists(check, rid_a)
            assert await _row_exists(check, rid_b)
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_disabled_flag_uses_plain_prune(
    session_factory, patched_settings, tmp_path, monkeypatch
):
    """With AUDIT_LOG_ARCHIVE_ENABLED=False, prune_once goes through the
    WP51 plain-DELETE path — archiver is never invoked and no file is
    written."""
    patched_settings.AUDIT_LOG_ARCHIVE_ENABLED = False
    patched_settings.AUDIT_LOG_RETENTION_DAYS = 30
    patched_settings.AUDIT_LOG_RETENTION_OVERRIDES = {}

    # Sentinel: if anything calls archive_then_prune, fail the test loudly.
    def _fail(*args, **kwargs):
        raise AssertionError("archive_then_prune was called with flag OFF")

    monkeypatch.setattr(
        audit_log_archive, "archive_then_prune", _fail
    )

    inserted: list[uuid.UUID] = []
    old = datetime.now(timezone.utc) - timedelta(days=60)

    async with session_factory() as setup:
        rid = await _insert_audit_row(
            setup, event="wp52.disabled", created_at=old
        )
        await setup.commit()
        inserted.append(rid)

    try:
        async with session_factory() as session:
            result = await prune_once(session)
            # PruneResult carries per_event_archived but it's empty on the
            # disabled path.
            assert result.per_event_archived == {}
            assert int(result) >= 1

        async with session_factory() as check:
            assert not await _row_exists(check, rid)

        # No JSONL file was created.
        assert os.listdir(tmp_path) == [], (
            f"unexpected archive files: {os.listdir(tmp_path)}"
        )
    finally:
        async with session_factory() as cleanup:
            await _delete_rows(cleanup, inserted)


@pytest.mark.asyncio
async def test_batch_boundary_archives_all_rows(
    session_factory, patched_settings, tmp_path
):
    """Rows count > batch_size: every row is archived + deleted across
    multiple batches."""
    patched_settings.AUDIT_LOG_ARCHIVE_BATCH_SIZE = 100  # clamps to 100
    total_rows = 250  # forces 3 batches

    inserted: list[uuid.UUID] = []
    old = datetime.now(timezone.utc) - timedelta(days=400)

    async with session_factory() as setup:
        for i in range(total_rows):
            rid = await _insert_audit_row(
                setup,
                event="wp52.batch",
                created_at=old,
                metadata={"i": i},
            )
            inserted.append(rid)
        await setup.commit()

    try:
        async with session_factory() as session:
            archived, deleted = await archive_then_prune(
                session, "wp52.batch", 365
            )
            assert archived == total_rows
            assert deleted == total_rows

        async with session_factory() as check:
            for rid in inserted:
                assert not await _row_exists(check, rid)
    finally:
        async with session_factory() as cleanup:
            # Idempotent — rows already gone, but covers crash paths.
            await _delete_rows(cleanup, inserted)
