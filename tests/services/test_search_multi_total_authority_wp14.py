"""v2.11-WP14 — total_authority + refresh_total on /api/search/v2 service layer.

These tests exercise:

* G2 — Arm response includes a ``total_authority`` value ("snapshot" on a
  fresh first page; "snapshot" on subsequent pages that read the cursor
  snapshot; "live" when ``refresh_total=True`` opts out).
* G3 — ``refresh_total=True`` forces a re-count: deleting a matching row
  between page 1 and page 2 yields a smaller ``total`` on page 2 (live),
  not the snapshot.
* G4 — Default behaviour (``refresh_total=False``) preserves the WP10
  stable-total snapshot.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.search_multi import search_entities
from tests.services.conftest import db, pg_engine  # noqa: F401


async def _seed_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, 'WP14 user', :handle)"
        ),
        {"id": uid, "email": f"{uid}@wp14.test", "handle": handle},
    )
    return uid


async def _seed_problem(db, *, author_id, title: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, status, search_vector) "
            "VALUES (:id, :title, 'desc', :author_id, 'open', "
            "        to_tsvector('english', :combined))"
        ),
        {"id": pid, "title": title, "author_id": author_id, "combined": title},
    )
    return pid


@pytest.mark.asyncio
async def test_arm_response_exposes_total_authority_snapshot_default(db):
    """G2 — fresh first page has ``total_authority='snapshot'``."""
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp14a_{uuid.uuid4().hex[:8]}")
    for i in range(3):
        await _seed_problem(db, author_id=uid, title=f"{token} p{i}")
    await db.flush()

    p1 = await search_entities(db, token, entity="problems", limit=2)
    arm = p1["problems"]
    assert arm["total"] == 3
    assert arm["total_authority"] == "snapshot"


@pytest.mark.asyncio
async def test_subsequent_page_inherits_snapshot_authority(db):
    """G2 — page 2 with cursor still reports ``snapshot`` authority."""
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp14b_{uuid.uuid4().hex[:8]}")
    for i in range(4):
        await _seed_problem(db, author_id=uid, title=f"{token} q{i}")
    await db.flush()

    p1 = await search_entities(db, token, entity="problems", limit=2)
    cursor = p1["problems"]["next_cursor"]
    assert cursor is not None

    p2 = await search_entities(
        db, token, entity="problems", limit=2, problems_cursor=cursor
    )
    arm = p2["problems"]
    assert arm["total_authority"] == "snapshot"


@pytest.mark.asyncio
async def test_refresh_total_returns_live_authority_and_live_count(db):
    """G3 — ``refresh_total=True`` re-counts and reports authority=live."""
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp14c_{uuid.uuid4().hex[:8]}")
    ids = []
    for i in range(4):
        pid = await _seed_problem(db, author_id=uid, title=f"{token} r{i}")
        ids.append(pid)
    await db.flush()

    p1 = await search_entities(db, token, entity="problems", limit=2)
    cursor = p1["problems"]["next_cursor"]
    assert p1["problems"]["total"] == 4
    assert cursor is not None

    # Delete one matching row between pages.
    await db.execute(
        text("DELETE FROM problems WHERE id = :id"), {"id": ids[0]}
    )
    await db.flush()

    # With refresh_total=True the response must reflect the LIVE count (3),
    # not the snapshotted 4.
    p2 = await search_entities(
        db,
        token,
        entity="problems",
        limit=2,
        problems_cursor=cursor,
        refresh_total=True,
    )
    arm = p2["problems"]
    assert arm["total"] == 3, f"expected live count=3, got {arm['total']}"
    assert arm["total_authority"] == "live"


@pytest.mark.asyncio
async def test_refresh_total_false_default_preserves_stable_total(db):
    """G4 — without ``refresh_total``, WP10 stable-total snapshot wins."""
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp14d_{uuid.uuid4().hex[:8]}")
    ids = []
    for i in range(4):
        pid = await _seed_problem(db, author_id=uid, title=f"{token} s{i}")
        ids.append(pid)
    await db.flush()

    p1 = await search_entities(db, token, entity="problems", limit=2)
    cursor = p1["problems"]["next_cursor"]
    assert p1["problems"]["total"] == 4

    # Delete a matching row.
    await db.execute(text("DELETE FROM problems WHERE id = :id"), {"id": ids[0]})
    await db.flush()

    # Default refresh_total=False: total remains the snapshot=4.
    p2 = await search_entities(
        db, token, entity="problems", limit=2, problems_cursor=cursor
    )
    arm = p2["problems"]
    assert arm["total"] == 4
    assert arm["total_authority"] == "snapshot"
