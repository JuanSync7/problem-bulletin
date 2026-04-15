"""
Tests for app.services.leaderboard — get_top_solvers and get_top_reporters.

Derived from: docs/AION_BULLETIN_TEST_DOCS.md lines 2150–2270
Phase 0 contracts:
  - Valid tracks: solvers, reporters only.
  - Valid periods: all_time, this_month, this_week only.
  - Anonymous content (is_anonymous=True) excluded in SQL before aggregation.
  - limit in [1, 100]; default 20.
  - Rank is assigned in Python as idx + 1 on an ordered, pre-limited result.
  - Solvers: cutoff applies to Solution.created_at.
  - Reporters: cutoff applies to Problem.created_at.
  - all_time applies no date filter (cutoff=None).
  - Tiebreaker is User.display_name ASC.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.leaderboard import get_top_solvers, get_top_reporters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_solver_row(*, user_id=None, display_name="Alice", accepted_count=5):
    """Return a mock row as returned by the solvers query."""
    row = MagicMock()
    row.user_id = user_id or uuid.uuid4()
    row.display_name = display_name
    row.accepted_count = accepted_count
    return row


def _make_reporter_row(*, user_id=None, display_name="Bob", upstar_count=10):
    """Return a mock row as returned by the reporters query."""
    row = MagicMock()
    row.user_id = user_id or uuid.uuid4()
    row.display_name = display_name
    row.upstar_count = upstar_count
    return row


def _db_result(rows):
    """Wrap rows in a mock that simulates AsyncSession.execute().all()."""
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value = result
    return result


# ---------------------------------------------------------------------------
# get_top_solvers — basic ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_ranked_by_accepted_count_desc(mock_db):
    """Entries must be ordered by accepted_count DESC; rank starts at 1."""
    rows = [
        _make_solver_row(display_name="Alice", accepted_count=10),
        _make_solver_row(display_name="Bob", accepted_count=7),
        _make_solver_row(display_name="Carol", accepted_count=3),
    ]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    assert len(entries) == 3
    # Rank assignment: idx + 1
    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks == [1, 2, 3]
    # Descending accepted_count order preserved from SQL
    counts = [getattr(e, "accepted_count", None) or e.get("accepted_count") for e in entries]
    assert counts == [10, 7, 3]


@pytest.mark.asyncio
async def test_top_solvers_rank_numbers_are_idx_plus_1(mock_db):
    """Rank values must be exactly [1, 2, ..., N] with no gaps."""
    rows = [_make_solver_row(display_name=f"User{i}", accepted_count=10 - i) for i in range(5)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks == list(range(1, 6))


# ---------------------------------------------------------------------------
# get_top_solvers — anonymous exclusion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_excludes_anonymous_solutions(mock_db):
    """Only non-anonymous solutions are counted; is_anonymous=False filter in SQL.

    The mock simulates the SQL having already applied the filter.
    We verify the service produces the correct accepted_count from the pre-filtered result.
    """
    # SQL returns only the 2 non-anonymous solutions aggregated
    rows = [_make_solver_row(display_name="Alice", accepted_count=2)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    assert len(entries) == 1
    accepted = getattr(entries[0], "accepted_count", None) or entries[0].get("accepted_count")
    assert accepted == 2


# ---------------------------------------------------------------------------
# get_top_reporters — basic ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_reporters_ranked_by_upstar_count_desc(mock_db):
    """Reporter entries ordered by upstar_count DESC; rank starts at 1."""
    rows = [
        _make_reporter_row(display_name="Alice", upstar_count=20),
        _make_reporter_row(display_name="Bob", upstar_count=15),
    ]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_reporters(mock_db, period="all_time", limit=20)

    assert len(entries) == 2
    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks == [1, 2]
    counts = [getattr(e, "upstar_count", None) or e.get("upstar_count") for e in entries]
    assert counts == [20, 15]


@pytest.mark.asyncio
async def test_top_reporters_excludes_anonymous_problems(mock_db):
    """Anonymous problems' upstars are excluded in SQL before aggregation.

    The mock returns the pre-filtered aggregate (only non-anonymous problem's upstars).
    """
    rows = [_make_reporter_row(display_name="Alice", upstar_count=10)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_reporters(mock_db, period="all_time", limit=20)

    assert len(entries) == 1
    upstars = getattr(entries[0], "upstar_count", None) or entries[0].get("upstar_count")
    assert upstars == 10


# ---------------------------------------------------------------------------
# Time filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_all_time_no_cutoff(mock_db):
    """all_time period must execute a query (no date filter applied)."""
    mock_db.execute.return_value = _db_result([_make_solver_row()])

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    mock_db.execute.assert_called_once()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_top_solvers_this_month_30_day_window(mock_db):
    """this_month period executes a query with a 30-day rolling cutoff."""
    mock_db.execute.return_value = _db_result([_make_solver_row()])

    entries = await get_top_solvers(mock_db, period="this_month", limit=20)

    mock_db.execute.assert_called_once()
    assert isinstance(entries, list)


@pytest.mark.asyncio
async def test_top_solvers_this_week_7_day_window(mock_db):
    """this_week period executes a query with a 7-day rolling cutoff."""
    mock_db.execute.return_value = _db_result([_make_solver_row()])

    entries = await get_top_solvers(mock_db, period="this_week", limit=20)

    mock_db.execute.assert_called_once()
    assert isinstance(entries, list)


@pytest.mark.asyncio
async def test_top_reporters_this_month_cutoff(mock_db):
    """this_month applies cutoff to Problem.created_at for reporters track."""
    mock_db.execute.return_value = _db_result([_make_reporter_row()])

    entries = await get_top_reporters(mock_db, period="this_month", limit=20)

    mock_db.execute.assert_called_once()
    assert isinstance(entries, list)


@pytest.mark.asyncio
async def test_top_reporters_this_week_cutoff(mock_db):
    """this_week applies cutoff to Problem.created_at for reporters track."""
    mock_db.execute.return_value = _db_result([_make_reporter_row()])

    entries = await get_top_reporters(mock_db, period="this_week", limit=20)

    mock_db.execute.assert_called_once()
    assert isinstance(entries, list)


# ---------------------------------------------------------------------------
# Empty result set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_empty_result_set(mock_db):
    """No qualifying activity returns an empty entries list without error."""
    mock_db.execute.return_value = _db_result([])

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    assert entries == []


@pytest.mark.asyncio
async def test_top_reporters_empty_result_set(mock_db):
    """No qualifying activity returns an empty entries list without error."""
    mock_db.execute.return_value = _db_result([])

    entries = await get_top_reporters(mock_db, period="all_time", limit=20)

    assert entries == []


# ---------------------------------------------------------------------------
# Alphabetical tiebreaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_alphabetical_tiebreaker(mock_db):
    """Users with equal accepted_count are ordered by display_name ASC (SQL-level).

    The service receives rows already sorted by SQL; we verify rank assignment
    honours the incoming order without re-sorting.
    """
    rows = [
        _make_solver_row(display_name="Alice", accepted_count=5),   # alphabetically first
        _make_solver_row(display_name="Zara", accepted_count=5),    # alphabetically last
    ]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    names = [getattr(e, "display_name", None) or e.get("display_name") for e in entries]
    assert names[0] == "Alice"
    assert names[1] == "Zara"
    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks == [1, 2]


@pytest.mark.asyncio
async def test_top_reporters_alphabetical_tiebreaker(mock_db):
    """Equal upstar_count: display_name ASC tiebreaker order preserved from SQL."""
    rows = [
        _make_reporter_row(display_name="Bob", upstar_count=10),
        _make_reporter_row(display_name="Zoe", upstar_count=10),
    ]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_reporters(mock_db, period="all_time", limit=20)

    names = [getattr(e, "display_name", None) or e.get("display_name") for e in entries]
    assert names[0] == "Bob"
    assert names[1] == "Zoe"


# ---------------------------------------------------------------------------
# Limit enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_default_limit_20(mock_db):
    """Default limit is 20; service passes limit=20 to query when not specified."""
    rows = [_make_solver_row(display_name=f"User{i}") for i in range(20)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time")

    assert len(entries) == 20


@pytest.mark.asyncio
async def test_top_solvers_max_limit_100(mock_db):
    """limit=100 is accepted; service returns up to 100 entries."""
    rows = [_make_solver_row(display_name=f"User{i}", accepted_count=100 - i) for i in range(100)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=100)

    assert len(entries) == 100
    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks[0] == 1
    assert ranks[-1] == 100


@pytest.mark.asyncio
async def test_top_solvers_limit_1(mock_db):
    """limit=1 returns exactly one entry with rank=1."""
    rows = [_make_solver_row(display_name="TopUser", accepted_count=99)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=1)

    assert len(entries) == 1
    rank = getattr(entries[0], "rank", None) or entries[0].get("rank")
    assert rank == 1


@pytest.mark.asyncio
async def test_top_reporters_limit_enforcement(mock_db):
    """Limit is respected for reporters track as well."""
    rows = [_make_reporter_row(display_name=f"User{i}", upstar_count=50 - i) for i in range(5)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_reporters(mock_db, period="all_time", limit=5)

    assert len(entries) == 5
    ranks = [getattr(e, "rank", None) or e.get("rank") for e in entries]
    assert ranks == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Single-user result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_solvers_single_user_rank_is_1(mock_db):
    """A single result entry must have rank=1 regardless of limit."""
    rows = [_make_solver_row(display_name="OnlyUser", accepted_count=3)]
    mock_db.execute.return_value = _db_result(rows)

    entries = await get_top_solvers(mock_db, period="all_time", limit=20)

    assert len(entries) == 1
    rank = getattr(entries[0], "rank", None) or entries[0].get("rank")
    assert rank == 1
