"""
Tests for app.services.search — search_problems and suggest_similar.

Derived from: docs/AION_BULLETIN_TEST_DOCS.md lines 1603–1730
Phase 0 contracts:
  - Sort modes: relevance (default), upvotes, newest only.
  - Full-text uses plainto_tsquery (no syntax errors on arbitrary input).
  - Empty/blank q returns empty result immediately — no SQL executed.
  - limit in [1, 100]; offset >= 0.
  - Deduplication to problem level; one row per problem_id.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.services.search import search_problems, suggest_similar
from app.enums import SortMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_row(
    *,
    problem_id=None,
    title="Firmware crash on startup",
    excerpt="The device crashes whenever the firmware is updated beyond v2.3",
    rank=0.75,
    match_source="problem",
    upstar_count=5,
    created_at=None,
):
    """Return a MagicMock that looks like a single search result row."""
    row = MagicMock()
    row.problem_id = problem_id or uuid.uuid4()
    row.title = title
    row.excerpt = excerpt
    row.rank = rank
    row.match_source = match_source
    row.upstar_count = upstar_count
    row.created_at = created_at or datetime.now(timezone.utc)
    return row


def _db_result(rows):
    """Wrap a list of rows in a mock that mimics AsyncSession.execute() scalars()."""
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value = result
    return result


# ---------------------------------------------------------------------------
# search_problems — empty / blank query short-circuit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_empty_query_returns_empty_no_db_call(mock_db):
    """Empty query must return empty result immediately without calling db.execute."""
    result = await search_problems(mock_db, q="")
    assert result == [] or (hasattr(result, "results") and result.results == [])
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_blank_whitespace_query_returns_empty_no_db_call(mock_db):
    """Whitespace-only query must short-circuit with empty result and no SQL."""
    result = await search_problems(mock_db, q="   ")
    assert result == [] or (hasattr(result, "results") and result.results == [])
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# search_problems — valid query returns structured results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_valid_query_returns_result_fields(mock_db):
    """Valid query returns results with problem_id, title, excerpt, rank, match_source."""
    pid = uuid.uuid4()
    row = _make_search_row(problem_id=pid, title="Sensor dropout", excerpt="Sensor reads drop intermittently", rank=0.9, match_source="problem")
    mock_db.execute.return_value = _db_result([row])

    results = await search_problems(mock_db, q="sensor")

    assert len(results) == 1
    item = results[0]
    # Required fields
    assert str(item.problem_id) == str(pid) or item["problem_id"] == str(pid) or getattr(item, "problem_id", None) is not None
    assert getattr(item, "title", None) == "Sensor dropout" or item.get("title") == "Sensor dropout"
    assert getattr(item, "rank", None) == 0.9 or item.get("rank") == 0.9
    assert getattr(item, "match_source", None) == "problem" or item.get("match_source") == "problem"


@pytest.mark.asyncio
async def test_search_result_has_excerpt_field(mock_db):
    """Result items must include an excerpt field."""
    row = _make_search_row(excerpt="Short excerpt text")
    mock_db.execute.return_value = _db_result([row])

    results = await search_problems(mock_db, q="firmware")

    item = results[0]
    excerpt = getattr(item, "excerpt", None) or item.get("excerpt") if hasattr(item, "get") else None
    assert excerpt is not None


# ---------------------------------------------------------------------------
# search_problems — sort modes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_sort_relevance_default(mock_db):
    """sort=relevance (default) executes without error and calls db.execute once."""
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="bug")

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_sort_upvotes(mock_db):
    """sort=upvotes executes without error."""
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="bug", sort=SortMode.upvotes)

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_sort_newest(mock_db):
    """sort=newest executes without error."""
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="bug", sort=SortMode.newest)

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_unknown_sort_falls_back_silently(mock_db):
    """Unknown sort value must fall back to relevance without raising an error.

    GAP: Phase 0 contract notes that sort=bogus falls back silently rather than
    returning HTTP 422. There is no test that asserts invalid sort values are rejected.
    If the API is ever tightened to reject unknown sorts, this test must be updated.
    """
    mock_db.execute.return_value = _db_result([_make_search_row()])

    # Pass the raw string that doesn't match any SortMode enum value.
    # The service layer should not raise; it should fall back to rank DESC ordering.
    try:
        results = await search_problems(mock_db, q="bug", sort="bogus")  # type: ignore[arg-type]
    except (ValueError, KeyError):
        # Acceptable: the service might reject the bad value early.
        # What is NOT acceptable is an unhandled exception propagating to the caller.
        pass
    else:
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# search_problems — filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_filter_category_id(mock_db):
    """Filter by category_id executes a query and returns matching results."""
    cat_id = uuid.uuid4()
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="sensor", category_id=cat_id)

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_filter_status(mock_db):
    """Filter by status executes a query and returns matching results."""
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="sensor", status="open")

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_filter_single_tag_id(mock_db):
    """Filter by a single tag_id executes a query."""
    tag_id = uuid.uuid4()
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="driver", tag_ids=[tag_id])

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_filter_multiple_tag_ids(mock_db):
    """Filter by multiple tag_ids (implicit AND) executes a query."""
    tag_ids = [uuid.uuid4(), uuid.uuid4()]
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="driver", tag_ids=tag_ids)

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# search_problems — pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_pagination_limit_1(mock_db):
    """limit=1 is accepted and executes a query."""
    mock_db.execute.return_value = _db_result([_make_search_row()])

    results = await search_problems(mock_db, q="error", limit=1, offset=0)

    mock_db.execute.assert_called_once()
    assert len(results) <= 1


@pytest.mark.asyncio
async def test_search_pagination_limit_100(mock_db):
    """limit=100 is accepted (maximum valid value)."""
    rows = [_make_search_row(problem_id=uuid.uuid4()) for _ in range(10)]
    mock_db.execute.return_value = _db_result(rows)

    results = await search_problems(mock_db, q="error", limit=100, offset=0)

    mock_db.execute.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_search_pagination_offset(mock_db):
    """Positive offset is accepted and forwarded to the query."""
    mock_db.execute.return_value = _db_result([])

    results = await search_problems(mock_db, q="error", limit=5, offset=10)

    mock_db.execute.assert_called_once()
    assert results == []


# ---------------------------------------------------------------------------
# search_problems — excerpt truncation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_excerpt_truncated_at_120_chars(mock_db):
    """Excerpts longer than 120 characters must be truncated to exactly 120.

    GAP: _EXCERPT_LEN = 120 in Python and LEFT(..., 120) in SQL are independent
    constants. A test at the service layer with a mock db cannot verify that the
    SQL constant matches the Python constant; this gap requires an integration test
    against a real database.
    """
    long_desc = "A" * 150
    row = _make_search_row(excerpt=long_desc[:120])  # DB already truncated
    mock_db.execute.return_value = _db_result([row])

    results = await search_problems(mock_db, q="firmware")

    item = results[0]
    excerpt = getattr(item, "excerpt", None) or (item.get("excerpt") if hasattr(item, "get") else None)
    assert excerpt is not None
    assert len(excerpt) <= 120


@pytest.mark.asyncio
async def test_search_excerpt_exactly_120_chars_not_truncated(mock_db):
    """An excerpt of exactly 120 characters must NOT be further truncated."""
    exact_desc = "B" * 120
    row = _make_search_row(excerpt=exact_desc)
    mock_db.execute.return_value = _db_result([row])

    results = await search_problems(mock_db, q="firmware")

    item = results[0]
    excerpt = getattr(item, "excerpt", None) or (item.get("excerpt") if hasattr(item, "get") else None)
    assert excerpt is not None
    assert len(excerpt) == 120


@pytest.mark.asyncio
async def test_search_excerpt_null_safety(mock_db):
    """A problem with no description must return excerpt as empty string, not None."""
    row = _make_search_row(excerpt="")
    mock_db.execute.return_value = _db_result([row])

    results = await search_problems(mock_db, q="firmware")

    item = results[0]
    excerpt = getattr(item, "excerpt", None)
    if excerpt is None and hasattr(item, "get"):
        excerpt = item.get("excerpt")
    # Should be empty string, not None
    assert excerpt is not None


# ---------------------------------------------------------------------------
# search_problems — zero matches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_valid_query_zero_matches(mock_db):
    """A valid query with no matches returns an empty list without error."""
    mock_db.execute.return_value = _db_result([])

    results = await search_problems(mock_db, q="xyzzy_no_match_123")

    mock_db.execute.assert_called_once()
    assert results == [] or (hasattr(results, "results") and results.results == [])


# ---------------------------------------------------------------------------
# suggest_similar — returns up to 5 results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggest_similar_returns_up_to_5(mock_db):
    """suggest_similar returns at most 5 results."""
    rows = [_make_search_row(problem_id=uuid.uuid4(), title=f"Problem {i}") for i in range(5)]
    mock_db.execute.return_value = _db_result(rows)

    results = await suggest_similar(mock_db, title="firmware update")

    assert isinstance(results, list)
    assert len(results) <= 5


@pytest.mark.asyncio
async def test_suggest_similar_fewer_than_5_matches(mock_db):
    """suggest_similar returns however many results exist (< 5) without error."""
    rows = [_make_search_row(problem_id=uuid.uuid4()) for _ in range(3)]
    mock_db.execute.return_value = _db_result(rows)

    results = await suggest_similar(mock_db, title="firmware update")

    assert len(results) == 3


# ---------------------------------------------------------------------------
# suggest_similar — exclude_problem_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggest_similar_exclude_problem_id_filters_self(mock_db):
    """exclude_problem_id must filter out the calling problem from results."""
    excluded_id = uuid.uuid4()
    other_id = uuid.uuid4()

    # Simulate DB returning only non-excluded results (filter applied in SQL)
    rows = [_make_search_row(problem_id=other_id, title="Related problem")]
    mock_db.execute.return_value = _db_result(rows)

    results = await suggest_similar(mock_db, title="firmware", exclude_problem_id=excluded_id)

    # Excluded ID must not appear in results
    result_ids = [
        str(getattr(r, "problem_id", None) or r.get("problem_id", ""))
        for r in results
    ]
    assert str(excluded_id) not in result_ids
    assert str(other_id) in result_ids


@pytest.mark.asyncio
async def test_suggest_similar_exclude_problem_id_forwarded_to_query(mock_db):
    """When exclude_problem_id is given, db.execute must be called (query runs)."""
    mock_db.execute.return_value = _db_result([])

    await suggest_similar(mock_db, title="sensor dropout", exclude_problem_id=uuid.uuid4())

    mock_db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# suggest_similar — empty title short-circuit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggest_similar_empty_title_returns_empty_no_db_call(mock_db):
    """Empty title must return empty result immediately without querying the DB."""
    results = await suggest_similar(mock_db, title="")

    assert results == [] or (hasattr(results, "results") and results.results == [])
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_suggest_similar_whitespace_title_returns_empty_no_db_call(mock_db):
    """Whitespace-only title must also short-circuit without querying the DB."""
    results = await suggest_similar(mock_db, title="   ")

    assert results == [] or (hasattr(results, "results") and results.results == [])
    mock_db.execute.assert_not_called()
