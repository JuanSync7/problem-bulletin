"""v2.29-S4 — Service tests for the Bounty space (bounties).

Live-DB tests via the ``db`` fixture from ``tests/services/conftest.py``.
Covers: create as user, agent create forbidden, claim/unclaim by user and
by agent, award by poster only, award requires claimed, withdraw only
open, and the status-filtered listing.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.enums import ActorType
from app.services.bounties import BountyService
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError


# ---------------------------------------------------------------------------
# DB helpers (same idiom as tests/services/test_share_posts_v229.py)
# ---------------------------------------------------------------------------


async def _mk_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_active) "
            "VALUES (:id, :e, :n, true)"
        ),
        {"id": uid, "e": f"{handle}-{uid.hex[:6]}@x.test", "n": handle.title()},
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
        {"id": aid, "n": name, "h": f"{name.lower()}-{aid.hex[:6]}", "owner": owner_id},
    )
    return aid


@pytest_asyncio.fixture
async def poster_actor(db) -> Actor:
    uid = await _mk_user(db, handle="poster")
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="poster@x.test", scopes=())


@pytest_asyncio.fixture
async def claimer_actor(db) -> Actor:
    uid = await _mk_user(db, handle="claimer")
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="claimer@x.test", scopes=())


@pytest_asyncio.fixture
async def bot_actor(db, poster_actor) -> Actor:
    aid = await _mk_agent(db, name="BountyBot", owner_id=poster_actor.id)
    await db.flush()
    return Actor(id=aid, type=ActorType.agent, label="bountybot", scopes=())


async def _mk_bounty(db, actor, **kw):
    svc = BountyService()
    defaults = dict(title="Fix the flaky test", description="It flakes.", points=50)
    defaults.update(kw)
    return await svc.create_bounty(db, actor, **defaults)


# ---------------------------------------------------------------------------
# create_bounty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_bounty_as_user(db, poster_actor):
    b = await _mk_bounty(db, poster_actor)
    assert b.id is not None
    assert b.status == "open"
    assert b.points == 50
    assert b.poster_user_id == poster_actor.id
    assert b.claimant_id is None
    assert b.claimant_type is None
    assert b.claimed_at is None
    assert b.awarded_at is None


@pytest.mark.asyncio
async def test_create_bounty_as_agent_forbidden(db, bot_actor):
    svc = BountyService()
    with pytest.raises(PermissionDeniedError):
        await svc.create_bounty(
            db, bot_actor, title="Agents cannot post", description="", points=10
        )


@pytest.mark.asyncio
async def test_create_bounty_writes_audit_row(db, poster_actor):
    b = await _mk_bounty(db, poster_actor)
    res = await db.execute(
        text(
            "SELECT action FROM audit_log "
            "WHERE entity_type = 'bounty' AND entity_id = :eid"
        ),
        {"eid": b.id},
    )
    actions = [r[0] for r in res.all()]
    assert "create" in actions


# ---------------------------------------------------------------------------
# claim / unclaim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_and_unclaim_by_user(db, poster_actor, claimer_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)

    claimed = await svc.claim(db, claimer_actor, b.id)
    assert claimed.status == "claimed"
    assert claimed.claimant_id == claimer_actor.id
    assert claimed.claimant_type == "user"
    assert claimed.claimed_at is not None

    reopened = await svc.unclaim(db, claimer_actor, b.id)
    assert reopened.status == "open"
    assert reopened.claimant_id is None
    assert reopened.claimant_type is None
    assert reopened.claimed_at is None


@pytest.mark.asyncio
async def test_claim_by_agent(db, poster_actor, bot_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    claimed = await svc.claim(db, bot_actor, b.id)
    assert claimed.status == "claimed"
    assert claimed.claimant_id == bot_actor.id
    assert claimed.claimant_type == "agent"


@pytest.mark.asyncio
async def test_claim_not_open_raises_value_error(db, poster_actor, claimer_actor, bot_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    await svc.claim(db, claimer_actor, b.id)
    with pytest.raises(ValueError):
        await svc.claim(db, bot_actor, b.id)


@pytest.mark.asyncio
async def test_claim_missing_raises_lookup_error(db, claimer_actor):
    svc = BountyService()
    with pytest.raises(LookupError):
        await svc.claim(db, claimer_actor, uuid.uuid4())


@pytest.mark.asyncio
async def test_unclaim_by_non_claimant_forbidden(db, poster_actor, claimer_actor, bot_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    await svc.claim(db, claimer_actor, b.id)
    with pytest.raises(PermissionDeniedError):
        await svc.unclaim(db, bot_actor, b.id)


# ---------------------------------------------------------------------------
# award
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_by_poster(db, poster_actor, claimer_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    await svc.claim(db, claimer_actor, b.id)

    awarded = await svc.award(db, poster_actor, b.id)
    assert awarded.status == "awarded"
    assert awarded.awarded_at is not None
    assert awarded.claimant_id == claimer_actor.id

    res = await db.execute(
        text(
            "SELECT action FROM audit_log "
            "WHERE entity_type = 'bounty' AND entity_id = :eid"
        ),
        {"eid": b.id},
    )
    actions = {r[0] for r in res.all()}
    assert {"create", "claim", "award"} <= actions


@pytest.mark.asyncio
async def test_award_by_non_poster_forbidden(db, poster_actor, claimer_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    await svc.claim(db, claimer_actor, b.id)
    with pytest.raises(PermissionDeniedError):
        await svc.award(db, claimer_actor, b.id)


@pytest.mark.asyncio
async def test_award_requires_claimed(db, poster_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    with pytest.raises(ValueError):
        await svc.award(db, poster_actor, b.id)


# ---------------------------------------------------------------------------
# withdraw
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_only_open(db, poster_actor, claimer_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)

    withdrawn = await svc.withdraw(db, poster_actor, b.id)
    assert withdrawn.status == "withdrawn"

    b2 = await _mk_bounty(db, poster_actor, title="Second")
    await svc.claim(db, claimer_actor, b2.id)
    with pytest.raises(ValueError):
        await svc.withdraw(db, poster_actor, b2.id)


@pytest.mark.asyncio
async def test_withdraw_by_non_poster_forbidden(db, poster_actor, claimer_actor):
    svc = BountyService()
    b = await _mk_bounty(db, poster_actor)
    with pytest.raises(PermissionDeniedError):
        await svc.withdraw(db, claimer_actor, b.id)


# ---------------------------------------------------------------------------
# list_bounties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bounties_status_filter_and_order(db, poster_actor, claimer_actor):
    svc = BountyService()
    b1 = await _mk_bounty(db, poster_actor, title="One")
    b2 = await _mk_bounty(db, poster_actor, title="Two")
    b3 = await _mk_bounty(db, poster_actor, title="Three")
    await svc.claim(db, claimer_actor, b2.id)

    items, total = await svc.list_bounties(db, limit=50, offset=0)
    ids = [b.id for b in items]
    assert ids.index(b3.id) < ids.index(b1.id)
    assert total >= 3

    items, total = await svc.list_bounties(db, status="claimed", limit=50, offset=0)
    ids = {b.id for b in items}
    assert b2.id in ids
    assert b1.id not in ids and b3.id not in ids
    assert total == 1

    items, _ = await svc.list_bounties(db, status="open", limit=50, offset=0)
    ids = {b.id for b in items}
    assert b1.id in ids and b3.id in ids and b2.id not in ids
