"""WP10 — Stable-total cursor mode for /api/search/v2.

The cursor payload carries a snapshot ``t`` (total) field minted on the
first page. Subsequent pages return the snapshot value verbatim so the
UI total counter does not drift mid-scroll, even when rows are inserted
or deleted between requests.

Tests:
  1. Insert a hit between page 1 and page 2 → page 2's ``total`` equals
     page 1's, not the live count.
  2. A legacy cursor lacking the ``t`` snapshot still works — total falls
     back to the live count.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services._pagination import encode_signed_cursor
from app.services.search_multi import (
    _cursor_secret,
    search_entities,
)
from tests.services.conftest import db, pg_engine  # noqa: F401


# ---------------------------------------------------------------------------
# Seed helpers (mirror test_search_v2_cursors.py)
# ---------------------------------------------------------------------------

async def _seed_user(db, *, handle: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, 'WP10 user', :handle)"
        ),
        {"id": uid, "email": f"{uid}@wp10.test", "handle": handle},
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_stays_stable_when_row_inserted_between_pages(db):
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp10_{uuid.uuid4().hex[:8]}")
    for i in range(4):
        await _seed_problem(db, author_id=uid, title=f"{token} problem {i}")
    await db.flush()

    # Page 1.
    p1 = await search_entities(db, token, entity="problems", limit=2)
    arm1 = p1["problems"]
    assert arm1["total"] == 4
    assert arm1["next_cursor"] is not None

    # Insert a new matching row before fetching page 2.
    await _seed_problem(db, author_id=uid, title=f"{token} interloper")
    await db.flush()

    # Live count is now 5, but page 2 must still report 4 (snapshot).
    p2 = await search_entities(
        db,
        token,
        entity="problems",
        limit=2,
        problems_cursor=arm1["next_cursor"],
    )
    arm2 = p2["problems"]
    assert arm2["total"] == 4, (
        f"expected stable total=4 from cursor snapshot, got {arm2['total']}"
    )


@pytest.mark.asyncio
async def test_legacy_cursor_without_snapshot_falls_back_to_live_count(db):
    """A cursor minted before WP10 (no ``t`` field) must still work; the
    response total falls back to the live count rather than crashing."""
    token = uuid.uuid4().hex[:12]
    uid = await _seed_user(db, handle=f"wp10b_{uuid.uuid4().hex[:8]}")
    ids = []
    for i in range(4):
        pid = await _seed_problem(db, author_id=uid, title=f"{token} problem {i}")
        ids.append(pid)
    await db.flush()

    # Get page 1 to discover the seek tuple of the second-to-last hit.
    p1 = await search_entities(db, token, entity="problems", limit=2)
    arm1 = p1["problems"]
    last_item = arm1["items"][-1]

    # Mint a legacy-shaped cursor (no "t" key) using the same seek tuple.
    legacy_cursor = encode_signed_cursor(
        "problems",
        {"rank": float(last_item["rank"]), "id": str(last_item["id"])},
        secret=_cursor_secret(),
    )

    p2 = await search_entities(
        db,
        token,
        entity="problems",
        limit=2,
        problems_cursor=legacy_cursor,
    )
    arm2 = p2["problems"]
    # No snapshot → falls back to live count, which is still 4 here.
    assert arm2["total"] == 4
    # And page 2 returned the remaining items (some subset of the seeded set).
    assert len(arm2["items"]) >= 1
