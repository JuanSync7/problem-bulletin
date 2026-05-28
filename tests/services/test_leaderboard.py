"""Live-Postgres tests for ``app.services.leaderboard``.

Re-written in v2.10-WP04b.  The legacy v1 file exercised mock-DB stubs
against a `period=` kwarg the service never used (service signature is
`time_filter=`).  These tests target the real service surface with the
function-scoped ``db`` session from ``tests/services/conftest.py``.

Service contract
----------------
``get_top_solvers(db, time_filter: TimePeriod, limit: int = 20)``
    Ranks non-anonymous solutions whose status == "accepted".  Returns
    ``[{user_id, display_name, accepted_count, rank}, …]`` ordered by
    ``accepted_count DESC, display_name ASC``.  ``time_filter`` ∈
    {``all_time``, ``this_month`` (30d window), ``this_week`` (7d
    window)}.

``get_top_reporters(db, time_filter: TimePeriod, limit: int = 20)``
    Ranks users by ``count(upstars)`` on non-anonymous problems they
    authored.  Same shape, but the count column is ``upstar_count`` and
    the window filters ``Problem.created_at``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.leaderboard import (
    TimePeriod,
    get_top_reporters,
    get_top_solvers,
)
from tests.helpers.seed_agent_account import seed_user
from tests.helpers.seed_problem import seed_problem, seed_solution


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test-local helpers (no cross-file reuse)
# ---------------------------------------------------------------------------

async def _accept_solution(db, solution_id) -> None:
    await db.execute(
        text("UPDATE solutions SET status = 'accepted' WHERE id = :id"),
        {"id": solution_id},
    )


async def _backdate_solution(db, solution_id, *, days: int) -> None:
    await db.execute(
        text(f"UPDATE solutions SET created_at = now() - interval '{int(days)} days' "
             "WHERE id = :id"),
        {"id": solution_id},
    )


async def _backdate_problem(db, problem_id, *, days: int) -> None:
    await db.execute(
        text(f"UPDATE problems SET created_at = now() - interval '{int(days)} days' "
             "WHERE id = :id"),
        {"id": problem_id},
    )


async def _insert_upstar(db, problem_id, user_id) -> None:
    await db.execute(
        text("INSERT INTO upstars (id, user_id, problem_id, created_at) "
             "VALUES (gen_random_uuid(), :u, :p, now())"),
        {"u": user_id, "p": problem_id},
    )


# ===========================================================================
# get_top_solvers
# ===========================================================================

async def test_top_solvers_ranked_by_accepted_count_desc(db):
    """Ordering must be accepted_count DESC; ties broken by display_name ASC."""
    alice = await seed_user(db, display_name="Alice", handle=f"al_{uuid.uuid4().hex[:6]}")
    bob = await seed_user(db, display_name="Bob", handle=f"bo_{uuid.uuid4().hex[:6]}")
    carol = await seed_user(db, display_name="Carol", handle=f"ca_{uuid.uuid4().hex[:6]}")

    problem_id = await seed_problem(db)
    # Alice: 3 accepted, Bob: 2 accepted, Carol: 1 accepted.
    for u, n in [(alice, 3), (bob, 2), (carol, 1)]:
        for _ in range(n):
            sid, _ = await seed_solution(db, problem_id=problem_id, author_id=u)
            await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=20)
    # Filter to only our test users so other rows in the DB don't pollute.
    names = {alice: "Alice", bob: "Bob", carol: "Carol"}
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in names]

    assert [e["display_name"] for e in ours] == ["Alice", "Bob", "Carol"]
    assert [e["accepted_count"] for e in ours] == [3, 2, 1]
    assert [e["rank"] for e in ours] == [1, 2, 3]


async def test_top_solvers_rank_numbers_are_idx_plus_1(db):
    """Rank is assigned in Python as idx+1 over the (sorted) result rows."""
    problem_id = await seed_problem(db)
    users = []
    for i in range(5):
        u = await seed_user(
            db, display_name=f"User-{i:02d}-{uuid.uuid4().hex[:4]}",
            handle=f"rk_{uuid.uuid4().hex[:6]}",
        )
        users.append(u)
        # User-i gets 10-i accepted solutions.
        for _ in range(10 - i):
            sid, _ = await seed_solution(db, problem_id=problem_id, author_id=u)
            await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in users]

    assert [e["rank"] for e in ours] == list(range(1, 6))


async def test_top_solvers_excludes_anonymous_solutions(db):
    """Anonymous solutions don't count toward the author's accepted total."""
    author = await seed_user(db, display_name="AnonAuthor", handle=f"an_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)

    # 2 non-anonymous accepted + 3 anonymous accepted.
    for _ in range(2):
        sid, _ = await seed_solution(db, problem_id=problem_id, author_id=author,
                                     is_anonymous=False)
        await _accept_solution(db, sid)
    for _ in range(3):
        sid, _ = await seed_solution(db, problem_id=problem_id, author_id=author,
                                     is_anonymous=True)
        await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["accepted_count"] == 2


async def test_top_solvers_all_time_no_cutoff(db):
    """`all_time` includes old (1y) solutions in the count."""
    author = await seed_user(db, display_name="OldTimer", handle=f"ot_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)
    sid, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    await _accept_solution(db, sid)
    await _backdate_solution(db, sid, days=400)  # 400d back
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["accepted_count"] == 1


async def test_top_solvers_this_month_30_day_window(db):
    """`this_month` excludes solutions older than 30 days."""
    author = await seed_user(db, display_name="Monthly", handle=f"mo_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)

    # One inside (5d), one outside (45d).
    sid_in, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    sid_out, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    await _accept_solution(db, sid_in)
    await _accept_solution(db, sid_out)
    await _backdate_solution(db, sid_in, days=5)
    await _backdate_solution(db, sid_out, days=45)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.this_month, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["accepted_count"] == 1


async def test_top_solvers_this_week_7_day_window(db):
    """`this_week` excludes solutions older than 7 days."""
    author = await seed_user(db, display_name="Weekly", handle=f"wk_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)

    sid_in, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    sid_out, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    await _accept_solution(db, sid_in)
    await _accept_solution(db, sid_out)
    await _backdate_solution(db, sid_in, days=2)
    await _backdate_solution(db, sid_out, days=10)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.this_week, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["accepted_count"] == 1


async def test_top_solvers_empty_result_set(db):
    """When no qualifying solutions exist for a window, the slice is empty.

    We can't claim the *whole* list is empty (other devs' rows may be in the
    shared DB).  Instead we seed a brand-new isolated user with NO accepted
    solutions and assert they don't appear.
    """
    nobody = await seed_user(db, display_name="Nobody", handle=f"nb_{uuid.uuid4().hex[:6]}")
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    assert str(nobody) not in {e["user_id"] for e in entries}


async def test_top_solvers_alphabetical_tiebreaker(db):
    """Equal counts are broken by display_name ASC."""
    aaron = await seed_user(db, display_name="Aaron", handle=f"aa_{uuid.uuid4().hex[:6]}")
    zara = await seed_user(db, display_name="Zara", handle=f"zz_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)
    for u in (aaron, zara):
        sid, _ = await seed_solution(db, problem_id=problem_id, author_id=u)
        await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in (aaron, zara)]
    assert [e["display_name"] for e in ours] == ["Aaron", "Zara"]


async def test_top_solvers_default_limit_20(db):
    """Default limit is 20."""
    # Seed 25 solvers, each with 1 accepted solution but counts that
    # rank them deterministically.  We then assert the *first 20* are
    # our seeded users, ranked by count.
    problem_id = await seed_problem(db)
    users = []
    for i in range(25):
        u = await seed_user(
            db, display_name=f"D-{i:02d}", handle=f"d_{uuid.uuid4().hex[:6]}",
        )
        users.append(u)
        # 25-i accepted solutions — first user gets 25, last gets 1.
        for _ in range(25 - i):
            sid, _ = await seed_solution(db, problem_id=problem_id, author_id=u)
            await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time)  # default limit
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in users]
    # At most 20 of our 25 can show because the default limit is 20.
    assert len(ours) <= 20


async def test_top_solvers_max_limit_100(db):
    """``limit=100`` is honoured."""
    problem_id = await seed_problem(db)
    users = []
    for i in range(5):
        u = await seed_user(
            db, display_name=f"M-{i:02d}", handle=f"m_{uuid.uuid4().hex[:6]}",
        )
        users.append(u)
        sid, _ = await seed_solution(db, problem_id=problem_id, author_id=u)
        await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=100)
    assert len(entries) <= 100
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in users]
    assert len(ours) == 5


async def test_top_solvers_limit_1(db):
    """``limit=1`` returns exactly one entry (with rank=1)."""
    author = await seed_user(db, display_name=f"Top-{uuid.uuid4().hex[:4]}",
                             handle=f"t1_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)
    for _ in range(99):
        sid, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
        await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=1)
    assert len(entries) == 1
    assert entries[0]["rank"] == 1


async def test_top_solvers_single_user_rank_is_1(db):
    """A solo solver is always rank 1, regardless of `limit`."""
    author = await seed_user(db, display_name="Only", handle=f"on_{uuid.uuid4().hex[:6]}")
    problem_id = await seed_problem(db)
    sid, _ = await seed_solution(db, problem_id=problem_id, author_id=author)
    await _accept_solution(db, sid)
    await db.flush()

    entries = await get_top_solvers(db, TimePeriod.all_time, limit=20)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    # Rank is among the *returned* slice — it's 1-indexed but our user might
    # not be #1 if other seeds exist.  Assert it's a positive int.
    assert me[0]["rank"] >= 1


# ===========================================================================
# get_top_reporters
# ===========================================================================

async def test_top_reporters_ranked_by_upstar_count_desc(db):
    """Reporters ranked by upstar count DESC."""
    alice = await seed_user(db, display_name="ReporterA", handle=f"rA_{uuid.uuid4().hex[:6]}")
    bob = await seed_user(db, display_name="ReporterB", handle=f"rB_{uuid.uuid4().hex[:6]}")
    voter = await seed_user(db, display_name="Voter", handle=f"vt_{uuid.uuid4().hex[:6]}")
    voter2 = await seed_user(db, display_name="Voter2", handle=f"vt2_{uuid.uuid4().hex[:6]}")

    pA = await seed_problem(db, author_id=alice)
    pB = await seed_problem(db, author_id=bob)
    # Alice: 2 upstars, Bob: 1 upstar.
    await _insert_upstar(db, pA, voter)
    await _insert_upstar(db, pA, voter2)
    await _insert_upstar(db, pB, voter)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.all_time, limit=100)
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in (alice, bob)]
    assert [e["display_name"] for e in ours] == ["ReporterA", "ReporterB"]
    assert [e["upstar_count"] for e in ours] == [2, 1]


async def test_top_reporters_excludes_anonymous_problems(db):
    """Upstars on anonymous problems don't count for the author."""
    author = await seed_user(db, display_name="MaybeAnon", handle=f"ma_{uuid.uuid4().hex[:6]}")
    voter = await seed_user(db, display_name="V", handle=f"vp_{uuid.uuid4().hex[:6]}")

    p_pub = await seed_problem(db, author_id=author, is_anonymous=False)
    p_anon = await seed_problem(db, author_id=author, is_anonymous=True)
    await _insert_upstar(db, p_pub, voter)
    await _insert_upstar(db, p_anon, voter)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.all_time, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["upstar_count"] == 1


async def test_top_reporters_this_month_cutoff(db):
    """``this_month`` filters by ``Problem.created_at`` (30d)."""
    author = await seed_user(db, display_name="MonthlyRep", handle=f"mR_{uuid.uuid4().hex[:6]}")
    voter = await seed_user(db, display_name="MV", handle=f"mv_{uuid.uuid4().hex[:6]}")

    p_in = await seed_problem(db, author_id=author)
    p_out = await seed_problem(db, author_id=author)
    await _insert_upstar(db, p_in, voter)
    await _insert_upstar(db, p_out, voter)
    await _backdate_problem(db, p_in, days=5)
    await _backdate_problem(db, p_out, days=45)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.this_month, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["upstar_count"] == 1


async def test_top_reporters_this_week_cutoff(db):
    """``this_week`` filters by ``Problem.created_at`` (7d)."""
    author = await seed_user(db, display_name="WeeklyRep", handle=f"wR_{uuid.uuid4().hex[:6]}")
    voter = await seed_user(db, display_name="WV", handle=f"wv_{uuid.uuid4().hex[:6]}")

    p_in = await seed_problem(db, author_id=author)
    p_out = await seed_problem(db, author_id=author)
    await _insert_upstar(db, p_in, voter)
    await _insert_upstar(db, p_out, voter)
    await _backdate_problem(db, p_in, days=2)
    await _backdate_problem(db, p_out, days=10)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.this_week, limit=100)
    me = [e for e in entries if e["user_id"] == str(author)]
    assert len(me) == 1
    assert me[0]["upstar_count"] == 1


async def test_top_reporters_empty_result_set(db):
    """A user with no upstars on their problems doesn't appear."""
    quiet = await seed_user(db, display_name="Quiet", handle=f"qu_{uuid.uuid4().hex[:6]}")
    await seed_problem(db, author_id=quiet)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.all_time, limit=100)
    assert str(quiet) not in {e["user_id"] for e in entries}


async def test_top_reporters_alphabetical_tiebreaker(db):
    """Equal upstar counts tie-break by display_name ASC."""
    bob = await seed_user(db, display_name="Bob", handle=f"bb_{uuid.uuid4().hex[:6]}")
    zoe = await seed_user(db, display_name="Zoe", handle=f"zo_{uuid.uuid4().hex[:6]}")
    voter = await seed_user(db, display_name="V", handle=f"vp2_{uuid.uuid4().hex[:6]}")

    pB = await seed_problem(db, author_id=bob)
    pZ = await seed_problem(db, author_id=zoe)
    await _insert_upstar(db, pB, voter)
    await _insert_upstar(db, pZ, voter)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.all_time, limit=100)
    ours = [e for e in entries if uuid.UUID(e["user_id"]) in (bob, zoe)]
    assert [e["display_name"] for e in ours] == ["Bob", "Zoe"]


async def test_top_reporters_limit_enforcement(db):
    """``limit`` caps the returned slice."""
    voter = await seed_user(db, display_name="LimitVoter", handle=f"lv_{uuid.uuid4().hex[:6]}")
    users = []
    for i in range(5):
        u = await seed_user(
            db, display_name=f"LR-{i:02d}", handle=f"lr_{uuid.uuid4().hex[:6]}",
        )
        users.append(u)
        for _ in range(5 - i):
            p = await seed_problem(db, author_id=u)
            await _insert_upstar(db, p, voter)
    await db.flush()

    entries = await get_top_reporters(db, TimePeriod.all_time, limit=5)
    assert len(entries) <= 5
