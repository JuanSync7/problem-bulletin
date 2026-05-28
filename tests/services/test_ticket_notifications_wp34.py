"""v2.5-WP34 Part B — Tests for dual-channel publish on agent-kind mark_read.

When a user marks an agent's notification as read, the realtime hub should
receive two publishes:
  1. To (agent, agent_id) — existing behaviour.
  2. To (user, owner_user_id) — new WP34 behaviour, so the user's own WS
     gets the event even if that session isn't subscribed to agent keys.

Both payloads should carry the ``agent_id`` field so the Sidebar can
distinguish them from user-inbox reads and avoid double-decrement.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models.ticket_notification import TicketNotification
from app.services.ticket_notifications import TicketNotificationService


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}@wp34.test", "n": handle.title()},
    )
    return uid


async def _mk_agent(db, *, name: str, owner_id: uuid.UUID) -> uuid.UUID:
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, api_key_hash, api_key_prefix, scopes, created_by) "
            "VALUES (:id, :n, :h, 'hash', 'pfx', ARRAY[]::text[], :owner)"
        ),
        {"id": aid, "n": name, "h": name.lower().replace(" ", "_"), "owner": owner_id},
    )
    return aid


async def _mk_notif_raw(
    db,
    *,
    kind: str,
    recipient_type: str,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
    target_display_id: str = "TKT-34",
    is_read: bool = False,
) -> uuid.UUID:
    nid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            "target_type, target_id, target_display_id, is_read) "
            "VALUES (:id, :kind, :rt, :r, 'user', :a, 'ticket', :tid, :did, :read)"
        ),
        {
            "id": nid,
            "kind": kind,
            "rt": recipient_type,
            "r": recipient_id,
            "a": actor_id,
            "tid": target_id,
            "did": target_display_id,
            "read": is_read,
        },
    )
    return nid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def actors(db):
    alice = await _mk_user(db, handle="alice_wp34")
    carol = await _mk_user(db, handle="carol_wp34")
    await db.flush()
    return {"alice": alice, "carol": carol}


# ---------------------------------------------------------------------------
# Part B: mark_read agent kind → dual publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_agent_publishes_to_both_agent_and_owner_channels(db, actors):
    """mark_read(agent) publishes notification_read to both agent channel
    and owner-user channel, both with agent_id field set."""
    owner_id = actors["alice"]
    agent_id = await _mk_agent(db, name="AliceBotWP34", owner_id=owner_id)
    target_id = uuid.uuid4()

    nid = await _mk_notif_raw(
        db,
        kind="ticket_assigned",
        recipient_type="agent",
        recipient_id=agent_id,
        actor_id=actors["carol"],
        target_id=target_id,
    )
    await db.flush()

    published_calls: list[tuple] = []

    async def _mock_publish(recipient_type: str, recipient_id: uuid.UUID, payload: dict):
        published_calls.append((recipient_type, recipient_id, payload))

    mock_hub = MagicMock()
    mock_hub.publish = _mock_publish

    svc = TicketNotificationService()

    # Patch the realtime module so the local import inside mark_read gets the mock.
    import sys
    import types

    fake_realtime = types.ModuleType("app.services.realtime")
    fake_realtime.hub = mock_hub  # type: ignore[attr-defined]

    old_mod = sys.modules.get("app.services.realtime")
    sys.modules["app.services.realtime"] = fake_realtime
    try:
        row = await svc.mark_read(
            db,
            notification_id=nid,
            recipient_type="agent",
            recipient_id=agent_id,
            recipient_kind="agent",
            acting_user_id=owner_id,
        )
        # Drain any pending asyncio tasks so mock_publish coroutines run.
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        if old_mod is not None:
            sys.modules["app.services.realtime"] = old_mod
        else:
            del sys.modules["app.services.realtime"]

    assert row.is_read is True

    # Should have two publishes: agent channel + user/owner channel.
    recipient_types = [(c[0], c[1]) for c in published_calls]
    assert ("agent", agent_id) in recipient_types, (
        f"Expected publish to agent channel, got: {recipient_types}"
    )
    assert ("user", owner_id) in recipient_types, (
        f"Expected publish to user/owner channel, got: {recipient_types}"
    )

    # Both payloads must carry agent_id.
    for rtype, rid, payload in published_calls:
        assert payload.get("agent_id") == str(agent_id), (
            f"Publish to ({rtype}, {rid}) missing agent_id: {payload}"
        )


@pytest.mark.asyncio
async def test_mark_all_read_agent_publishes_to_both_channels(db, actors):
    """mark_all_read(agent) publishes notification_read_all to both
    agent channel and owner-user channel."""
    owner_id = actors["alice"]
    agent_id = await _mk_agent(db, name="AliceBulkBotWP34", owner_id=owner_id)

    # Insert 2 unread agent notifications.
    for _ in range(2):
        await _mk_notif_raw(
            db,
            kind="ticket_mention",
            recipient_type="agent",
            recipient_id=agent_id,
            actor_id=actors["carol"],
            target_id=uuid.uuid4(),
        )
    await db.flush()

    published_calls: list[tuple] = []

    async def _mock_publish(recipient_type: str, recipient_id: uuid.UUID, payload: dict):
        published_calls.append((recipient_type, recipient_id, payload))

    mock_hub = MagicMock()
    mock_hub.publish = _mock_publish

    svc = TicketNotificationService()

    import sys
    import types

    fake_realtime = types.ModuleType("app.services.realtime")
    fake_realtime.hub = mock_hub  # type: ignore[attr-defined]

    old_mod = sys.modules.get("app.services.realtime")
    sys.modules["app.services.realtime"] = fake_realtime
    try:
        count = await svc.mark_all_read(
            db,
            recipient_type="agent",
            recipient_id=agent_id,
            recipient_kind="agent",
            acting_user_id=owner_id,
        )
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        if old_mod is not None:
            sys.modules["app.services.realtime"] = old_mod
        else:
            del sys.modules["app.services.realtime"]

    assert count == 2

    recipient_types = [(c[0], c[1]) for c in published_calls]
    assert ("agent", agent_id) in recipient_types
    assert ("user", owner_id) in recipient_types

    for rtype, rid, payload in published_calls:
        assert payload.get("agent_id") == str(agent_id)
        assert payload["count"] == 2


def test_null_created_by_guard_in_source():
    """Structural guard: service code checks ``owner_id is not None`` before
    publishing to the user channel (WP34 Part B spec requirement).

    Rather than fighting the live DB to create a NULL row (which a17 prevents),
    we verify the guard exists in the source. This is a contract test — if
    the implementation removes the guard, this test will fail.
    """
    import inspect
    from app.services import ticket_notifications as tns

    source = inspect.getsource(tns.TicketNotificationService.mark_read)
    # The guard must be present so NULL created_by rows don't crash mark_read.
    assert "owner_id is not None" in source, (
        "mark_read must guard 'owner_id is not None' before user-channel publish"
    )


@pytest.mark.asyncio
async def test_mark_read_agent_null_created_by_skips_owner_publish_gracefully(db, actors):
    """When AgentAccount.created_by is effectively None (simulated via mocked
    resolve), the owner-channel publish is skipped and mark_read succeeds.

    We use a subclass of TicketNotificationService that overrides the inner
    agent lookup to return a fake agent with created_by=None, while leaving
    the real ownership-check and mark-read logic intact.
    """
    import sys
    import types
    from unittest.mock import AsyncMock as _AsyncMock, patch as _patch
    from sqlalchemy import select as _select
    from app.models.ticket_notification import TicketNotification
    from app.models.agent_account import AgentAccount

    owner_id = actors["alice"]
    agent_id = await _mk_agent(db, name="NullOwnerBotWP34", owner_id=owner_id)
    target_id = uuid.uuid4()

    nid = await _mk_notif_raw(
        db,
        kind="ticket_assigned",
        recipient_type="agent",
        recipient_id=agent_id,
        actor_id=actors["carol"],
        target_id=target_id,
    )
    await db.flush()

    published_calls: list[tuple] = []

    async def _mock_publish(recipient_type: str, recipient_id: uuid.UUID, payload: dict):
        published_calls.append((recipient_type, recipient_id, payload))

    mock_hub = MagicMock()
    mock_hub.publish = _mock_publish

    class _FakeAgentNullOwner:
        id = agent_id
        created_by = None  # simulates pre-a17 legacy state

    class _SubSvc(TicketNotificationService):
        """Override _resolve_owned_agent_ids and the inner AgentAccount lookup."""

        @staticmethod
        async def _resolve_owned_agent_ids(session, user_id):
            return [agent_id]  # ownership check passes

    # Patch the db.execute call that happens INSIDE mark_read when it does
    # select(AgentAccount).where(AgentAccount.id == ...) to return our fake agent.
    original_execute = db.execute

    async def _patched_execute(stmt, *args, **kwargs):
        from sqlalchemy.orm import DeclarativeBase
        # Detect AgentAccount SELECT by checking the froms.
        try:
            froms = stmt.get_final_froms() if hasattr(stmt, "get_final_froms") else []
            for f in froms:
                if hasattr(f, "name") and f.name == "agent_accounts":
                    # This is the AgentAccount lookup — return our fake row.
                    fake_agent = _FakeAgentNullOwner()
                    mock_r = MagicMock()

                    async def _scalar(*a, **kw):
                        return fake_agent

                    mock_r.scalar_one_or_none = _scalar
                    return mock_r
        except Exception:
            pass
        return await original_execute(stmt, *args, **kwargs)

    svc = _SubSvc()

    fake_realtime = types.ModuleType("app.services.realtime")
    fake_realtime.hub = mock_hub  # type: ignore[attr-defined]

    old_mod = sys.modules.get("app.services.realtime")
    sys.modules["app.services.realtime"] = fake_realtime
    db.execute = _patched_execute
    try:
        row = await svc.mark_read(
            db,
            notification_id=nid,
            recipient_type="agent",
            recipient_id=agent_id,
            recipient_kind="agent",
            acting_user_id=owner_id,
        )
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        db.execute = original_execute
        if old_mod is not None:
            sys.modules["app.services.realtime"] = old_mod
        else:
            del sys.modules["app.services.realtime"]

    assert row.is_read is True

    # Agent-channel publish must have happened.
    recipient_types = [(c[0], c[1]) for c in published_calls]
    assert ("agent", agent_id) in recipient_types

    # Owner-channel publish must be skipped (created_by is None).
    user_publishes = [c for c in published_calls if c[0] == "user"]
    assert len(user_publishes) == 0, (
        f"Expected no user-channel publish when created_by is None, got: {user_publishes}"
    )
