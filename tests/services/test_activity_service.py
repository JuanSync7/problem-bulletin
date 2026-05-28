"""v2.1-WP7 — TicketService.list_activity tests.

Service-layer coverage for the merged activity feed (transitions ∪
comments ∪ links). Verifies union ordering, agent_step_id passthrough,
and the actor_type/actor_id renaming for comments (author_* → actor_*).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.enums import ActorType, TicketLinkType
from app.services.context import Actor, agent_step_id_var, set_agent_step_id
from app.services.tickets import TicketService


@pytest_asyncio.fixture
async def db_user_actor(db, user_actor) -> Actor:
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": user_actor.id, "e": f"u-{user_actor.id}@x.test"},
    )
    await db.flush()
    return user_actor


@pytest_asyncio.fixture
async def db_agent_actor(db) -> Actor:
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'a')"),
        {"id": uid, "e": f"agent-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.agent, label="claude-bot", scopes=())


@pytest.mark.asyncio
async def test_transitions_only_default(db, db_user_actor):
    """Default ``include=set()`` yields only transition rows."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="t")
    await svc.transition(
        db, t.id, actor=db_user_actor, target_status="in_progress"
    )
    await svc.add_comment(db, t.id, actor=db_user_actor, body="hi")
    page = await svc.list_activity(db, t.id)
    assert {row["kind"] for row in page["items"]} == {"transition"}
    # create() emits an initial todo transition + the explicit transition.
    assert page["total"] == 2


@pytest.mark.asyncio
async def test_cursor_filters_older_items_only(db, db_user_actor):
    """list_activity with cursor returns only rows strictly older than anchor."""
    from app.services.tickets import _encode_cursor

    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="cursor-test")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_progress")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_review")
    # Get all rows first.
    full = await svc.list_activity(db, t.id)
    all_items = full["items"]
    # Build a cursor from the second item (middle of list).
    if len(all_items) >= 2:
        anchor = all_items[1]  # second newest
        cur = _encode_cursor(anchor["created_at"], anchor["id"])
        paged = await svc.list_activity(db, t.id, cursor=cur)
        # All returned items must be strictly older than anchor.
        for item in paged["items"]:
            assert (item["created_at"], str(item["id"])) < (
                anchor["created_at"],
                str(anchor["id"]),
            )


@pytest.mark.asyncio
async def test_total_populated_on_every_page(db, db_user_actor):
    """total is populated on every page (v2.6-WP45) and matches the
    include-filtered union size."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="total-test")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_progress")
    page_one = await svc.list_activity(db, t.id)
    assert page_one["total"] == len(page_one["items"])
    full_total = page_one["total"]
    # Second page (even a dummy cursor that returns empty) should still
    # carry the unchanged total — same predicate, count form.
    from app.services.tickets import _encode_cursor
    from datetime import datetime, timezone
    import uuid

    fake_cursor = _encode_cursor(datetime.now(timezone.utc), uuid.uuid4())
    page_two = await svc.list_activity(db, t.id, cursor=fake_cursor)
    assert page_two["total"] == full_total


@pytest.mark.asyncio
async def test_total_reflects_include_filter(db, db_user_actor):
    """total reflects the include-set predicate (filter)."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="filter-total")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_progress")
    transitions_only = await svc.list_activity(db, t.id)
    with_comments = await svc.list_activity(db, t.id, include={"comments"})
    # Adding more arms cannot reduce the union count.
    assert with_comments["total"] >= transitions_only["total"]
    # And the count matches the actual rows returned (within first page).
    assert transitions_only["total"] == len(transitions_only["items"])


@pytest.mark.asyncio
async def test_merged_feed_ordered_desc(db, db_user_actor):
    """include=comments,links yields all three kinds, ordered DESC."""
    svc = TicketService()
    a = await svc.create(db, actor=db_user_actor, title="A")
    b = await svc.create(db, actor=db_user_actor, title="B")
    await svc.transition(
        db, a.id, actor=db_user_actor, target_status="in_progress"
    )
    await svc.add_comment(db, a.id, actor=db_user_actor, body="merged")
    await svc.link(
        db,
        actor=db_user_actor,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )
    page = await svc.list_activity(
        db, a.id, include={"comments", "links"}
    )
    kinds = {row["kind"] for row in page["items"]}
    assert kinds == {"transition", "comment", "link"}
    timestamps = [row["created_at"] for row in page["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_agent_step_id_passthrough(db, db_user_actor, db_agent_actor):
    """agent_step_id flows through transition + comment + link rows."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="t")
    token = set_agent_step_id("step-abc")
    try:
        await svc.transition(
            db, t.id, actor=db_agent_actor, target_status="in_progress"
        )
    finally:
        agent_step_id_var.reset(token)
    token = set_agent_step_id("step-xyz")
    try:
        await svc.add_comment(db, t.id, actor=db_agent_actor, body="bot")
    finally:
        agent_step_id_var.reset(token)
    page = await svc.list_activity(
        db, t.id, include={"comments"}
    )
    step_ids = {row["agent_step_id"] for row in page["items"]}
    assert "step-abc" in step_ids
    assert "step-xyz" in step_ids


@pytest.mark.asyncio
async def test_union_all_preserves_chronological_order(db, db_user_actor):
    """v2.7-WP50: events from different sources interleave by created_at DESC.

    Creates transitions and comments in an interleaved temporal order and
    asserts the SQL UNION ALL outer ORDER BY weaves them correctly.
    """
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="weave")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_progress")
    await svc.add_comment(db, t.id, actor=db_user_actor, body="c1")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_review")
    await svc.add_comment(db, t.id, actor=db_user_actor, body="c2")
    page = await svc.list_activity(db, t.id, include={"comments"})
    items = page["items"]
    # DESC by created_at — every successive item must be <= the previous.
    timestamps = [row["created_at"] for row in items]
    assert timestamps == sorted(timestamps, reverse=True)
    # Both kinds present — interleaving actually happened.
    assert {row["kind"] for row in items} == {"transition", "comment"}


@pytest.mark.asyncio
async def test_count_query_matches_items(db, db_user_actor):
    """v2.7-WP50: total (COUNT(*) over UNION) equals count of all items
    paged through with a small page size."""
    from app.services.tickets import _encode_cursor

    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="count-pages")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_progress")
    await svc.add_comment(db, t.id, actor=db_user_actor, body="c1")
    await svc.add_comment(db, t.id, actor=db_user_actor, body="c2")
    await svc.transition(db, t.id, actor=db_user_actor, target_status="in_review")

    seen: list[dict] = []
    cursor = None
    declared_total = None
    for _ in range(10):  # safety bound
        page = await svc.list_activity(
            db, t.id, include={"comments"}, limit=2, cursor=cursor
        )
        if declared_total is None:
            declared_total = page["total"]
        else:
            # total is stable across pages.
            assert page["total"] == declared_total
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    # Total returned by COUNT(*) must equal the number of items we paged
    # through across all pages — no duplicates, no gaps.
    assert declared_total == len(seen)


@pytest.mark.asyncio
async def test_filter_predicate_applied_to_union(db, db_user_actor):
    """v2.7-WP50: ``include`` filter excludes arms from both the items
    SELECT and the COUNT(*) subquery — total must shrink when an arm
    is dropped."""
    svc = TicketService()
    a = await svc.create(db, actor=db_user_actor, title="A")
    b = await svc.create(db, actor=db_user_actor, title="B")
    await svc.transition(db, a.id, actor=db_user_actor, target_status="in_progress")
    await svc.add_comment(db, a.id, actor=db_user_actor, body="hi")
    await svc.link(
        db,
        actor=db_user_actor,
        source_id=a.id,
        target_id=b.id,
        link_type=TicketLinkType.blocks,
    )

    all_arms = await svc.list_activity(db, a.id, include={"comments", "links"})
    transitions_only = await svc.list_activity(db, a.id)
    plus_comments = await svc.list_activity(db, a.id, include={"comments"})

    # Dropping arms strictly reduces (or keeps) the union size.
    assert transitions_only["total"] < plus_comments["total"] < all_arms["total"]
    # Items in the filtered page never include excluded kinds.
    assert all(row["kind"] == "transition" for row in transitions_only["items"])
    assert {row["kind"] for row in plus_comments["items"]} <= {
        "transition",
        "comment",
    }


@pytest.mark.asyncio
async def test_comment_actor_field_uniformity(db, db_user_actor):
    """Comments expose actor_type/actor_id (renamed from author_*)."""
    svc = TicketService()
    t = await svc.create(db, actor=db_user_actor, title="t")
    await svc.add_comment(db, t.id, actor=db_user_actor, body="x")
    page = await svc.list_activity(db, t.id, include={"comments"})
    comment_row = next(r for r in page["items"] if r["kind"] == "comment")
    assert comment_row["actor_type"] == "user"
    assert comment_row["actor_id"] == db_user_actor.id
