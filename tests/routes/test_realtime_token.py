"""Tests for POST /api/v1/realtime/token — short-lived WS auth token (WP34 Part A).

All tests build a minimal FastAPI app that overrides the CurrentUser
dependency, so they do not need live Postgres.
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.jwt import (
    ALGORITHM,
    REALTIME_TOKEN_TTL_SECONDS,
    create_realtime_token,
    decode_realtime_token,
)
from app.config import get_settings
from tests.helpers.app_factory import build_test_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, uid: uuid.UUID | None = None):
        self.id = uid or uuid.uuid4()
        self.is_active = True
        self.role = "user"


def _build_app(user: _FakeUser | None = None):
    """Build a fully-wired test app via build_test_app().

    If ``user`` is supplied the ``CurrentUser`` dependency is overridden
    to return it (authenticated).  If ``None``, no override is applied
    so the real dependency path runs (and raises 401 for missing creds).
    """
    overrides: dict = {}
    if user is not None:
        overrides[get_current_user] = lambda: user
    return build_test_app(dependency_overrides=overrides or None)


# ---------------------------------------------------------------------------
# Part A tests: POST /api/v1/realtime/token
# ---------------------------------------------------------------------------


def test_authenticated_user_gets_realtime_token():
    """Authenticated user → 200 with token, expires_at, ttl_seconds."""
    user = _FakeUser()
    client = TestClient(_build_app(user))

    resp = client.post("/api/v1/realtime/token")
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert "token" in data
    assert "expires_at" in data
    assert data["ttl_seconds"] == REALTIME_TOKEN_TTL_SECONDS

    # Decode the token and verify claims.
    settings = get_settings()
    claims = jwt.decode(
        data["token"],
        settings.JWT_SECRET.get_secret_value(),
        algorithms=[ALGORITHM],
    )
    assert claims["sub"] == str(user.id)
    assert claims["purpose"] == "realtime"
    assert "exp" in claims
    assert "iat" in claims

    # exp should be within the expected TTL window (±5s tolerance).
    now = int(time.time())
    assert claims["exp"] <= now + REALTIME_TOKEN_TTL_SECONDS + 5
    assert claims["exp"] >= now + REALTIME_TOKEN_TTL_SECONDS - 5


def test_unauthenticated_returns_401():
    """No credentials → 401."""
    client = TestClient(_build_app(user=None), raise_server_exceptions=False)
    resp = client.post("/api/v1/realtime/token")
    assert resp.status_code == 401


def test_token_purpose_claim_is_realtime():
    """Decoded realtime token has purpose='realtime'."""
    user = _FakeUser()
    token, _ = create_realtime_token(user)
    sub = decode_realtime_token(token)
    assert sub == str(user.id)


def test_decode_realtime_token_rejects_main_session_token():
    """Main session JWT (no purpose claim) is rejected by decode_realtime_token."""
    from app.auth.jwt import create_access_token
    from jose import JWTError

    user = _FakeUser()
    main_token = create_access_token(user)
    with pytest.raises(JWTError):
        decode_realtime_token(main_token)


# ---------------------------------------------------------------------------
# Part A tests: WS endpoint enforcement
# ---------------------------------------------------------------------------


def test_ws_connect_with_realtime_token_succeeds():
    """WS ?token= with realtime token → handshake succeeds, receives ready."""
    from unittest.mock import AsyncMock, patch

    user = _FakeUser()
    token, _ = create_realtime_token(user)
    app = _build_app(user)

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [])),
    ):
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/realtime/ws?token={token}") as ws:
            msg = ws.receive_json()
            assert msg == {"type": "ready"}


def test_ws_connect_with_main_session_token_rejected():
    """WS ?token= with main session JWT (no purpose claim) → 4401 close."""
    from app.auth.jwt import create_access_token

    user = _FakeUser()
    main_token = create_access_token(user)
    app = _build_app(user)

    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(Exception):
        # TestClient raises when the server closes with a non-101 code.
        with client.websocket_connect(
            f"/api/v1/realtime/ws?token={main_token}"
        ) as ws:
            ws.receive_json()


def test_ws_connect_cookie_path_still_works():
    """Cookie auth on WS (main session token) remains unaffected — no purpose check."""
    from unittest.mock import AsyncMock, patch
    from app.auth.jwt import create_access_token

    user = _FakeUser()
    cookie_token = create_access_token(user)
    app = _build_app(user)

    with patch(
        "app.routes.realtime_ws._get_user_and_agent_ids",
        new=AsyncMock(return_value=(user, [])),
    ):
        client = TestClient(app, cookies={"access_token": cookie_token})
        with client.websocket_connect("/api/v1/realtime/ws") as ws:
            msg = ws.receive_json()
            assert msg == {"type": "ready"}
