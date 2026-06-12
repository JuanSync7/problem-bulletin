"""Tests for the /api/ws ticket events channel (G1).

We exercise both the in-process bus and the WebSocket route. The bus path
runs without Postgres; the service-layer integration uses the live-PG
``db`` fixture and the post-commit flush helper directly so we don't need
to drive a real commit (the rollback'd test session would otherwise discard
staged events).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.events import (
    bus,
    discard_session_events,
    flush_session_events,
    stage_event,
)
from tests.helpers.app_factory import build_test_app


def _build_app():
    return build_test_app()


def test_ws_receives_published_event():
    app = _build_app()
    client = TestClient(app)
    with client.websocket_connect("/api/ws") as ws:
        # Give the server a tick to subscribe
        import time
        for _ in range(20):
            if bus.subscriber_count >= 1:
                break
            time.sleep(0.05)
        assert bus.subscriber_count >= 1

        bus.publish(
            {
                "event": "ticket.transitioned",
                "ticket_id": "abc",
                "project_id": None,
                "correlation_id": "test-corr",
                "occurred_at": "2026-05-12T00:00:00Z",
                "payload": {"to_status": "in_progress"},
            }
        )

        msg = ws.receive_json()
        assert msg["event"] == "ticket.transitioned"
        assert msg["ticket_id"] == "abc"
        assert msg["correlation_id"] == "test-corr"


def test_bus_drops_when_no_subscribers():
    # publish to empty bus — should not raise
    initial = bus.subscriber_count
    bus.publish({"event": "noop"})
    assert bus.subscriber_count == initial


@pytest.mark.asyncio
async def test_stage_and_flush_session_events(db):
    """stage_event accumulates per-session; flush publishes; discard drops."""
    received: list[dict] = []
    q = bus.subscribe()
    try:
        stage_event(
            db, "ticket.created",
            ticket_id=uuid.uuid4(),
            correlation_id="c1",
            payload={"hello": "world"},
        )
        # not yet published
        assert q.empty()
        flushed = flush_session_events(db)
        assert flushed == 1
        evt = q.get_nowait()
        received.append(evt)
        assert evt["event"] == "ticket.created"
        assert evt["correlation_id"] == "c1"

        # discard path
        stage_event(db, "ticket.created", ticket_id=uuid.uuid4())
        discard_session_events(db)
        assert flush_session_events(db) == 0
    finally:
        bus.unsubscribe(q)


@pytest.mark.asyncio
async def test_service_create_stages_event(db, agent_actor):
    """TicketService.create stages a ticket.created envelope."""
    from sqlalchemy import text as _sa_text
    from app.services.tickets import TicketService

    # Ticket.reporter_id has an FK to users(id); insert a stub user row first.
    await db.execute(
        _sa_text("INSERT INTO users (id, email, display_name) "
                 "VALUES (:id, :email, :name)"),
        {"id": agent_actor.id, "email": f"u-{agent_actor.id}@x.test", "name": "agent"},
    )
    await db.flush()

    q = bus.subscribe()
    try:
        svc = TicketService()
        ticket = await svc.create(
            db, actor=agent_actor, title="ws-event-smoke",
            correlation_id="corr-svc-1",
        )
        flush_session_events(db)
        evt = q.get_nowait()
        assert evt["event"] == "ticket.created"
        assert evt["ticket_id"] == str(ticket.id)
        assert evt["correlation_id"] == "corr-svc-1"
        assert evt["payload"]["ticket"]["display_id"] == ticket.computed_display_id
    finally:
        bus.unsubscribe(q)
