"""Audit-log cold-storage archiver — v2.7-WP52.

SOC2 wants every row that ages out of ``activity_audit_log`` to land in
durable storage *before* the DELETE. WP44/WP51 did hard-delete only; WP52
adds a local rotating JSONL archive (S3/GCS pluggable later).

Contract
--------
``archive_then_prune(session, event_type, days) -> (archived, deleted)``
streams rows older than ``NOW() - INTERVAL '<days> days'`` matching the
WP51 predicate (single event or "everything not in overrides" when
``event_type is None``) to ``{ARCHIVE_DIR}/{event_type or "_default"}-{UTC date}.jsonl``,
then DELETEs by primary key.

Safety invariant
~~~~~~~~~~~~~~~~
**Never DELETE without a successful file append.** Each batch runs in one
transaction:

  1. SELECT id, event, actor_user_id, target_type, target_id, metadata,
     created_at … FOR UPDATE SKIP LOCKED LIMIT :batch_size
  2. Append serialised JSON lines to the archive file
     (``asyncio.to_thread`` around stdlib ``open(..., 'a')`` — no
     ``aiofiles`` dep required).
  3. DELETE WHERE id IN (...)
  4. COMMIT.

If step 2 raises, the transaction is rolled back and the rows remain
locked-by-no-one (advisory locks released) so a later run can retry. If
step 3 deletes zero rows (someone else got there first), the partial JSONL
write is tolerated — the rows are in the archive but already gone from the
table; SOC2 only cares we never lost a row, not that we never archived a
row twice.

The ``event_type=None`` branch matches the WP51 "global fallback bucket":
``event NOT IN (override_keys) AND created_at < cutoff``. Callers pass the
override-keys list via ``exclude_events``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)


def _row_to_jsonl(row: dict[str, Any]) -> str:
    """Serialise one audit row to a single JSONL line.

    Handles ``UUID`` and ``datetime`` (the only non-JSON-native types we
    expect from ``activity_audit_log``). ``metadata`` is JSONB and arrives
    as a Python dict from asyncpg, so it serialises directly.
    """
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return json.dumps(out, separators=(",", ":"), sort_keys=True)


def _archive_path(archive_dir: str, event_type: str | None) -> str:
    """``{dir}/{event or _default}-{UTC YYYY-MM-DD}.jsonl``."""
    bucket = event_type or "_default"
    # Sanitise: event names are dot-notated lowercase ascii in practice, but
    # guard against path separators just in case.
    safe = bucket.replace("/", "_").replace(os.sep, "_")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(archive_dir, f"{safe}-{date}.jsonl")


def _append_lines_sync(path: str, lines: list[str]) -> None:
    """Blocking file append — invoked via ``asyncio.to_thread``.

    Opens in append mode so concurrent runs targeting the same
    ``(event_type, date)`` bucket simply interleave without truncating.
    Each line ends in ``\\n`` per the JSONL convention. If the directory
    does not exist this raises ``FileNotFoundError`` — operators must
    pre-create ``AUDIT_LOG_ARCHIVE_DIR``, or we'd silently mkdir into a
    bad location.
    """
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line)
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


async def _select_batch(
    session: AsyncSession,
    *,
    event_type: str | None,
    days: int,
    batch_size: int,
    exclude_events: list[str] | None,
) -> list[dict[str, Any]]:
    """SELECT one batch of rows past cutoff, FOR UPDATE SKIP LOCKED.

    Mirrors the WP51 DELETE predicate exactly:
      * ``event_type=str`` → ``event = :evt AND created_at < cutoff``
      * ``event_type=None`` → ``event NOT IN :exclude AND created_at < cutoff``
        (or no event filter at all when ``exclude_events`` is empty/None,
        matching the WP44 empty-overrides single-cutoff case).
    """
    cutoff_sql = f"NOW() - INTERVAL '{int(days)} days'"
    cols = "id, event, actor_user_id, target_type, target_id, metadata, created_at"

    if event_type is not None:
        sql = (
            f"SELECT {cols} FROM activity_audit_log "
            f"WHERE event = :evt AND created_at < {cutoff_sql} "
            f"ORDER BY created_at "
            f"LIMIT :lim FOR UPDATE SKIP LOCKED"
        )
        result = await session.execute(
            text(sql), {"evt": event_type, "lim": batch_size}
        )
    elif exclude_events:
        sql = (
            f"SELECT {cols} FROM activity_audit_log "
            f"WHERE event NOT IN :keys AND created_at < {cutoff_sql} "
            f"ORDER BY created_at "
            f"LIMIT :lim FOR UPDATE SKIP LOCKED"
        )
        stmt = text(sql).bindparams(bindparam("keys", expanding=True))
        result = await session.execute(
            stmt, {"keys": list(exclude_events), "lim": batch_size}
        )
    else:
        sql = (
            f"SELECT {cols} FROM activity_audit_log "
            f"WHERE created_at < {cutoff_sql} "
            f"ORDER BY created_at "
            f"LIMIT :lim FOR UPDATE SKIP LOCKED"
        )
        result = await session.execute(text(sql), {"lim": batch_size})

    return [dict(row) for row in result.mappings().all()]


async def archive_then_prune(
    session: AsyncSession,
    event_type: str | None,
    days: int,
    *,
    exclude_events: list[str] | None = None,
) -> tuple[int, int]:
    """Archive-then-delete rows past cutoff. Returns (archived, deleted).

    Loops over batches of size ``AUDIT_LOG_ARCHIVE_BATCH_SIZE`` until the
    SELECT comes back empty. Each iteration is its own transaction so
    long-running prunes don't hold one massive lock.

    Raises ``RuntimeError`` if ``AUDIT_LOG_ARCHIVE_DIR`` is not set —
    callers must check ``AUDIT_LOG_ARCHIVE_ENABLED`` first.
    """
    settings = get_settings()
    archive_dir = settings.AUDIT_LOG_ARCHIVE_DIR
    if not archive_dir:
        raise RuntimeError(
            "archive_then_prune called with AUDIT_LOG_ARCHIVE_DIR unset"
        )
    batch_size = int(settings.AUDIT_LOG_ARCHIVE_BATCH_SIZE)

    total_archived = 0
    total_deleted = 0

    while True:
        rows = await _select_batch(
            session,
            event_type=event_type,
            days=days,
            batch_size=batch_size,
            exclude_events=exclude_events,
        )
        if not rows:
            # Nothing else to do — release row locks via rollback (no writes).
            await session.rollback()
            break

        lines = [_row_to_jsonl(r) for r in rows]
        ids = [r["id"] for r in rows]
        path = _archive_path(archive_dir, event_type)

        try:
            # Step 1: write durably to disk. If this raises, the batch is
            # aborted via rollback below and rows stay in the table.
            await asyncio.to_thread(_append_lines_sync, path, lines)
        except Exception:
            logger.exception(
                "audit_log_archive: file write failed; rolling back batch "
                "(event_type=%s, batch=%d)",
                event_type,
                len(rows),
            )
            await session.rollback()
            raise

        # Step 2: DELETE by primary key — fast and indexed.
        del_stmt = text(
            "DELETE FROM activity_audit_log WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        del_result = await session.execute(
            del_stmt.execution_options(synchronize_session=False),
            {"ids": ids},
        )
        deleted = int(del_result.rowcount or 0)

        await session.commit()

        total_archived += len(rows)
        total_deleted += deleted

        # Short-circuit: if a batch came back under the requested size we
        # know we've drained the bucket — saves one empty SELECT round-trip.
        if len(rows) < batch_size:
            break

    if total_archived:
        logger.info(
            "audit_log_archive: archived=%d deleted=%d event_type=%s",
            total_archived,
            total_deleted,
            event_type,
        )
    return total_archived, total_deleted
