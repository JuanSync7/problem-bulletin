"""WP61 — Tickets arm tsvector FTS tests.

These tests prove the tickets arm uses Postgres full-text search on the
generated ``search_tsv`` column rather than naive ILIKE substring matching,
while preserving an ILIKE fallback for hyphenated ``display_id`` lookups.

Behaviours under test:
- Morphological/stem matching ("running" matches a ticket titled "runs daily")
  — proves FTS rather than substring.
- display_id substring matching ("PROJ-4" matches "PROJ-42") — proves the
  ILIKE fallback survives.
- Wildcard safety: q='%' returns empty (the LIKE pattern is escaped).
- Empty query short-circuit: q='' returns the empty-arm shape.

Tests rely on the live-Postgres ``db`` fixture from ``tests/conftest.py`` and
auto-skip when PG is unreachable.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.services.search_multi import search_entities


# ---------------------------------------------------------------------------
# Local seed helpers (mirror those in test_search_multi.py but kept local to
# avoid coupling test modules together).
# ---------------------------------------------------------------------------

async def _seed_user(db, *, handle: str, display_name: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle) "
            "VALUES (:id, :email, :display_name, :handle)"
        ),
        {
            "id": uid,
            "email": f"{uid}@test.example",
            "display_name": display_name,
            "handle": handle,
        },
    )
    return uid


async def _seed_project(db, *, key: str, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :key, :name)"),
        {"id": pid, "key": key, "name": name},
    )
    return pid


async def _seed_ticket(
    db,
    *,
    project_id: uuid.UUID,
    reporter_id: uuid.UUID,
    title: str,
    description: str | None = None,
    display_id: str,
    seq: int,
    status: str = "todo",
) -> uuid.UUID:
    tid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, labels, "
            " fix_versions, custom_fields) "
            "VALUES (:id, :seq, :display_id, :title, :desc, :project_id, "
            "        :reporter_id, 'user', 'task', :status, 'medium', '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "display_id": display_id,
            "title": title,
            "desc": description,
            "project_id": project_id,
            "reporter_id": reporter_id,
            "status": status,
        },
    )
    return tid


@pytest_asyncio.fixture
async def fts_user(db) -> uuid.UUID:
    uid = await _seed_user(
        db,
        handle=f"wp61_{uuid.uuid4().hex[:6]}",
        display_name="WP61 Tester",
    )
    await db.flush()
    return uid


@pytest_asyncio.fixture
async def fts_project(db) -> uuid.UUID:
    pid = await _seed_project(
        db, key=f"WP61{uuid.uuid4().hex[:4].upper()}", name="WP61 FTS Project"
    )
    await db.flush()
    return pid


# ---------------------------------------------------------------------------
# 1. Stem / morphological match — proves FTS, not ILIKE substring.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_matches_morphological_stem(db, fts_user, fts_project):
    """q='running' should match a ticket titled 'runs daily' via 'english' stemmer.

    Substring ILIKE would NOT match because neither 'run' nor 'running' is a
    substring of 'runs daily' as a contiguous string. tsvector('english')
    reduces 'runs' and 'running' to the same stem.
    """
    # Use a unique token so we only catch our own seeded row.
    unique = f"orbital{uuid.uuid4().hex[:6]}"
    tid = await _seed_ticket(
        db,
        project_id=fts_project,
        reporter_id=fts_user,
        title=f"{unique} runs daily",
        display_id=f"FTS-{uuid.uuid4().hex[:6]}",
        seq=51001,
    )
    await db.flush()

    # Query with the morphological variant 'running' AND the unique token to
    # disambiguate from any other 'running' rows that might exist.
    result = await search_entities(
        db, query=f"{unique} running", entity="tickets"
    )
    ids = [i["id"] for i in result["tickets"]["items"]]
    assert str(tid) in ids, (
        "FTS expected to stem 'running' → 'run' and match 'runs daily'. "
        f"Got items: {result['tickets']['items']!r}"
    )


# ---------------------------------------------------------------------------
# 2. display_id substring — proves the ILIKE fallback.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_display_id_substring_via_ilike_fallback(
    db, fts_user, fts_project
):
    """q='PROJ-4' must still match a ticket whose display_id is 'PROJ-42'.

    plainto_tsquery('english') tokenises 'PROJ-4' as separate lexemes 'proj'
    and '4' and would not match the literal display_id string. The ILIKE
    fallback on t.display_id keeps this lookup working.
    """
    unique_key = f"WP61X{uuid.uuid4().hex[:4].upper()}"
    display = f"{unique_key}-42"
    tid = await _seed_ticket(
        db,
        project_id=fts_project,
        reporter_id=fts_user,
        title="An unrelated title that wont match the prefix",
        display_id=display,
        seq=51002,
    )
    await db.flush()

    # Query the display_id prefix WITHOUT the trailing 2 — pure substring lookup.
    result = await search_entities(
        db, query=f"{unique_key}-4", entity="tickets"
    )
    ids = [i["id"] for i in result["tickets"]["items"]]
    assert str(tid) in ids, (
        "ILIKE fallback on display_id expected to match 'PROJ-4' against "
        f"display_id={display!r}. Got items: {result['tickets']['items']!r}"
    )


# ---------------------------------------------------------------------------
# 3. Wildcard safety — q='%' must NOT leak every row.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_percent_wildcard_returns_empty(db, fts_user, fts_project):
    """q='%' must not act as a SQL LIKE wildcard — _escape_like() neutralises it.

    Seed one ticket so the table is non-empty; the query must still return
    zero rows for our seeded ticket (and ideally zero overall, but we only
    assert our own row is absent to stay isolation-safe).
    """
    tid = await _seed_ticket(
        db,
        project_id=fts_project,
        reporter_id=fts_user,
        title="Just a normal ticket",
        display_id=f"WP61PCT-{uuid.uuid4().hex[:4]}",
        seq=51003,
    )
    await db.flush()

    result = await search_entities(db, query="%", entity="tickets")
    ids = [i["id"] for i in result["tickets"]["items"]]
    assert str(tid) not in ids, (
        "q='%' must be escaped — it must not wildcard-match every row. "
        f"Got items: {result['tickets']['items']!r}"
    )


# ---------------------------------------------------------------------------
# 4. Empty query short-circuit — existing behaviour preserved.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tickets_arm_empty_query_short_circuits(db):
    """q='' with entity='tickets' returns the empty-arm shape (no SQL run)."""
    result = await search_entities(db, query="", entity="tickets")
    # v2.11-WP14 (F1): empty-arm shape additionally carries ``total_authority``
    # (always ``"snapshot"`` for empty arms — no live/snapshot distinction).
    assert result == {
        "tickets": {
            "items": [],
            "total": 0,
            "next_cursor": None,
            "total_authority": "snapshot",
        }
    }
