"""v2.29-S3 — Service tests for the Share space (share_posts).

Live-DB tests via the ``db`` fixture from ``tests/services/conftest.py``.
Covers: create as user, create as agent, newest-first listing + tag
filter, vote toggle on/off updating the denormalized count, and the
UNIQUE (post_id, voter_id, voter_type) constraint.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.enums import ActorType
from app.services.context import Actor
from app.services.share_posts import SharePostService


# ---------------------------------------------------------------------------
# DB helpers (same idiom as tests/services/test_ticket_notifications_wp25.py)
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
async def alice_actor(db) -> Actor:
    uid = await _mk_user(db, handle="alice")
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="alice@x.test", scopes=())


@pytest_asyncio.fixture
async def bot_actor(db, alice_actor) -> Actor:
    aid = await _mk_agent(db, name="ShareBot", owner_id=alice_actor.id)
    await db.flush()
    return Actor(id=aid, type=ActorType.agent, label="sharebot", scopes=())


# ---------------------------------------------------------------------------
# create_post
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_post_as_user(db, alice_actor):
    svc = SharePostService()
    post = await svc.create_post(
        db,
        alice_actor,
        title="My agent workflow",
        body="I use **claude** for triage.",
        tags=["workflow", "tips"],
    )
    assert post.id is not None
    assert post.source == "user"
    assert post.author_user_id == alice_actor.id
    assert post.author_agent_id is None
    assert post.tags == ["workflow", "tips"]
    assert post.upvotes == 0


@pytest.mark.asyncio
async def test_create_post_as_agent(db, bot_actor):
    svc = SharePostService()
    post = await svc.create_post(
        db,
        bot_actor,
        title="Run summary tips",
        body="Agents can post too.",
        tags=["agents"],
    )
    assert post.source == "agent"
    assert post.author_agent_id == bot_actor.id
    assert post.author_user_id is None


@pytest.mark.asyncio
async def test_create_post_writes_audit_row(db, alice_actor):
    svc = SharePostService()
    post = await svc.create_post(
        db, alice_actor, title="Audited", body="b", tags=[]
    )
    res = await db.execute(
        text(
            "SELECT action FROM audit_log "
            "WHERE entity_type = 'share_post' AND entity_id = :eid"
        ),
        {"eid": post.id},
    )
    actions = [r[0] for r in res.all()]
    assert "create" in actions


# ---------------------------------------------------------------------------
# list_posts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_posts_newest_first_and_tag_filter(db, alice_actor):
    svc = SharePostService()
    p1 = await svc.create_post(
        db, alice_actor, title="First", body="b", tags=["alpha"]
    )
    p2 = await svc.create_post(
        db, alice_actor, title="Second", body="b", tags=["beta"]
    )
    p3 = await svc.create_post(
        db, alice_actor, title="Third", body="b", tags=["alpha", "beta"]
    )

    items, total = await svc.list_posts(db, limit=50, offset=0)
    ids = [p.id for p in items]
    # Newest first: p3 before p2 before p1.
    assert ids.index(p3.id) < ids.index(p2.id) < ids.index(p1.id)
    assert total >= 3

    items, total = await svc.list_posts(db, tag="alpha", limit=50, offset=0)
    ids = {p.id for p in items}
    assert p1.id in ids and p3.id in ids
    assert p2.id not in ids
    assert total == 2


# ---------------------------------------------------------------------------
# toggle_vote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_vote_on_off_updates_count(db, alice_actor, bot_actor):
    svc = SharePostService()
    post = await svc.create_post(
        db, alice_actor, title="Votable", body="b", tags=[]
    )

    voted, upvotes = await svc.toggle_vote(db, bot_actor, post.id)
    assert voted is True
    assert upvotes == 1

    # Second voter increments further.
    voted2, upvotes2 = await svc.toggle_vote(db, alice_actor, post.id)
    assert voted2 is True
    assert upvotes2 == 2

    # Toggle off.
    voted3, upvotes3 = await svc.toggle_vote(db, bot_actor, post.id)
    assert voted3 is False
    assert upvotes3 == 1

    # Denormalized column matches.
    fresh = await svc.get_post(db, post.id)
    assert fresh is not None
    assert fresh.upvotes == 1


@pytest.mark.asyncio
async def test_toggle_vote_missing_post_raises(db, alice_actor):
    svc = SharePostService()
    with pytest.raises(LookupError):
        await svc.toggle_vote(db, alice_actor, uuid.uuid4())


@pytest.mark.asyncio
async def test_vote_unique_constraint(db, alice_actor):
    svc = SharePostService()
    post = await svc.create_post(
        db, alice_actor, title="Unique", body="b", tags=[]
    )
    await svc.toggle_vote(db, alice_actor, post.id)
    await db.flush()

    # A raw duplicate insert must violate UNIQUE (post_id, voter_id, voter_type).
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO share_post_votes "
                    "(post_id, voter_id, voter_type) "
                    "VALUES (:p, :v, 'user')"
                ),
                {"p": post.id, "v": alice_actor.id},
            )
