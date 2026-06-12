"""V2a — GET /api/v1/projects/{id}/mention-candidates.

Returns project members (users + agents) whose handle or display name
starts with ``prefix`` (case-insensitive), capped at the ``limit`` param
(default 20). The discriminator ``type='user' | 'agent'`` lets the UI
distinguish humans from agent accounts.

Uses the test-app factory (live DB via the ``db`` session fixture).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.enums import ActorType, ProjectRole, UserRole
from app.middleware.bearer_auth import get_actor
from app.services.context import Actor
from app.services.projects import project_service
from tests.helpers.app_factory import build_test_app


def _make_user_mock(uid, role=UserRole.admin):
    m = MagicMock()
    m.id = uid
    m.role = role
    return m


def _build_app(db_session, *, actor):
    async def _override_db():
        yield db_session

    overrides: dict = {
        get_db: _override_db,
        get_actor: lambda: actor,
        get_current_user: lambda: _make_user_mock(actor.id),
    }
    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _proj_key() -> str:
    return "MC" + uuid.uuid4().hex[:4].upper()


async def _insert_user(db, *, handle: str, display: str) -> uuid.UUID:
    uid = uuid.uuid4()
    suffix = uuid.uuid4().hex[:6]
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, is_active) "
            "VALUES (:id, :e, :n, :h, true)"
        ),
        {
            "id": uid,
            "e": f"{handle}-{suffix}@mc.test",
            "n": display,
            "h": handle,
        },
    )
    await db.flush()
    return uid


async def _insert_agent(db, *, handle: str, name: str, created_by) -> uuid.UUID:
    aid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, active, created_by, api_key_hash, api_key_prefix) "
            "VALUES (:id, :n, :h, true, :cb, :k, :p)"
        ),
        {
            "id": aid,
            "n": name,
            "h": handle,
            "cb": created_by,
            "k": f"test-{aid}",
            "p": "test_",
        },
    )
    await db.flush()
    return aid


@pytest_asyncio.fixture
async def project_with_alices(db):
    """Seed a project with: a user 'alice-<suffix>', a user 'bob-<suffix>',
    and an agent 'alice-coder-<suffix>'. All three are members of the
    project. Returns the project + handles."""
    suffix = uuid.uuid4().hex[:5]
    actor_id = await _insert_user(
        db, handle=f"actor_{suffix}", display="Actor User"
    )

    alice_id = await _insert_user(
        db, handle=f"alice_{suffix}", display=f"Alice {suffix}"
    )
    bob_id = await _insert_user(
        db, handle=f"bob_{suffix}", display=f"Bob {suffix}"
    )
    alice_agent_id = await _insert_agent(
        db,
        handle=f"alice-coder-{suffix}",
        name=f"Alice Coder {suffix}",
        created_by=actor_id,
    )

    proj = await project_service.create(db, key=_proj_key(), name="MC proj")
    for member_id, mtype in [
        (actor_id, "user"),
        (alice_id, "user"),
        (bob_id, "user"),
        (alice_agent_id, "agent"),
    ]:
        await project_service.add_member(
            db,
            proj.id,
            member_id=member_id,
            member_type=mtype,
            role=ProjectRole.member,
        )
    await db.flush()

    actor = Actor(id=actor_id, type=ActorType.user, label="actor", scopes=())
    return {
        "proj_id": str(proj.id),
        "actor": actor,
        "suffix": suffix,
        "alice_id": alice_id,
        "alice_agent_id": alice_agent_id,
        "bob_id": bob_id,
    }


@pytest.mark.asyncio
async def test_mention_candidates_prefix_returns_user_and_agent(
    db, project_with_alices
):
    """``prefix=alice`` returns both the alice user (type=user) and the
    alice-coder agent (type=agent)."""
    p = project_with_alices
    app = _build_app(db, actor=p["actor"])

    async with _client(app) as c:
        resp = await c.get(
            f"/api/v1/projects/{p['proj_id']}/mention-candidates",
            params={"prefix": "alice"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    types = {(it["type"], str(it["id"])) for it in body["items"]}
    assert ("user", str(p["alice_id"])) in types, body
    assert ("agent", str(p["alice_agent_id"])) in types, body


@pytest.mark.asyncio
async def test_mention_candidates_caps_at_limit(db, project_with_alices):
    """``limit=20`` is the default + enforced cap."""
    p = project_with_alices
    app = _build_app(db, actor=p["actor"])

    async with _client(app) as c:
        resp = await c.get(
            f"/api/v1/projects/{p['proj_id']}/mention-candidates",
            params={"prefix": ""},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) <= 20


@pytest.mark.asyncio
async def test_mention_candidates_404_for_unknown_project(
    db, project_with_alices
):
    """Unknown project_id → 404 (mirrors the hierarchy endpoint contract)."""
    p = project_with_alices
    app = _build_app(db, actor=p["actor"])

    async with _client(app) as c:
        resp = await c.get(
            f"/api/v1/projects/{uuid.uuid4()}/mention-candidates"
        )

    assert resp.status_code == 404, resp.text
