"""Tests for app.middleware.bearer_auth.get_actor (Task R1)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.jwt import create_access_token
from app.database import get_db
from app.enums import ActorType, UserRole
from app.middleware.bearer_auth import get_actor
from app.models.user import User
from app.services.agent_accounts import AgentAccountService


def _make_app(db_session):
    app = FastAPI()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    @app.get("/whoami")
    async def whoami(actor=Depends(get_actor)):
        return {"id": str(actor.id), "type": actor.type.value, "label": actor.label}

    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_missing_credentials_returns_401(db):
    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get("/whoami")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_agent_api_key_resolves_to_agent_actor(db):
    svc = AgentAccountService()
    name = f"bot-{uuid.uuid4().hex[:8]}"
    account, plaintext = await svc.create_account(db, name=name, scopes=["tickets:read"])
    await db.flush()

    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get("/whoami", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == ActorType.agent.value
    assert body["id"] == str(account.id)
    assert body["label"] == name


@pytest.mark.asyncio
async def test_bearer_invalid_token_returns_401(db):
    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/whoami",
            headers={"Authorization": "Bearer not-a-real-key-abc123xyz-nope"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_jwt_resolves_to_user_actor(db):
    user = User(
        email=f"alice-{uuid.uuid4().hex[:6]}@example.com",
        display_name="Alice",
        role=UserRole.user,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    token = create_access_token(user)

    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == ActorType.user.value
    assert body["id"] == str(user.id)


@pytest.mark.asyncio
async def test_bearer_rejected_on_ws_upgrade(db):
    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get(
            "/whoami",
            headers={
                "Authorization": "Bearer some-key",
                "Upgrade": "websocket",
                "Connection": "upgrade",
            },
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cookie_token_resolves_user_actor(db):
    user = User(
        email=f"bob-{uuid.uuid4().hex[:6]}@example.com",
        display_name="Bob",
        role=UserRole.user,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    token = create_access_token(user)

    app = _make_app(db)
    async with _client(app) as c:
        resp = await c.get("/whoami", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(user.id)
