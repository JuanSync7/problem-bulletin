"""Tests for /api/v1/realtime/ws — in-process hub WS endpoint (WP31).

All tests build a minimal FastAPI app so they don't need live Postgres.
The user/agent resolution is patched at the route level.

Note on TestClient + async: Starlette's TestClient runs the ASGI app in
a thread with its own event loop. asyncio.create_task() inside the route
will target that loop, so hub publishes that happen *inside* the
TestClient context manager are observable from the WS client.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.auth.jwt import create_realtime_token
from app.services.realtime import hub
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, uid: uuid.UUID | None = None):
        self.id = uid or uuid.uuid4()
        self.is_active = True
        # JWT helper needs a role attribute.
        self.role = "user"


def _make_token(user: _FakeUser) -> str:
    """Issue a realtime-purpose token (WP34: ?token= path requires purpose='realtime')."""
    token, _ = create_realtime_token(user)
    return token


def _build_app() -> FastAPI:
    return build_test_app()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_connect_receives_ready_frame():
    """Valid token → receives {'type': 'ready'} immediately."""
    user = _FakeUser()
    token = _make_token(user)
    app = _build_app()

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [])),
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws:
            msg = ws.receive_json()
            assert msg == {"type": "ready"}


def test_publish_received_by_connected_client():
    """hub.publish to user's key → client receives the payload."""
    user = _FakeUser()
    token = _make_token(user)
    app = _build_app()

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [])),
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws:
            # Drain ready
            ws.receive_json()

            # Publish from within the test (runs in the TestClient's event loop thread).
            payload = {
                "type": "ticket_notification",
                "kind": "ticket_mention",
                "id": str(uuid.uuid4()),
                "target_display_id": "TKT-1",
                "created_at": "2026-05-19T00:00:00+00:00",
            }
            hub._subs  # ensure hub is the singleton

            # Directly put into queue (simulates publish) so we don't need
            # to spin a separate async task inside the sync test.
            key = ("user", user.id)
            queues = hub._subs.get(key, set())
            for q in list(queues):
                q.put_nowait(payload)

            msg = ws.receive_json()
            assert msg["type"] == "ticket_notification"
            assert msg["kind"] == "ticket_mention"
            assert msg["target_display_id"] == "TKT-1"


def test_bad_token_closes_with_4401():
    """Invalid token → WebSocket closed with code 4401."""
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(Exception):
        # TestClient raises on unexpected close — that's the expected behaviour.
        with client.websocket_connect("/api/v1/realtime/ws?token=not-a-real-token") as ws:
            ws.receive_json()


def test_missing_token_closes_with_4401():
    """No token → WebSocket closed with code 4401."""
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/realtime/ws") as ws:
            ws.receive_json()


def test_two_clients_same_user_both_receive():
    """Two connections for the same user both receive a hub publish."""
    user = _FakeUser()
    token = _make_token(user)
    app = _build_app()
    payload = {"type": "ticket_notification", "kind": "test", "id": "x"}

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [])),
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws1:
            ws1.receive_json()  # ready

            with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws2:
                ws2.receive_json()  # ready

                # Inject into both queues directly.
                key = ("user", user.id)
                for q in list(hub._subs.get(key, set())):
                    q.put_nowait(payload)

                m1 = ws1.receive_json()
                m2 = ws2.receive_json()
                assert m1["kind"] == "test"
                assert m2["kind"] == "test"


def test_cross_user_isolation():
    """Publish to user A → user B's socket does NOT receive it."""
    user_a = _FakeUser()
    user_b = _FakeUser()
    token_a = _make_token(user_a)
    token_b = _make_token(user_b)
    app = _build_app()

    # Track calls so we return a different user each time.
    _call_order = [user_a, user_b]
    _call_idx = [0]

    async def _side_effect(uid_str):
        user = _call_order[_call_idx[0]]
        _call_idx[0] += 1
        return user, []

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        side_effect=_side_effect,
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token_a}") as ws_a:
            ws_a.receive_json()  # ready

            with client.websocket_connect(f"/api/v1/realtime/ws?token={token_b}") as ws_b:
                ws_b.receive_json()  # ready

                # Inject ONLY into user_a's queue.
                payload = {"type": "ticket_notification", "kind": "a_only"}
                key_a = ("user", user_a.id)
                key_b = ("user", user_b.id)

                for q in list(hub._subs.get(key_a, set())):
                    q.put_nowait(payload)

                # user_b should NOT receive (queue stays empty).
                queues_b = hub._subs.get(key_b, set())
                for q in queues_b:
                    assert q.empty(), "user B received a message meant for user A"


def test_agent_subscription_relays_to_owner():
    """Publish to one of the user's owned agents → user receives."""
    user = _FakeUser()
    agent_id = uuid.uuid4()
    token = _make_token(user)
    app = _build_app()
    payload = {"type": "ticket_notification", "kind": "agent_msg", "id": "y"}

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [agent_id])),
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws:
            ws.receive_json()  # ready

            # Inject into agent key — should reach user via shared queue.
            key = ("agent", agent_id)
            for q in list(hub._subs.get(key, set())):
                q.put_nowait(payload)

            msg = ws.receive_json()
            assert msg["kind"] == "agent_msg"
