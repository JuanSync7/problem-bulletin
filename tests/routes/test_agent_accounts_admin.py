"""Tests for the admin agent-accounts router (Task R3)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.enums import ActorType, UserRole
from app.middleware.bearer_auth import get_admin_actor
from app.models.user import User
from app.routes.admin.agent_accounts import router as agent_accounts_router
from app.services.context import Actor


def _build_app(db_session, admin_actor: Actor):
    app = FastAPI()
    app.include_router(agent_accounts_router, prefix="/api")

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_admin_actor] = lambda: admin_actor
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin(db):
    user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@x",
        display_name="Admin",
        role=UserRole.admin,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return Actor(id=user.id, type=ActorType.user, label=user.email, scopes=())


@pytest.mark.asyncio
async def test_create_returns_plaintext_key_once(db):
    app = _build_app(db, await _admin(db))
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/agent-accounts",
            json={"name": f"bot-{uuid.uuid4().hex[:6]}", "scopes": ["tickets:write"]},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "api_key" in body
    assert len(body["api_key"]) > 16
    assert body["api_key_prefix"] == body["api_key"][:8]
    assert body["scopes"] == ["tickets:write"]
    assert body["active"] is True


@pytest.mark.asyncio
async def test_list_returns_accounts_without_plaintext(db):
    admin = await _admin(db)
    app = _build_app(db, admin)
    async with _client(app) as c:
        await c.post(
            "/api/v1/admin/agent-accounts",
            json={"name": f"lister-{uuid.uuid4().hex[:6]}", "scopes": []},
        )
        resp = await c.get("/api/v1/admin/agent-accounts")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list) and len(items) >= 1
    for it in items:
        assert "api_key" not in it
        assert "api_key_prefix" in it


@pytest.mark.asyncio
async def test_revoke_marks_account_inactive(db):
    admin = await _admin(db)
    app = _build_app(db, admin)
    async with _client(app) as c:
        created = await c.post(
            "/api/v1/admin/agent-accounts",
            json={"name": f"revoke-{uuid.uuid4().hex[:6]}", "scopes": []},
        )
        aid = created.json()["id"]
        resp = await c.post(f"/api/v1/admin/agent-accounts/{aid}/revoke")
        assert resp.status_code == 204
        # Confirm revoked via service
        from sqlalchemy import select
        from app.models.agent_account import AgentAccount
        row = (await db.execute(select(AgentAccount).where(AgentAccount.id == aid))).scalar_one()
        assert row.active is False
        assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_create_validation_empty_name(db):
    app = _build_app(db, await _admin(db))
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/agent-accounts", json={"name": "", "scopes": []}
        )
    # pydantic min_length=1 → 422
    assert resp.status_code == 422
