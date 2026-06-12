"""v2.29-S7 — Share + Bounty seed assertions for ``app.scripts.seed_demo``.

The S7 seed extends the demo cast with three share posts (two
user-authored, one agent-authored linked to a seeded ticket) and three
bounties walked to ``open`` / ``claimed`` / ``awarded``. These tests
assert the exact shape after one run and idempotency after two.

Same live-Postgres harness as ``test_seed_demo.py``: fixtures come from
the shared services conftest, and the PB subtree plus the S7 rows are
purged before/after each test so the suite stays hermetic. Share posts
and bounties must be purged explicitly — their author/poster FKs are
``ON DELETE SET NULL``, so ``_purge_pb`` alone would leave stale
title-keyed rows that short-circuit the natural-key upserts.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)
from tests.scripts.test_seed_demo import _purge_pb  # noqa: F401

from app.scripts.seed_demo import BOUNTY_TITLES, SHARE_POST_TITLES


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _purge_share_bounty(session: AsyncSession) -> None:
    """Delete the S7 share posts (votes cascade) and bounties by title."""
    await session.execute(
        text("DELETE FROM share_posts WHERE title = ANY(:t)"),
        {"t": list(SHARE_POST_TITLES)},
    )
    await session.execute(
        text("DELETE FROM bounties WHERE title = ANY(:t)"),
        {"t": list(BOUNTY_TITLES)},
    )
    await session.commit()


async def _counts(session: AsyncSession) -> dict[str, int]:
    out: dict[str, int] = {}
    out["share_posts"] = int(
        (
            await session.execute(
                text("SELECT count(*) FROM share_posts WHERE title = ANY(:t)"),
                {"t": list(SHARE_POST_TITLES)},
            )
        ).scalar_one()
    )
    out["share_post_votes"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM share_post_votes WHERE post_id IN "
                    "(SELECT id FROM share_posts WHERE title = ANY(:t))"
                ),
                {"t": list(SHARE_POST_TITLES)},
            )
        ).scalar_one()
    )
    out["bounties"] = int(
        (
            await session.execute(
                text("SELECT count(*) FROM bounties WHERE title = ANY(:t)"),
                {"t": list(BOUNTY_TITLES)},
            )
        ).scalar_one()
    )
    return out


@pytest_asyncio.fixture
async def clean_share_bounty(db):  # noqa: F811 — re-uses imported fixture
    """Strip the PB subtree + S7 rows before AND after each test."""
    await _purge_share_bounty(db)
    await _purge_pb(db)
    yield
    await _purge_share_bounty(db)
    await _purge_pb(db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_seed_creates_share_posts_with_sources_and_votes(
    db, clean_share_bounty,  # noqa: F811
):
    """3 posts: user/user/agent sources, agent post ticket-linked, and
    denormalized upvotes of 0 / 1 / 2 matching the vote rows."""
    from app.scripts.seed_demo import seed

    await seed(db)
    await db.commit()

    rows = (
        await db.execute(
            text(
                "SELECT title, source, author_user_id, author_agent_id, "
                "       ticket_id, upvotes, "
                "       (SELECT count(*) FROM share_post_votes v "
                "        WHERE v.post_id = share_posts.id) AS vote_rows "
                "FROM share_posts WHERE title = ANY(:t)"
            ),
            {"t": list(SHARE_POST_TITLES)},
        )
    ).mappings().all()
    by_title = {r["title"]: r for r in rows}
    assert set(by_title) == set(SHARE_POST_TITLES), by_title.keys()

    alice_post = by_title[SHARE_POST_TITLES[0]]
    bob_post = by_title[SHARE_POST_TITLES[1]]
    agent_post = by_title[SHARE_POST_TITLES[2]]

    assert alice_post["source"] == "user"
    assert alice_post["author_user_id"] is not None
    assert alice_post["upvotes"] == 0
    assert alice_post["vote_rows"] == 0

    assert bob_post["source"] == "user"
    assert bob_post["author_user_id"] is not None
    assert bob_post["upvotes"] == 1  # alice's vote
    assert bob_post["vote_rows"] == 1

    assert agent_post["source"] == "agent"
    assert agent_post["author_agent_id"] is not None
    assert agent_post["author_user_id"] is None
    assert agent_post["ticket_id"] is not None, (
        "agent post must link to a seeded ticket"
    )
    assert agent_post["upvotes"] == 2  # alice + bob
    assert agent_post["vote_rows"] == 2


async def test_seed_creates_bounties_in_three_statuses(
    db, clean_share_bounty,  # noqa: F811
):
    """3 bounties: open (no claimant), claimed (agent claimant + ticket
    + claimed_at), awarded (user claimant + claimed_at + awarded_at)."""
    from app.scripts.seed_demo import seed

    await seed(db)
    await db.commit()

    rows = (
        await db.execute(
            text(
                "SELECT title, status, points, poster_user_id, ticket_id, "
                "       claimant_id, claimant_type, claimed_at, awarded_at "
                "FROM bounties WHERE title = ANY(:t)"
            ),
            {"t": list(BOUNTY_TITLES)},
        )
    ).mappings().all()
    by_title = {r["title"]: r for r in rows}
    assert set(by_title) == set(BOUNTY_TITLES), by_title.keys()

    open_b = by_title[BOUNTY_TITLES[0]]
    claimed_b = by_title[BOUNTY_TITLES[1]]
    awarded_b = by_title[BOUNTY_TITLES[2]]

    assert open_b["status"] == "open"
    assert open_b["points"] == 50
    assert open_b["claimant_id"] is None
    assert open_b["claimed_at"] is None
    assert open_b["awarded_at"] is None

    assert claimed_b["status"] == "claimed"
    assert claimed_b["points"] == 120
    assert claimed_b["claimant_type"] == "agent"
    assert claimed_b["claimant_id"] is not None
    assert claimed_b["ticket_id"] is not None
    assert claimed_b["claimed_at"] is not None
    assert claimed_b["awarded_at"] is None

    assert awarded_b["status"] == "awarded"
    assert awarded_b["points"] == 80
    assert awarded_b["claimant_type"] == "user"
    assert awarded_b["claimant_id"] is not None
    assert awarded_b["claimed_at"] is not None
    assert awarded_b["awarded_at"] is not None


async def test_seed_share_bounty_idempotent(
    db, clean_share_bounty,  # noqa: F811
):
    """A second seed run inserts no new posts, votes, or bounties — and
    crucially does NOT toggle the votes off (counts must be identical,
    not merely the same row totals)."""
    from app.scripts.seed_demo import seed

    await seed(db)
    await db.commit()
    first = await _counts(db)
    assert first == {
        "share_posts": 3,
        "share_post_votes": 3,
        "bounties": 3,
    }, first

    await seed(db)
    await db.commit()
    second = await _counts(db)
    assert second == first, (
        f"idempotency violated: first={first} second={second}"
    )
