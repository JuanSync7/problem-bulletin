"""Audit-log retention scanner — v2.6-WP44 + v2.7-WP51.

Periodically hard-deletes rows from ``activity_audit_log`` older than
``settings.AUDIT_LOG_RETENTION_DAYS``, with optional per-event-type overrides
(``settings.AUDIT_LOG_RETENTION_OVERRIDES``) so high-churn events
(``auth.login_failed``) can age out faster than rare admin events
(``user.handle_changed_by_admin``).

Design
------
* ``prune_once(session)`` — testable in isolation. Acquires a session-scoped
  Postgres advisory lock (WP46 helper). On contention returns an empty result
  with a log line.

  When ``AUDIT_LOG_RETENTION_OVERRIDES`` is non-empty:
    * For each ``(event, days)`` override: one ``DELETE`` filtered by
      ``event = :evt AND created_at < NOW() - INTERVAL ...``.
    * For all remaining event types: one ``DELETE`` with
      ``event NOT IN (override_keys) AND created_at < NOW() - INTERVAL
      :global_days``.
  Otherwise (empty overrides): a single global ``DELETE`` matching WP44
  behaviour exactly.

  Returns a ``PruneResult`` — an ``int`` (total rows deleted) carrying a
  ``per_event: dict[str, int]`` attribute. Back-compatible with WP44 callers
  that treat the return as an int; the ``"__global__"`` key holds the
  fallback-bucket count.

* ``run_loop(session_factory)`` — unchanged poll-loop wrapper.

Postgres-only — uses ``NOW() - INTERVAL '<N> days'`` rather than an
application-side cutoff, per spec.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.services import audit_log
from app.services._advisory import advisory_lock_key, with_advisory_lock

logger = logging.getLogger(__name__)

_LOCK_KEY_STR = "audit_log_retention"
# Kept for backward-compat: existing tests import the numeric key directly.
_LOCK_KEY = advisory_lock_key(_LOCK_KEY_STR)

# Bucket-key used in PruneResult.per_event for the global fallback DELETE
# (covers all event types NOT listed in AUDIT_LOG_RETENTION_OVERRIDES).
GLOBAL_BUCKET = "__global__"


class PruneResult(int):
    """``int`` (total rows deleted) with a ``per_event`` per-bucket breakdown.

    Subclassing ``int`` preserves WP44 callers that wrote
    ``deleted = await prune_once(session)`` and then did
    ``assert deleted == 3`` / ``assert deleted >= 1``. WP51 callers can read
    ``deleted.per_event`` for the ``{event_type: rows_deleted}`` shape.

    WP52 adds ``per_event_archived``: the count of rows written to the
    cold-storage JSONL archive (parallel to ``per_event`` deletions). When
    the archiver is disabled this stays an empty dict so existing callers
    keep their shape.
    """

    per_event: dict[str, int]
    per_event_archived: dict[str, int]

    def __new__(
        cls,
        total: int,
        per_event: dict[str, int] | None = None,
        per_event_archived: dict[str, int] | None = None,
    ):
        obj = super().__new__(cls, total)
        obj.per_event = dict(per_event or {})
        obj.per_event_archived = dict(per_event_archived or {})
        return obj


async def prune_once(session: AsyncSession) -> PruneResult:
    """Hard-delete ``activity_audit_log`` rows older than retention cutoffs.

    Returns a ``PruneResult`` (int total + ``per_event`` breakdown). Returns
    ``PruneResult(0, {})`` if:
      * ``AUDIT_LOG_RETENTION_ENABLED`` is False, OR
      * another worker holds the advisory lock (contention).

    Always commits in one transaction at the end so the bucketed deletes are
    atomic. The advisory lock is released in the ``with_advisory_lock``
    context-manager's ``finally`` clause so it cannot leak.
    """
    settings = get_settings()
    if not settings.AUDIT_LOG_RETENTION_ENABLED:
        logger.debug("audit_log_retention: disabled by settings; skipping")
        return PruneResult(0, {})

    overrides: dict[str, int] = dict(
        getattr(settings, "AUDIT_LOG_RETENTION_OVERRIDES", {}) or {}
    )
    global_days = int(settings.AUDIT_LOG_RETENTION_DAYS)

    # WP52: archive-then-delete path is opt-in via two settings (master switch
    # + non-empty directory). When OFF we keep the WP51 fast DELETE path
    # exactly as-is for backward compat.
    archive_enabled = bool(
        getattr(settings, "AUDIT_LOG_ARCHIVE_ENABLED", False)
    ) and bool(getattr(settings, "AUDIT_LOG_ARCHIVE_DIR", None))

    async with with_advisory_lock(session, _LOCK_KEY_STR) as acquired:
        if not acquired:
            logger.info(
                "audit_log_retention: another worker holds the prune lock; skipping"
            )
            return PruneResult(0, {})

        per_event: dict[str, int] = {}
        per_event_archived: dict[str, int] = {}

        if archive_enabled:
            # Lazy import — keeps the audit_log_archive module unimported on
            # the disabled path, which matters for environments that haven't
            # provisioned an archive dir.
            from app.services.audit_log_archive import archive_then_prune

            # 1) Per-override buckets via archiver.
            for evt, days in overrides.items():
                archived, deleted = await archive_then_prune(
                    session, evt, int(days)
                )
                per_event[evt] = deleted
                per_event_archived[evt] = archived

            # 2) Global fallback bucket via archiver.
            archived, deleted = await archive_then_prune(
                session,
                None,
                global_days,
                exclude_events=list(overrides.keys()) if overrides else None,
            )
            per_event[GLOBAL_BUCKET] = deleted
            per_event_archived[GLOBAL_BUCKET] = archived
        else:
            # 1) Per-override buckets.
            for evt, days in overrides.items():
                days_i = int(days)
                # INTERVAL string built from a vetted int — overrides validator
                # clamps to [1, 3650] so no SQL-injection surface here.
                sql = (
                    "DELETE FROM activity_audit_log "
                    "WHERE event = :evt "
                    f"AND created_at < NOW() - INTERVAL '{days_i} days'"
                )
                result = await session.execute(
                    text(sql).execution_options(synchronize_session=False),
                    {"evt": evt},
                )
                per_event[evt] = int(result.rowcount or 0)

            # 2) Global fallback bucket (event NOT IN overrides, older than global_days).
            if overrides:
                from sqlalchemy import bindparam

                sql_expanding = (
                    "DELETE FROM activity_audit_log "
                    "WHERE event NOT IN :keys "
                    f"AND created_at < NOW() - INTERVAL '{global_days} days'"
                )
                stmt = (
                    text(sql_expanding)
                    .bindparams(bindparam("keys", expanding=True))
                    .execution_options(synchronize_session=False)
                )
                result = await session.execute(stmt, {"keys": list(overrides.keys())})
                per_event[GLOBAL_BUCKET] = int(result.rowcount or 0)
            else:
                sql = (
                    "DELETE FROM activity_audit_log "
                    f"WHERE created_at < NOW() - INTERVAL '{global_days} days'"
                )
                result = await session.execute(
                    text(sql).execution_options(synchronize_session=False),
                )
                per_event[GLOBAL_BUCKET] = int(result.rowcount or 0)

        total = sum(per_event.values())
        if not archive_enabled:
            await session.commit()

        total_archived = sum(per_event_archived.values())
        if total or total_archived:
            logger.info(
                "audit_log_retention: pruned %d row(s); archived=%d; per_event=%s",
                total,
                total_archived,
                per_event,
            )
            # Emit a summary audit event so the prune itself is observable.
            # NOTE (WP51): If the operator sets a very small override for
            # 'audit_log.pruned' itself, this very row may be pruned on a
            # subsequent run. That is harmless (it just ages out) but worth
            # remembering when chasing missing observability data.
            try:
                await audit_log.record(
                    session,
                    event="audit_log.pruned",
                    actor_user_id=None,
                    target_type=None,
                    target_id=None,
                    metadata={
                        "total": total,
                        "per_event": per_event,
                        "global_days": global_days,
                        "overrides": overrides,
                    },
                )
                # WP52: parallel summary for the archive side. Only emit when
                # the archiver was actually engaged — otherwise the counts are
                # all zero and the event is just noise.
                if archive_enabled:
                    await audit_log.record(
                        session,
                        event="audit_log.archived",
                        actor_user_id=None,
                        target_type=None,
                        target_id=None,
                        metadata={
                            "total_archived": total_archived,
                            "per_event_archived": per_event_archived,
                            "global_days": global_days,
                            "overrides": overrides,
                        },
                    )
                # audit_log.record uses a nested SAVEPOINT and never raises,
                # but it doesn't commit — flush+commit the outer tx so the
                # summary row lands.
                await session.commit()
            except Exception:
                logger.exception(
                    "audit_log_retention: failed to emit audit_log.pruned summary"
                )

        return PruneResult(total, per_event, per_event_archived)


async def run_loop(session_factory: async_sessionmaker) -> None:
    """Run ``prune_once`` on ``AUDIT_LOG_RETENTION_SCAN_INTERVAL_SECONDS`` cadence.

    Exits immediately if ``AUDIT_LOG_RETENTION_ENABLED`` is False so deploys
    can disable retention via env var with no overhead. A single prune
    failure is caught and logged; the loop continues.
    """
    settings = get_settings()
    if not settings.AUDIT_LOG_RETENTION_ENABLED:
        logger.info("audit_log_retention: disabled by settings; loop not starting")
        return

    interval = settings.AUDIT_LOG_RETENTION_SCAN_INTERVAL_SECONDS
    logger.info("audit_log_retention: loop started (interval=%ds)", interval)
    while True:
        try:
            async with session_factory() as session:
                await prune_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "audit_log_retention: prune failed; will retry in %ds", interval
            )

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break

    logger.info("audit_log_retention: loop stopped")
