"""v2.6-WP41 — Tests for watcher-added notification flow.

Exercises the ``TicketService.add_watcher`` -> ``fanout_watcher_added``
path end-to-end against the live Postgres DB fixture. Covers:

  * Adding a non-actor watcher emits exactly one ``ticket_watcher_added``
    row for that recipient.
  * Self-watch (actor == watcher) emits zero rows.
  * Excerpt shape is the stable sentence ``"You were added as a watcher"``.
  * A forced failure inside the per-recipient SAVEPOINT does not roll back
    the parent transaction nor the watcher row.

Mirrors the WP37 / WP40 savepoint-isolation pattern. Targets live
Postgres via the ``db`` fixture from ``tests/services/conftest.py`` —
auto-skipped when DB is unreachable.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.enums import ActorType
from app.models.ticket_notification import TicketNotification
from app.models.ticket_watcher import TicketWatcher
from app.services.context import Actor
from app.services.tickets import TicketService


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}@wp41.test", "n": handle.title()},
    )
    return uid


@pytest_asyncio.fixture
async def users(db):
    alice = await _mk_user(db, handle="alice41")
    bob = await _mk_user(db, handle="bob41")
    await db.flush()
    return {"alice": alice, "bob": bob}


@pytest_asyncio.fixture
async def ticket(db, users):
    """Create a minimal ticket owned by alice and return it."""
    svc = TicketService()
    alice_actor = Actor(
        id=users["alice"], type=ActorType.user, label="alice41", scopes=()
    )
    t = await svc.create(
        db,
        actor=alice_actor,
        title="WP41 ticket",
    )
    await db.flush()
    return t


# ---------------------------------------------------------------------------
# Happy path: watcher != actor → exactly one row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_watcher_emits_one_notification_for_recipient(db, users, ticket):
    """A non-actor watcher receives exactly one ticket_watcher_added row."""
    svc = TicketService()
    alice = users["alice"]  # actor
    bob = users["bob"]      # the new watcher

    actor = Actor(id=alice, type=ActorType.user, label="alice41", scopes=())
    w = await svc.add_watcher(
        db,
        ticket.id,
        watcher_id=bob,
        watcher_type="user",
        actor=actor,
    )
    await db.flush()

    # Watcher row exists.
    assert w.ticket_id == ticket.id
    assert w.watcher_id == bob

    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.kind == "ticket_watcher_added",
                TicketNotification.target_id == ticket.id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    n = rows[0]
    assert n.recipient_type == "user"
    assert n.recipient_id == bob
    assert n.actor_id == alice


# ---------------------------------------------------------------------------
# Self-watch: actor == watcher → zero rows.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_self_watch_emits_no_notification(db, users, ticket):
    """When actor adds themselves as a watcher, no notification is created."""
    svc = TicketService()
    alice = users["alice"]
    actor = Actor(id=alice, type=ActorType.user, label="alice41", scopes=())

    await svc.add_watcher(
        db,
        ticket.id,
        watcher_id=alice,
        watcher_type="user",
        actor=actor,
    )
    await db.flush()

    rows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.kind == "ticket_watcher_added",
                TicketNotification.target_id == ticket.id,
            )
        )
    ).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Excerpt shape — stable, no display-id / title splice.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_excerpt_is_constant_recipient_centric_sentence(db, users, ticket):
    """Excerpt is the literal string ``"You were added as a watcher"``."""
    svc = TicketService()
    actor = Actor(
        id=users["alice"], type=ActorType.user, label="alice41", scopes=()
    )
    await svc.add_watcher(
        db,
        ticket.id,
        watcher_id=users["bob"],
        watcher_type="user",
        actor=actor,
    )
    await db.flush()

    n = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.kind == "ticket_watcher_added",
                TicketNotification.target_id == ticket.id,
            )
        )
    ).scalar_one()
    assert n.excerpt == "You were added as a watcher"
    # The display_id is still on the row for the UI; just not in the excerpt.
    assert n.target_display_id == ticket.display_id


# ---------------------------------------------------------------------------
# SAVEPOINT isolation: forced INSERT failure does not roll back the watcher
# row nor poison the parent TX.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_savepoint_isolates_notification_failure_from_watcher(
    db, users, ticket, monkeypatch
):
    """A forced INSERT error inside fanout_watcher_added does not rollback
    the watcher row, and the parent TX stays usable for subsequent queries.

    Mirrors the wp37/wp40 SAVEPOINT-isolation pattern.
    """
    import app.services.ticket_notifications as mod

    real_pg_insert = mod.pg_insert
    calls = {"n": 0}

    def boom(table):  # noqa: ANN001
        if table is TicketNotification or table is TicketNotification.__table__:
            calls["n"] += 1
            raise RuntimeError("forced insert failure")
        return real_pg_insert(table)

    monkeypatch.setattr(mod, "pg_insert", boom)

    svc = TicketService()
    actor = Actor(
        id=users["alice"], type=ActorType.user, label="alice41", scopes=()
    )

    # Should NOT raise — the SAVEPOINT swallows the failure.
    w = await svc.add_watcher(
        db,
        ticket.id,
        watcher_id=users["bob"],
        watcher_type="user",
        actor=actor,
    )
    await db.flush()

    monkeypatch.setattr(mod, "pg_insert", real_pg_insert)
    assert calls["n"] >= 1, "forced failure path should have been exercised"

    # Watcher row survived the notification failure.
    wrow = (
        await db.execute(
            select(TicketWatcher).where(
                TicketWatcher.ticket_id == ticket.id,
                TicketWatcher.watcher_id == users["bob"],
            )
        )
    ).scalar_one_or_none()
    assert wrow is not None
    assert wrow.id == w.id

    # Parent TX still alive — no notification row was inserted, but the SELECT
    # itself must succeed (i.e. the TX is not in an aborted state).
    nrows = (
        await db.execute(
            select(TicketNotification).where(
                TicketNotification.target_id == ticket.id,
                TicketNotification.kind == "ticket_watcher_added",
            )
        )
    ).scalars().all()
    assert nrows == []
