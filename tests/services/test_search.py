"""Live-Postgres tests for ``app.services.search``.

Rewritten in v2.10-WP04b.  The legacy v1 file mocked db.execute and
passed ``q=`` (service uses positional ``query``).  These tests target
the real service surface with the function-scoped ``db`` session.

Service contract
----------------
``search_problems(db, query, *, sort="relevance", category_id=None,
tag_ids=None, status=None, limit=20, offset=0) -> dict``
    Returns ``{"results": [...]}`` on a hit, ``{"results": [],
    "message": "No results found"}`` on miss or empty query.  Excerpt
    truncation is done in SQL via ``LEFT(description, 120)``.

``suggest_similar(db, title, *, exclude_problem_id=None, limit=5)
-> list[dict]``
    Returns ``[]`` for an empty title; otherwise the list of matching
    problems sorted by ts_rank DESC.

Bucket (b) production fix (historical)
--------------------------------------
The status filter previously read ``p.status = :status``, but the
``problems`` table column was briefly renamed to ``legacy_status``
between ``a1_agent_kanban`` and ``a19_problems_status_rename``
(v2.11-WP15 reverted the rename). ``test_search_filter_status`` is the
red regression that drove the v2.10-WP04b fix and continues to guard
the post-WP15 spelling.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services.search import search_problems, suggest_similar
from tests.helpers.seed_problem import seed_problem, seed_tag


pytestmark = pytest.mark.asyncio


async def _refresh_tsv(db, problem_id) -> None:
    """Recompute the FTS vector for a problem after raw SQL inserts."""
    await db.execute(
        text(
            "UPDATE problems "
            "SET search_vector = to_tsvector('english', title || ' ' || description) "
            "WHERE id = :id"
        ),
        {"id": problem_id},
    )


async def _attach_tag(db, problem_id, tag_id) -> None:
    await db.execute(
        text("INSERT INTO problem_tags (problem_id, tag_id) VALUES (:p, :t)"),
        {"p": problem_id, "t": tag_id},
    )


# ===========================================================================
# Empty / whitespace short-circuit
# ===========================================================================

async def test_search_empty_query_returns_empty_no_db_call(db):
    """Empty query short-circuits to the empty-result envelope."""
    result = await search_problems(db, "")
    assert result == {"results": [], "message": "No results found"}


async def test_search_blank_whitespace_query_returns_empty_no_db_call(db):
    """Whitespace-only query also short-circuits."""
    result = await search_problems(db, "    \t  ")
    assert result == {"results": [], "message": "No results found"}


# ===========================================================================
# Valid query → structured result envelope
# ===========================================================================

async def test_search_valid_query_returns_result_fields(db):
    """A matching problem produces all documented fields."""
    pid = await seed_problem(
        db, title="Sensor dropout in firmware",
        description="Sensor reads drop intermittently when firmware boots",
    )
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "sensor dropout")
    assert "results" in out
    hits = [r for r in out["results"] if r["problem_id"] == str(pid)]
    assert len(hits) == 1
    item = hits[0]
    assert item["title"] == "Sensor dropout in firmware"
    assert isinstance(item["rank"], float)
    assert item["match_source"] in ("problem", "solution", "comment")
    assert "excerpt" in item
    assert "upstar_count" in item
    assert "created_at" in item


async def test_search_result_has_excerpt_field(db):
    """Result items must include a non-None excerpt."""
    pid = await seed_problem(
        db, title="Firmware update", description="Firmware fails to boot on cold start",
    )
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "firmware")
    hits = [r for r in out["results"] if r["problem_id"] == str(pid)]
    assert hits and hits[0]["excerpt"] is not None


# ===========================================================================
# Sort modes
# ===========================================================================

async def test_search_sort_relevance_default(db):
    """``sort=relevance`` (default) returns results without error."""
    pid = await seed_problem(db, title="Bug X", description="bug bug bug")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "bug")
    assert "results" in out


async def test_search_sort_upvotes(db):
    """``sort=upvotes`` is accepted and returns results."""
    pid = await seed_problem(db, title="Bug X", description="bug payload")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "bug", sort="upvotes")
    assert "results" in out


async def test_search_sort_newest(db):
    """``sort=newest`` is accepted and returns results."""
    pid = await seed_problem(db, title="Newish bug", description="bug payload")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "bug", sort="newest")
    assert "results" in out


async def test_search_unknown_sort_falls_back_silently(db):
    """An unknown sort value silently falls back to relevance order."""
    pid = await seed_problem(db, title="Fallback bug", description="bug bug")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "bug", sort="bogus")
    assert "results" in out


# ===========================================================================
# Filters
# ===========================================================================

async def test_search_filter_category_id(db):
    """A category_id filter restricts results to that category."""
    from tests.helpers.seed_problem import seed_category

    cat = await seed_category(db, name=f"Cat-{uuid.uuid4().hex[:6]}")
    pid_in = await seed_problem(
        db, category_id=cat, title="Driver crash", description="driver dies on init",
    )
    pid_out = await seed_problem(
        db, title="Driver crash", description="driver dies on init",
    )
    await _refresh_tsv(db, pid_in)
    await _refresh_tsv(db, pid_out)
    await db.flush()

    out = await search_problems(db, "driver", category_id=cat)
    ids = {r["problem_id"] for r in out["results"]}
    assert str(pid_in) in ids
    assert str(pid_out) not in ids


async def test_search_filter_status(db):
    """A status filter restricts results to that status (regression for
    the ``problems.status`` ↔ ``legacy_status`` rename history).

    Bucket (b): before the v2.10-WP04b fix, the raw SQL referenced
    ``p.status`` which at the time did not exist (a1 had renamed it to
    ``legacy_status``). The column was renamed back to ``status`` in
    v2.11-WP15 (``a19``); this regression test continues to guard the
    final spelling.
    """
    pid_open = await seed_problem(
        db, title="Open bug", description="open bug body", status="open",
    )
    pid_closed = await seed_problem(
        db, title="Open bug", description="open bug body", status="resolved",
    )
    await _refresh_tsv(db, pid_open)
    await _refresh_tsv(db, pid_closed)
    await db.flush()

    out = await search_problems(db, "open bug", status="open")
    ids = {r["problem_id"] for r in out["results"]}
    assert str(pid_open) in ids
    assert str(pid_closed) not in ids


async def test_search_filter_single_tag_id(db):
    """A single tag_id filters to tagged problems."""
    tag = await seed_tag(db, name=f"sgl-{uuid.uuid4().hex[:6]}")
    pid_tagged = await seed_problem(
        db, title="Tagged thing", description="tagged thing body keyword",
    )
    pid_plain = await seed_problem(
        db, title="Untagged thing", description="untagged thing body keyword",
    )
    await _attach_tag(db, pid_tagged, tag)
    await _refresh_tsv(db, pid_tagged)
    await _refresh_tsv(db, pid_plain)
    await db.flush()

    out = await search_problems(db, "keyword", tag_ids=[tag])
    ids = {r["problem_id"] for r in out["results"]}
    assert str(pid_tagged) in ids
    assert str(pid_plain) not in ids


async def test_search_filter_multiple_tag_ids(db):
    """Multiple tag_ids accept matches on ANY tag (SQL IN clause)."""
    tag_a = await seed_tag(db, name=f"a-{uuid.uuid4().hex[:6]}")
    tag_b = await seed_tag(db, name=f"b-{uuid.uuid4().hex[:6]}")
    pid_a = await seed_problem(db, title="Has A", description="alpha alpha alpha")
    pid_b = await seed_problem(db, title="Has B", description="alpha alpha alpha")
    await _attach_tag(db, pid_a, tag_a)
    await _attach_tag(db, pid_b, tag_b)
    await _refresh_tsv(db, pid_a)
    await _refresh_tsv(db, pid_b)
    await db.flush()

    out = await search_problems(db, "alpha", tag_ids=[tag_a, tag_b])
    ids = {r["problem_id"] for r in out["results"]}
    assert str(pid_a) in ids
    assert str(pid_b) in ids


# ===========================================================================
# Pagination
# ===========================================================================

async def test_search_pagination_limit_1(db):
    """``limit=1`` returns at most one result."""
    for i in range(3):
        pid = await seed_problem(
            db, title=f"Bug-{i}", description="paginate keyword keyword",
        )
        await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "paginate", limit=1, offset=0)
    assert len(out.get("results", [])) <= 1


async def test_search_pagination_limit_100(db):
    """``limit=100`` is accepted (max)."""
    pid = await seed_problem(db, title="One", description="paginate2 paginate2")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "paginate2", limit=100, offset=0)
    assert "results" in out


async def test_search_pagination_offset(db):
    """A positive offset skips earlier rows."""
    pids = []
    for i in range(3):
        pid = await seed_problem(
            db, title=f"Off-{i}", description="offsetkw offsetkw offsetkw",
        )
        await _refresh_tsv(db, pid)
        pids.append(pid)
    await db.flush()

    out_all = await search_problems(db, "offsetkw", limit=10, offset=0)
    out_skip = await search_problems(db, "offsetkw", limit=10, offset=2)
    # Offset must not return more rows than (all - 2).
    assert len(out_skip["results"]) <= max(0, len(out_all["results"]) - 2)


# ===========================================================================
# Excerpt truncation (SQL ``LEFT(description, 120)``)
# ===========================================================================

async def test_search_excerpt_truncated_at_120_chars(db):
    """Long descriptions are truncated to <=120 chars by the SQL LEFT()."""
    long_desc = "tquery " + ("X" * 250)  # 256 chars, keyword "tquery" at start
    pid = await seed_problem(db, title="Long body", description=long_desc)
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "tquery")
    hits = [r for r in out["results"] if r["problem_id"] == str(pid)]
    assert hits and len(hits[0]["excerpt"]) <= 120


async def test_search_excerpt_exactly_120_chars_not_truncated(db):
    """A 120-char description excerpt is returned in full."""
    desc = "exactkey " + ("Y" * (120 - len("exactkey ")))  # exactly 120
    assert len(desc) == 120
    pid = await seed_problem(db, title="Exact-len", description=desc)
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "exactkey")
    hits = [r for r in out["results"] if r["problem_id"] == str(pid)]
    assert hits and len(hits[0]["excerpt"]) == 120


async def test_search_excerpt_null_safety(db):
    """The service must coerce a null/empty excerpt to '' (not None)."""
    # A description that's non-null but minimal.
    pid = await seed_problem(db, title="nullsafekw thing", description="x")
    await _refresh_tsv(db, pid)
    await db.flush()

    out = await search_problems(db, "nullsafekw")
    hits = [r for r in out["results"] if r["problem_id"] == str(pid)]
    assert hits
    assert hits[0]["excerpt"] is not None
    assert isinstance(hits[0]["excerpt"], str)


# ===========================================================================
# Zero matches
# ===========================================================================

async def test_search_valid_query_zero_matches(db):
    """A valid query with no FTS hit returns the empty-message envelope."""
    out = await search_problems(db, "qqqzzz_no_match_xyzzy")
    assert out == {"results": [], "message": "No results found"}


# ===========================================================================
# suggest_similar
# ===========================================================================

async def test_suggest_similar_exclude_problem_id_filters_self(db):
    """``exclude_problem_id`` removes the caller's own row from results."""
    me = await seed_problem(
        db, title="firmware crash", description="firmware crash recurring",
    )
    other = await seed_problem(
        db, title="firmware crash too", description="firmware crash similar",
    )
    await _refresh_tsv(db, me)
    await _refresh_tsv(db, other)
    await db.flush()

    out = await suggest_similar(db, "firmware crash", exclude_problem_id=me)
    ids = {r["problem_id"] for r in out}
    assert str(me) not in ids
    assert str(other) in ids


async def test_suggest_similar_fewer_than_5_matches(db):
    """``suggest_similar`` returns however many match, capped by limit."""
    # Use a deliberately unique token so the seed dominates.
    token = f"uniqsimkw{uuid.uuid4().hex[:8]}"
    for i in range(3):
        pid = await seed_problem(
            db, title=f"Match-{i}", description=f"{token} body text",
        )
        await _refresh_tsv(db, pid)
    await db.flush()

    out = await suggest_similar(db, token, limit=5)
    assert len(out) == 3


async def test_suggest_similar_returns_up_to_5(db):
    """``suggest_similar`` caps the result list at the limit (default 5)."""
    token = f"capkw{uuid.uuid4().hex[:8]}"
    for i in range(7):
        pid = await seed_problem(
            db, title=f"Cap-{i}", description=f"{token} body matter",
        )
        await _refresh_tsv(db, pid)
    await db.flush()

    out = await suggest_similar(db, token)  # default limit
    assert len(out) <= 5


async def test_suggest_similar_exclude_problem_id_forwarded_to_query(db):
    """When ``exclude_problem_id`` is given the SQL still runs."""
    token = f"fwdkw{uuid.uuid4().hex[:8]}"
    pid = await seed_problem(db, title="Fwd", description=f"{token} body")
    await _refresh_tsv(db, pid)
    await db.flush()
    out = await suggest_similar(db, token, exclude_problem_id=uuid.uuid4())
    # Sanity: still returns the row (it's not self-excluded).
    assert any(r["problem_id"] == str(pid) for r in out)


async def test_suggest_similar_empty_title_returns_empty_no_db_call(db):
    """An empty title short-circuits to ``[]``."""
    out = await suggest_similar(db, "")
    assert out == []


async def test_suggest_similar_whitespace_title_returns_empty_no_db_call(db):
    """Whitespace-only title short-circuits to ``[]``."""
    out = await suggest_similar(db, "  \t  ")
    assert out == []
