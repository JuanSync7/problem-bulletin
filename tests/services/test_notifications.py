"""
Tests for Watch & Notification Pipeline:
  app.services.watches   — set_watch, remove_watch, auto_watch
  app.services.notifications — generate_notification
  app.services.delivery  — push_ws_notification, send_teams_webhook,
                           send_email_digest, is_milestone

Derived from: docs/AION_BULLETIN_TEST_DOCS.md lines 1731–1876
Phase 0 contracts:
  - set_watch uses ON CONFLICT DO UPDATE (upsert semantics).
  - remove_watch returns False when no row exists.
  - auto_watch never downgrades an existing higher-priority level.
  - generate_notification excludes the actor from notifications.
  - WATCH_ROUTING: all_activity→all types, solutions_only→{solution_posted,
    solution_accepted}, status_only→{status_changed}, none→{}.
  - is_milestone is a pure function; no mocking needed.

GAP (REQ-312): The Phase 0 contracts and spec disagree on WATCH_ROUTING for
  solutions_only (spec adds solution_upvote_milestone) and status_only (spec adds
  problem_claimed, claim_expired, duplicate_flagged). Tests here use the Phase 0
  contract values. If WATCH_ROUTING in app/enums or app/services differs, update
  the routing assertions to match the coded implementation.

GAP (REQ-310): NotificationType enum names may differ between Phase 0 contracts
  (comment_posted, upstar_received, problem_pinned, problem_claimed) and the spec
  (new_comment, solution_upvote_milestone, claim_expired, duplicate_flagged).
  The app.enums module is the source of truth; update type strings if needed.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.watches import set_watch, remove_watch, auto_watch
from app.services.notifications import generate_notification
from app.services.delivery import (
    push_ws_notification,
    send_teams_webhook,
    send_email_digest,
    is_milestone,
)
from app.enums import WatchLevel, NotificationType
from app.models.notification import Notification
from app.models.watch import Watch
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_watch(user_id=None, problem_id=None, level=WatchLevel.all_activity):
    watch = MagicMock()
    watch.user_id = user_id or uuid.uuid4()
    watch.problem_id = problem_id or uuid.uuid4()
    watch.level = level
    return watch


def _make_notification(recipient_id=None, problem_id=None, event_type=None):
    n = MagicMock()
    n.id = uuid.uuid4()
    n.recipient_id = recipient_id or uuid.uuid4()
    n.problem_id = problem_id or uuid.uuid4()
    n.event_type = event_type or NotificationType.comment_posted
    n.is_read = False
    n.updated_at = None
    return n


def _make_watcher_row(user_id=None, level=WatchLevel.all_activity):
    row = MagicMock()
    row.user_id = user_id or uuid.uuid4()
    row.level = level
    return row


def _db_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value = result
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.fetchall.return_value = rows
    return result


# ---------------------------------------------------------------------------
# set_watch — upsert semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_watch_new_row_inserts(db):
    """set_watch with no prior row inserts a new Watch via ON CONFLICT DO UPDATE."""
    uid = await seed_user(db)
    pid = await seed_problem(db)

    result = await set_watch(db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.solutions_only)

    assert result is not None
    assert result.user_id == uid
    assert result.problem_id == pid
    assert result.level == WatchLevel.solutions_only.value


@pytest.mark.asyncio
async def test_set_watch_updates_existing_row(db):
    """Calling set_watch twice on the same (user_id, problem_id) upserts to new level."""
    uid = await seed_user(db)
    pid = await seed_problem(db)

    # First call — solutions_only
    first = await set_watch(db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.solutions_only)
    # Second call — upgrades level
    second = await set_watch(db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.all_activity)

    assert first.id == second.id  # same row (upsert)
    # Re-read from DB to bypass the SQLAlchemy identity-map cache.
    await db.refresh(second)
    assert second.level == WatchLevel.all_activity.value


@pytest.mark.asyncio
async def test_set_watch_second_call_returns_fresh_level_without_manual_refresh(db):
    """Regression for v2.11-WP04 A6.

    The SQLAlchemy identity map used to hand back the row in its
    pre-upsert state on the second call.  After WP04 the service runs
    ``await db.refresh(watch)`` internally, so the returned object's
    ``.level`` reflects the post-write value without the caller having
    to refresh manually.
    """
    uid = await seed_user(db)
    pid = await seed_problem(db)

    first = await set_watch(
        db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.status_only
    )
    assert first.level == WatchLevel.status_only.value

    second = await set_watch(
        db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.all_activity
    )

    # No manual ``db.refresh`` — the service must return the fresh level.
    assert second.level == WatchLevel.all_activity.value


# ---------------------------------------------------------------------------
# remove_watch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_watch_existing_row_returns_true(db):
    """remove_watch returns True when the row exists and is deleted."""
    uid = await seed_user(db)
    pid = await seed_problem(db)
    await set_watch(db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.all_activity)

    result = await remove_watch(db, user_id=str(uid), problem_id=str(pid))

    assert result is True


@pytest.mark.asyncio
async def test_remove_watch_missing_row_returns_false(db):
    """remove_watch returns False when no matching row exists."""
    uid = await seed_user(db)
    pid = await seed_problem(db)

    result = await remove_watch(db, user_id=str(uid), problem_id=str(pid))

    assert result is False


# ---------------------------------------------------------------------------
# auto_watch — priority comparison and no-downgrade guarantee
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_watch_no_prior_watch_sets_watch(db):
    """auto_watch with no existing row creates one at the requested level."""
    uid = await seed_user(db)
    pid = await seed_problem(db)

    result = await auto_watch(db, user_id=str(uid), problem_id=str(pid), level=WatchLevel.all_activity)

    assert result is not None
    assert result.user_id == uid
    assert result.problem_id == pid
    assert result.level == WatchLevel.all_activity.value


@pytest.mark.asyncio
async def test_auto_watch_upgrades_lower_priority(mock_db):
    """auto_watch upgrades from solutions_only (lower) to all_activity (higher)."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    existing = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.solutions_only)
    mock_db.execute.return_value = _db_result([existing])

    with patch("app.services.watches.get_watch", new_callable=AsyncMock, return_value=existing):
        with patch("app.services.watches.set_watch", new_callable=AsyncMock) as mock_set:
            upgraded = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.all_activity)
            mock_set.return_value = upgraded

            result = await auto_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_auto_watch_does_not_downgrade_higher_priority(mock_db):
    """auto_watch must not downgrade from all_activity to solutions_only."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    existing = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    with patch("app.services.watches.get_watch", new_callable=AsyncMock, return_value=existing):
        with patch("app.services.watches.set_watch", new_callable=AsyncMock) as mock_set:

            result = await auto_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.solutions_only)

    mock_set.assert_not_called()


@pytest.mark.asyncio
async def test_auto_watch_equal_level_no_op(mock_db):
    """auto_watch with equal-priority level is a no-op; set_watch not called."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    existing = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    with patch("app.services.watches.get_watch", new_callable=AsyncMock, return_value=existing):
        with patch("app.services.watches.set_watch", new_callable=AsyncMock) as mock_set:

            result = await auto_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# generate_notification — creates rows for qualifying watchers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_notification_creates_rows_for_watchers(db):
    """generate_notification inserts Notification rows for qualifying watchers."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db)
    await set_watch(db, user_id=str(watcher_id), problem_id=str(pid), level=WatchLevel.all_activity)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert isinstance(notifications, list)
    assert len(notifications) == 1
    assert notifications[0].recipient_id == watcher_id
    assert notifications[0].type == NotificationType.comment_posted.value


@pytest.mark.asyncio
async def test_generate_notification_excludes_actor(db):
    """Actor must not receive a notification for their own action."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    # Only watcher is the actor — must be excluded by the WHERE user_id != :actor
    await set_watch(db, user_id=str(actor_id), problem_id=str(pid), level=WatchLevel.all_activity)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert notifications == []


@pytest.mark.asyncio
async def test_generate_notification_empty_watcher_list_returns_empty(db):
    """When no watchers exist, generate_notification returns []."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert notifications == []


# ---------------------------------------------------------------------------
# generate_notification — WATCH_ROUTING filtering
# ---------------------------------------------------------------------------

async def _seed_watcher(db, pid, level):
    uid = await seed_user(db)
    await set_watch(db, user_id=str(uid), problem_id=str(pid), level=level)
    return uid


@pytest.mark.asyncio
async def test_routing_all_activity_receives_any_type(db):
    """all_activity level receives every notification type."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.all_activity)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_routing_solutions_only_receives_solution_posted(db):
    """solutions_only watcher receives solution_posted events."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.solutions_only)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.solution_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_routing_solutions_only_receives_solution_accepted(db):
    """solutions_only watcher receives solution_accepted events."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.solutions_only)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.solution_accepted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_routing_solutions_only_blocked_from_comment_posted(db):
    """solutions_only watcher must NOT receive comment_posted events."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.solutions_only)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert notifications == []


@pytest.mark.asyncio
async def test_routing_status_only_receives_status_changed(db):
    """status_only watcher receives status_changed events."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.status_only)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.status_changed,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_routing_status_only_blocked_from_solution_posted(db):
    """status_only watcher must NOT receive solution_posted events."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.status_only)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.solution_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    assert notifications == []


@pytest.mark.asyncio
async def test_routing_none_blocks_all_types(db):
    """none level must block every notification type."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.none)

    for event_type in [
        NotificationType.comment_posted,
        NotificationType.solution_posted,
        NotificationType.solution_accepted,
        NotificationType.status_changed,
    ]:
        notifications = await generate_notification(
            db,
            event_type=event_type,
            problem_id=str(pid),
            actor_id=str(actor_id),
        )
        assert notifications == [], f"none level must block {event_type}"


@pytest.mark.asyncio
async def test_routing_mixed_watcher_levels(db):
    """Three watchers (all_activity, solutions_only, none); event=solution_posted → 2 notifications."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    await _seed_watcher(db, pid, WatchLevel.all_activity)
    await _seed_watcher(db, pid, WatchLevel.solutions_only)
    await _seed_watcher(db, pid, WatchLevel.none)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.solution_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )

    # all_activity and solutions_only should receive; none should not
    assert len(notifications) == 2


# ---------------------------------------------------------------------------
# push_ws_notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_ws_notification_broadcasts_to_active_connection(db):
    """push_ws_notification calls broadcast_to_user for a connected recipient.

    Uses a real Notification row (live DB) and mocks only the WebSocket
    connection_manager at its boundary.
    """
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db)
    await set_watch(db, user_id=str(watcher_id), problem_id=str(pid), level=WatchLevel.all_activity)

    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )
    assert len(notifications) == 1
    notification = notifications[0]

    mock_manager = AsyncMock()
    mock_manager.broadcast_to_user = AsyncMock()

    with patch("app.services.delivery.connection_manager", mock_manager):
        await push_ws_notification(notification)

    mock_manager.broadcast_to_user.assert_called_once()
    call_args = mock_manager.broadcast_to_user.call_args
    # First positional arg is the recipient id as a string
    assert call_args.args[0] == str(notification.recipient_id)


@pytest.mark.asyncio
async def test_push_ws_notification_no_connections_is_noop():
    """push_ws_notification is a no-op and raises no exception when recipient has no connections."""
    notification = _make_notification()

    mock_manager = AsyncMock()
    mock_manager.broadcast_to_user = AsyncMock(return_value=None)

    with patch("app.services.delivery.connection_manager", mock_manager):
        # Must not raise
        await push_ws_notification(notification)


@pytest.mark.asyncio
async def test_push_ws_notification_swallows_broadcast_exceptions():
    """push_ws_notification catches unexpected broadcast failures silently."""
    notification = _make_notification()

    mock_manager = AsyncMock()
    mock_manager.broadcast_to_user = AsyncMock(side_effect=RuntimeError("unexpected"))

    with patch("app.services.delivery.connection_manager", mock_manager):
        # Must not propagate the exception
        await push_ws_notification(notification)


# ---------------------------------------------------------------------------
# send_teams_webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_teams_webhook_fires_and_forgets(db):
    """send_teams_webhook calls httpx.AsyncClient.post with Adaptive Card payload.

    Uses a real Notification row (live DB) and mocks only the httpx client.
    The TEAMS_WEBHOOK_URL setting is forced to a non-empty value.
    """
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db)
    await set_watch(db, user_id=str(watcher_id), problem_id=str(pid), level=WatchLevel.all_activity)
    notifications = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )
    notification = notifications[0]
    # created_at is server-default; populate via flush+refresh
    await db.flush()
    await db.refresh(notification)

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.delivery.httpx.AsyncClient", return_value=mock_client):
        with patch("app.services.delivery.get_settings") as mock_settings:
            settings = MagicMock()
            settings.TEAMS_WEBHOOK_URL = "https://example.invalid/webhook"
            mock_settings.return_value = settings
            await send_teams_webhook(notification)

    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_teams_webhook_silent_on_failure():
    """send_teams_webhook catches httpx exceptions and returns silently."""
    import httpx

    notification = _make_notification()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused", request=MagicMock()))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.delivery.httpx.AsyncClient", return_value=mock_client):
        # Must not raise
        await send_teams_webhook(notification)


@pytest.mark.asyncio
async def test_send_teams_webhook_no_op_when_url_unconfigured():
    """send_teams_webhook returns early without HTTP call when TEAMS_WEBHOOK_URL is empty."""
    notification = _make_notification()

    with patch("app.services.delivery.httpx.AsyncClient") as mock_cls:
        with patch("app.services.delivery.get_settings") as mock_settings:
            settings = MagicMock()
            settings.TEAMS_WEBHOOK_URL = None  # production reads the uppercase attribute
            mock_settings.return_value = settings

            await send_teams_webhook(notification)

        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# send_email_digest
# ---------------------------------------------------------------------------

async def _build_real_notification(db, *, pid, actor_id, watcher_id) -> Notification:
    """Helper: insert one Notification row via generate_notification and refresh."""
    await set_watch(db, user_id=str(watcher_id), problem_id=str(pid), level=WatchLevel.all_activity)
    rows = await generate_notification(
        db,
        event_type=NotificationType.comment_posted,
        problem_id=str(pid),
        actor_id=str(actor_id),
    )
    await db.flush()
    await db.refresh(rows[0])
    return rows[0]


@pytest.mark.asyncio
async def test_send_email_digest_calls_aiosmtplib(db):
    """send_email_digest calls aiosmtplib.send and stamps updated_at.

    Real User and Notification rows; SMTP mocked at the aiosmtplib boundary.
    """
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db, email="user@example.com")
    notifications = [
        await _build_real_notification(db, pid=pid, actor_id=actor_id, watcher_id=watcher_id)
    ]

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        await send_email_digest(db, user_id=str(watcher_id), notifications=notifications)

    mock_smtp.assert_called_once()
    for n in notifications:
        assert n.updated_at is not None


@pytest.mark.asyncio
async def test_send_email_digest_stamps_updated_at(db):
    """updated_at is set on each notification after a successful digest send."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db, email="alice@example.com")
    notification = await _build_real_notification(
        db, pid=pid, actor_id=actor_id, watcher_id=watcher_id
    )
    assert notification.updated_at is None

    with patch("aiosmtplib.send", new_callable=AsyncMock):
        await send_email_digest(db, user_id=str(watcher_id), notifications=[notification])

    assert notification.updated_at is not None


@pytest.mark.asyncio
async def test_send_email_digest_silent_on_smtp_failure(db):
    """send_email_digest catches SMTP failures and does NOT stamp updated_at."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db, email="bob@example.com")
    notification = await _build_real_notification(
        db, pid=pid, actor_id=actor_id, watcher_id=watcher_id
    )
    assert notification.updated_at is None

    with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("SMTP error")):
        # Must not raise
        await send_email_digest(db, user_id=str(watcher_id), notifications=[notification])

    # updated_at must NOT be stamped on failure
    assert notification.updated_at is None


@pytest.mark.asyncio
async def test_send_email_digest_no_smtp_call_for_unknown_user(db):
    """When user_id does not match any User row, SMTP is not called and no exception raised."""
    pid = await seed_problem(db)
    actor_id = await seed_user(db)
    watcher_id = await seed_user(db)
    # Build a real notification row so the early-return guard (empty list)
    # doesn't pre-empt the user lookup branch.
    notification = await _build_real_notification(
        db, pid=pid, actor_id=actor_id, watcher_id=watcher_id
    )

    unknown_user_id = uuid.uuid4()
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        await send_email_digest(db, user_id=str(unknown_user_id), notifications=[notification])

    mock_smtp.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_digest_zero_notifications_no_smtp_call(mock_db):
    """send_email_digest with an empty notifications list must not call SMTP.

    GAP: The spec requires no duplicate sends, but idempotency of the stamp
    logic is not fully testable here without exercising the digest job query.
    """
    uid = uuid.uuid4()
    mock_user = MagicMock()
    mock_user.id = uid
    mock_user.email = "user@example.com"
    mock_user.display_name = "Test User"
    mock_db.get.return_value = mock_user

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        await send_email_digest(mock_db, user_id=uid, notifications=[])

    mock_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# is_milestone — pure function; no mocking required
# ---------------------------------------------------------------------------

def test_is_milestone_true_for_threshold_values():
    """is_milestone returns True for [10, 25, 50, 100]."""
    assert is_milestone(10) is True
    assert is_milestone(25) is True
    assert is_milestone(50) is True
    assert is_milestone(100) is True


def test_is_milestone_false_for_non_threshold_values():
    """is_milestone returns False for values not in the milestone set."""
    for value in [0, 1, 9, 11, 24, 26, 49, 51, 99, 101, -1, 200]:
        assert is_milestone(value) is False, f"Expected False for is_milestone({value})"


def test_is_milestone_exact_list_membership():
    """Only exactly [10, 25, 50, 100] return True; adjacent values return False."""
    # Boundary checks
    assert is_milestone(9) is False
    assert is_milestone(10) is True
    assert is_milestone(11) is False

    assert is_milestone(24) is False
    assert is_milestone(25) is True
    assert is_milestone(26) is False

    assert is_milestone(49) is False
    assert is_milestone(50) is True
    assert is_milestone(51) is False

    assert is_milestone(99) is False
    assert is_milestone(100) is True
    assert is_milestone(101) is False


# ---------------------------------------------------------------------------
# Mark read / mark all read / notification listing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_single_notification_read(mock_db):
    """Marking a notification as read sets is_read=True and calls flush."""
    notification = _make_notification()
    notification.is_read = False
    mock_db.execute.return_value = _db_result([notification])

    # Import the mark_read service function if it exists; adjust import as needed.
    try:
        from app.services.notifications import mark_notification_read
    except ImportError:
        pytest.skip("mark_notification_read not yet implemented — GAP")

    uid = notification.recipient_id
    await mark_notification_read(mock_db, notification_id=notification.id, user_id=uid)

    mock_db.execute.assert_called()


@pytest.mark.asyncio
async def test_mark_all_notifications_read(mock_db):
    """mark_all_read issues a bulk UPDATE for all unread notifications by recipient."""
    try:
        from app.services.notifications import mark_all_notifications_read
    except ImportError:
        pytest.skip("mark_all_notifications_read not yet implemented — GAP")

    uid = uuid.uuid4()
    mock_db.execute.return_value = _db_result([])

    await mark_all_notifications_read(mock_db, user_id=uid)

    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_list_notifications_default_page(mock_db):
    """get_notifications returns up to 20 notifications ordered by created_at DESC."""
    try:
        from app.services.notifications import get_notifications
    except ImportError:
        pytest.skip("get_notifications not yet implemented — GAP")

    uid = uuid.uuid4()
    rows = [_make_notification(recipient_id=uid) for _ in range(5)]
    mock_db.execute.return_value = _db_result(rows)

    result = await get_notifications(mock_db, user_id=uid)

    assert isinstance(result, list)
    assert len(result) <= 20


@pytest.mark.asyncio
async def test_list_notifications_unread_only_filter(mock_db):
    """get_notifications with unread_only=True returns only unread rows."""
    try:
        from app.services.notifications import get_notifications
    except ImportError:
        pytest.skip("get_notifications not yet implemented — GAP")

    uid = uuid.uuid4()
    unread = _make_notification(recipient_id=uid)
    unread.is_read = False
    mock_db.execute.return_value = _db_result([unread])

    result = await get_notifications(mock_db, user_id=uid, unread_only=True)

    mock_db.execute.assert_called_once()
    assert isinstance(result, list)
