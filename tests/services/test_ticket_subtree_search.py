"""S7 — TicketService.get_subtree + .search."""
from __future__ import annotations

import pytest

from app.enums import TicketStatus
from app.services.tickets import TicketService


@pytest.mark.asyncio
async def test_get_subtree_three_levels(db, user_actor):
    """root -> child -> grandchild; expect 3 rows, depths 0/1/2."""
    svc = TicketService()
    root = await svc.create(db, actor=user_actor, title="root")
    child = await svc.create(
        db, actor=user_actor, title="child", parent_id=root.id
    )
    grandchild = await svc.create(
        db, actor=user_actor, title="gc", parent_id=child.id
    )

    rows = await svc.get_subtree(db, root.id)
    assert len(rows) == 3
    depths_by_id = {r["ticket"].id: r["depth"] for r in rows}
    assert depths_by_id[root.id] == 0
    assert depths_by_id[child.id] == 1
    assert depths_by_id[grandchild.id] == 2


@pytest.mark.asyncio
async def test_get_subtree_excludes_soft_deleted(db, user_actor):
    from datetime import datetime, timezone
    svc = TicketService()
    root = await svc.create(db, actor=user_actor, title="root")
    child = await svc.create(
        db, actor=user_actor, title="child", parent_id=root.id
    )
    child.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    rows = await svc.get_subtree(db, root.id)
    assert [r["ticket"].id for r in rows] == [root.id]


@pytest.mark.asyncio
async def test_get_subtree_respects_max_depth(db, user_actor):
    svc = TicketService()
    root = await svc.create(db, actor=user_actor, title="root")
    a = await svc.create(db, actor=user_actor, title="a", parent_id=root.id)
    b = await svc.create(db, actor=user_actor, title="b", parent_id=a.id)
    rows = await svc.get_subtree(db, root.id, max_depth=1)
    ids = {r["ticket"].id for r in rows}
    assert ids == {root.id, a.id}
    assert b.id not in ids


@pytest.mark.asyncio
async def test_search_by_phrase(db, user_actor):
    svc = TicketService()
    apple = await svc.create(db, actor=user_actor, title="apple banana orange")
    other = await svc.create(db, actor=user_actor, title="cherry grape melon")
    # search_tsv is a stored generated column; commit not required since it
    # populates on INSERT and we hit the same TX.
    results = await svc.search(db, query="banana")
    ids = {t.id for t in results}
    assert apple.id in ids
    assert other.id not in ids


@pytest.mark.asyncio
async def test_search_with_label_filter(db, user_actor):
    svc = TicketService()
    a = await svc.create(
        db, actor=user_actor,
        title="auth bug login form",
        labels=["bug", "auth"],
    )
    b = await svc.create(
        db, actor=user_actor,
        title="auth bug signup form",
        labels=["bug"],
    )
    results = await svc.search(db, query="auth", labels=["auth"])
    ids = {t.id for t in results}
    assert a.id in ids
    assert b.id not in ids


@pytest.mark.asyncio
async def test_search_empty_query_falls_through_to_list(db, user_actor):
    svc = TicketService()
    t = await svc.create(db, actor=user_actor, title="x", labels=["xq"])
    results = await svc.search(db, query=None, labels=["xq"])
    assert any(r.id == t.id for r in results)
