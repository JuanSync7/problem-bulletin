"""v2.29-S4 — Route tests for /api/v1/bounties.

Mirrors tests/routes/test_share_posts_v229.py: dependency-override the
``get_db`` and ``get_actor`` seams against a live-DB session.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor | None):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    overrides: dict = {get_db: _override_db}
    if actor is not None:
        overrides[_ga] = lambda: actor
    return build_test_app(dependency_overrides=overrides)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _mk_user(db, name) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{name}-{uid.hex[:6]}@x.test", "n": name},
    )
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def poster(db):
    uid = await _mk_user(db, "bounty-poster")
    return Actor(id=uid, type=ActorType.user, label="bounty-poster", scopes=())


@pytest_asyncio.fixture
async def claimer(db):
    uid = await _mk_user(db, "bounty-claimer")
    return Actor(id=uid, type=ActorType.user, label="bounty-claimer", scopes=())


@pytest.mark.asyncio
async def test_create_claim_award_round_trip(db, poster, claimer):
    poster_app = _build_app(db, actor=poster)
    claimer_app = _build_app(db, actor=claimer)

    async with _client(poster_app) as pc, _client(claimer_app) as cc:
        # Create (poster)
        resp = await pc.post(
            "/api/v1/bounties",
            json={
                "title": "Document the deploy runbook",
                "description": "Make it a one-pager.",
                "points": 100,
            },
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["title"] == "Document the deploy runbook"
        assert created["points"] == 100
        assert created["status"] == "open"
        assert created["claimant_label"] is None
        bounty_id = created["id"]

        # List shows it
        resp = await pc.get("/api/v1/bounties?status=open")
        assert resp.status_code == 200, resp.text
        assert bounty_id in [b["id"] for b in resp.json()["items"]]

        # Claim (claimer)
        resp = await cc.post(f"/api/v1/bounties/{bounty_id}/claim")
        assert resp.status_code == 200, resp.text
        claimed = resp.json()
        assert claimed["status"] == "claimed"
        assert claimed["claimant_label"] is not None

        # Award (poster)
        resp = await pc.post(f"/api/v1/bounties/{bounty_id}/award")
        assert resp.status_code == 200, resp.text
        awarded = resp.json()
        assert awarded["status"] == "awarded"
        assert awarded["awarded_at"] is not None

        # Detail reflects final state
        resp = await pc.get(f"/api/v1/bounties/{bounty_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "awarded"


@pytest.mark.asyncio
async def test_double_claim_409(db, poster, claimer):
    poster_app = _build_app(db, actor=poster)
    claimer_app = _build_app(db, actor=claimer)
    async with _client(poster_app) as pc, _client(claimer_app) as cc:
        resp = await pc.post(
            "/api/v1/bounties",
            json={"title": "One claim only", "points": 10},
        )
        assert resp.status_code == 201, resp.text
        bounty_id = resp.json()["id"]

        resp = await cc.post(f"/api/v1/bounties/{bounty_id}/claim")
        assert resp.status_code == 200

        # Poster tries to claim the already-claimed bounty -> 409.
        resp = await pc.post(f"/api/v1/bounties/{bounty_id}/claim")
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_award_by_non_poster_403(db, poster, claimer):
    poster_app = _build_app(db, actor=poster)
    claimer_app = _build_app(db, actor=claimer)
    async with _client(poster_app) as pc, _client(claimer_app) as cc:
        resp = await pc.post(
            "/api/v1/bounties", json={"title": "Mine to award", "points": 5}
        )
        bounty_id = resp.json()["id"]
        await cc.post(f"/api/v1/bounties/{bounty_id}/claim")

        resp = await cc.post(f"/api/v1/bounties/{bounty_id}/award")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_missing_bounty_404(db, poster):
    app = _build_app(db, actor=poster)
    async with _client(app) as c:
        resp = await c.get(f"/api/v1/bounties/{uuid.uuid4()}")
        assert resp.status_code == 404
        resp = await c.post(f"/api/v1/bounties/{uuid.uuid4()}/claim")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_with_ticket_and_problem_422(db, poster):
    app = _build_app(db, actor=poster)
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/bounties",
            json={
                "title": "Cannot link both",
                "points": 10,
                "ticket_id": str(uuid.uuid4()),
                "problem_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 422
