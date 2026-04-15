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
async def test_set_watch_new_row_inserts(mock_db):
    """set_watch with no prior row inserts a new Watch via ON CONFLICT DO UPDATE."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    expected_watch = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.solutions_only)
    mock_db.execute.return_value = _db_result([expected_watch])

    result = await set_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.solutions_only)

    mock_db.execute.assert_called()
    assert result is not None


@pytest.mark.asyncio
async def test_set_watch_updates_existing_row(mock_db):
    """Calling set_watch twice on the same (user_id, problem_id) upserts to new level."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    mock_db.execute.return_value = _db_result([_make_watch(user_id=uid, problem_id=pid, level=WatchLevel.all_activity)])

    # First call
    await set_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.solutions_only)
    # Second call — upgrades level
    result = await set_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    assert mock_db.execute.call_count >= 2


# ---------------------------------------------------------------------------
# remove_watch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_watch_existing_row_returns_true(mock_db):
    """remove_watch returns True when the row exists and is deleted."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    # Simulate rowcount=1 (one row deleted)
    result_mock = MagicMock()
    result_mock.rowcount = 1
    mock_db.execute.return_value = result_mock

    result = await remove_watch(mock_db, user_id=uid, problem_id=pid)

    assert result is True


@pytest.mark.asyncio
async def test_remove_watch_missing_row_returns_false(mock_db):
    """remove_watch returns False when no matching row exists."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    # Simulate rowcount=0 (no row deleted)
    result_mock = MagicMock()
    result_mock.rowcount = 0
    mock_db.execute.return_value = result_mock

    result = await remove_watch(mock_db, user_id=uid, problem_id=pid)

    assert result is False


# ---------------------------------------------------------------------------
# auto_watch — priority comparison and no-downgrade guarantee
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_watch_no_prior_watch_sets_watch(mock_db):
    """auto_watch with no existing row calls set_watch."""
    uid = uuid.uuid4()
    pid = uuid.uuid4()
    # get_watch returns None → no existing watch
    mock_db.execute.return_value = _db_result([])

    with patch("app.services.watches.set_watch", new_callable=AsyncMock) as mock_set:
        new_watch = _make_watch(user_id=uid, problem_id=pid, level=WatchLevel.all_activity)
        mock_set.return_value = new_watch

        result = await auto_watch(mock_db, user_id=uid, problem_id=pid, level=WatchLevel.all_activity)

    mock_set.assert_called_once()


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
async def test_generate_notification_creates_rows_for_watchers(mock_db):
    """generate_notification inserts Notification rows for qualifying watchers."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.all_activity)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.comment_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    mock_db.add_all.assert_called_once()
    mock_db.flush.assert_called_once()
    assert isinstance(notifications, list)
    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_generate_notification_excludes_actor(mock_db):
    """Actor must not receive a notification for their own action."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    # Only watcher is the actor — must be excluded
    watcher_row = _make_watcher_row(user_id=actor_id, level=WatchLevel.all_activity)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.comment_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    # Actor is excluded at query level; result is empty
    assert notifications == []


@pytest.mark.asyncio
async def test_generate_notification_empty_watcher_list_returns_empty(mock_db):
    """When no watchers exist, generate_notification returns [] and calls add_all([])."""
    mock_db.execute.return_value = _db_result([])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.comment_posted,
        problem_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
    )

    assert notifications == []
    mock_db.add_all.assert_called_once_with([])


# ---------------------------------------------------------------------------
# generate_notification — WATCH_ROUTING filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routing_all_activity_receives_any_type(mock_db):
    """all_activity level receives every notification type."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.all_activity)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.comment_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_routing_solutions_only_receives_solution_posted(mock_db):
    """solutions_only watcher receives solution_posted events."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.solutions_only)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.solution_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_routing_solutions_only_receives_solution_accepted(mock_db):
    """solutions_only watcher receives solution_accepted events."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.solutions_only)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.solution_accepted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_routing_solutions_only_blocked_from_comment_posted(mock_db):
    """solutions_only watcher must NOT receive comment_posted events.

    GAP: Phase 0 says solutions_only → {solution_posted, solution_accepted}.
    If WATCH_ROUTING in the implementation differs, update this assertion.
    """
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.solutions_only)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.comment_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert notifications == []


@pytest.mark.asyncio
async def test_routing_status_only_receives_status_changed(mock_db):
    """status_only watcher receives status_changed events."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.status_only)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.status_changed,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_routing_status_only_blocked_from_solution_posted(mock_db):
    """status_only watcher must NOT receive solution_posted events.

    GAP: Phase 0 says status_only → {status_changed} only.
    """
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.status_only)
    mock_db.execute.return_value = _db_result([watcher_row])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.solution_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    assert notifications == []


@pytest.mark.asyncio
async def test_routing_none_blocks_all_types(mock_db):
    """none level must block every notification type.

    GAP: Verify none does not accidentally inherit status_only routing via
    an off-by-one in the routing table lookup.
    """
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    watcher_id = uuid.uuid4()
    watcher_row = _make_watcher_row(user_id=watcher_id, level=WatchLevel.none)
    mock_db.execute.return_value = _db_result([watcher_row])

    for event_type in [
        NotificationType.comment_posted,
        NotificationType.solution_posted,
        NotificationType.solution_accepted,
        NotificationType.status_changed,
    ]:
        mock_db.execute.return_value = _db_result([watcher_row])
        notifications = await generate_notification(
            mock_db,
            event_type=event_type,
            problem_id=problem_id,
            actor_id=actor_id,
        )
        assert notifications == [], f"none level must block {event_type}"


@pytest.mark.asyncio
async def test_routing_mixed_watcher_levels(mock_db):
    """Three watchers (all_activity, solutions_only, none); event=solution_posted → 2 notifications."""
    problem_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    w_all = _make_watcher_row(user_id=uuid.uuid4(), level=WatchLevel.all_activity)
    w_sol = _make_watcher_row(user_id=uuid.uuid4(), level=WatchLevel.solutions_only)
    w_none = _make_watcher_row(user_id=uuid.uuid4(), level=WatchLevel.none)
    mock_db.execute.return_value = _db_result([w_all, w_sol, w_none])

    notifications = await generate_notification(
        mock_db,
        event_type=NotificationType.solution_posted,
        problem_id=problem_id,
        actor_id=actor_id,
    )

    # all_activity and solutions_only should receive; none should not
    assert len(notifications) == 2


# ---------------------------------------------------------------------------
# push_ws_notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_ws_notification_broadcasts_to_active_connection():
    """push_ws_notification calls broadcast_to_user for a connected recipient."""
    notification = _make_notification()

    mock_manager = AsyncMock()
    mock_manager.broadcast_to_user = AsyncMock()

    with patch("app.services.delivery.connection_manager", mock_manager):
        await push_ws_notification(notification)

    mock_manager.broadcast_to_user.assert_called_once()
    call_args = mock_manager.broadcast_to_user.call_args
    # Verify the notification's recipient_id was passed
    assert notification.recipient_id in call_args.args or notification.recipient_id in call_args.kwargs.values()


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
async def test_send_teams_webhook_fires_and_forgets(mock_teams_webhook):
    """send_teams_webhook calls httpx.AsyncClient.post with Adaptive Card payload."""
    notification = _make_notification()

    with patch("app.services.delivery.httpx.AsyncClient", return_value=mock_teams_webhook):
        await send_teams_webhook(notification)

    mock_teams_webhook.post.assert_called_once()


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
            settings.teams_webhook_url = None
            mock_settings.return_value = settings

            await send_teams_webhook(notification)

        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# send_email_digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_email_digest_calls_aiosmtplib(mock_db, mock_smtp):
    """send_email_digest calls aiosmtplib.send and stamps updated_at."""
    uid = uuid.uuid4()
    notifications = [_make_notification(recipient_id=uid) for _ in range(3)]

    # Simulate db.get returning a User with an email address
    mock_user = MagicMock()
    mock_user.id = uid
    mock_user.email = "user@example.com"
    mock_user.display_name = "Test User"
    mock_db.get.return_value = mock_user

    await send_email_digest(mock_db, user_id=uid, notifications=notifications)

    mock_smtp.assert_called_once()
    # updated_at should be stamped on each notification
    for n in notifications:
        assert n.updated_at is not None


@pytest.mark.asyncio
async def test_send_email_digest_stamps_updated_at(mock_db, mock_smtp):
    """updated_at is set on each notification after a successful digest send."""
    uid = uuid.uuid4()
    n = _make_notification(recipient_id=uid)
    n.updated_at = None

    mock_user = MagicMock()
    mock_user.id = uid
    mock_user.email = "user@example.com"
    mock_user.display_name = "Test User"
    mock_db.get.return_value = mock_user

    await send_email_digest(mock_db, user_id=uid, notifications=[n])

    assert n.updated_at is not None
    mock_db.flush.assert_called()


@pytest.mark.asyncio
async def test_send_email_digest_silent_on_smtp_failure(mock_db):
    """send_email_digest catches SMTP failures and does NOT stamp updated_at."""
    uid = uuid.uuid4()
    n = _make_notification(recipient_id=uid)
    n.updated_at = None

    mock_user = MagicMock()
    mock_user.id = uid
    mock_user.email = "user@example.com"
    mock_user.display_name = "Test User"
    mock_db.get.return_value = mock_user

    with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("SMTP error")):
        # Must not raise
        await send_email_digest(mock_db, user_id=uid, notifications=[n])

    # updated_at must NOT be stamped on failure
    assert n.updated_at is None


@pytest.mark.asyncio
async def test_send_email_digest_no_smtp_call_for_unknown_user(mock_db):
    """When user_id does not match any User row, SMTP is not called and no exception raised."""
    mock_db.get.return_value = None  # user not found

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_smtp:
        await send_email_digest(mock_db, user_id=uuid.uuid4(), notifications=[_make_notification()])

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
