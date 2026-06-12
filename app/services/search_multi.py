"""Multi-entity search service — WP55.

Searches across Problems, Tickets, Components, Labels (Tags), and Users
(User + AgentAccount) in a single call with per-arm filters and a
consistent normalised item shape.

Public API
----------
search_entities(db, query, *, entity="all", ...) -> dict[str, Any]

Return shape::

    {
        "problems":   {"items": [...], "total": int},
        "tickets":    {"items": [...], "total": int},
        "components": {"items": [...], "total": int},
        "labels":     {"items": [...], "total": int},
        "users":      {"items": [...], "total": int},
    }

Each item in ``items`` conforms to the normalised shape::

    {
        "id":         str,           # UUID of the entity
        "display_id": str | None,    # human-readable ID (e.g. "WP55-42")
        "title":      str,
        "subtitle":   str,           # excerpt / handle / description snippet
        "kind":       str,           # "problem"|"ticket"|"component"|"label"|"user"|"agent"
        "href":       str,           # frontend route fragment
        "rank":       float,         # relevance score (1.0 exact, 0.5 prefix, 0.1 substring)
        # arm-specific extras (may be None)
        "project_id": str | None,    # components, tickets
        "status":     str | None,    # problems, tickets
    }

Ranking strategy
----------------
- Problems:   ts_rank via plainto_tsquery (Postgres full-text).
- Tickets:    ts_rank via the persisted ``search_tsv`` generated column when
              the column exists and is non-null; falls back to ILIKE.
- Components / Labels / Users: ILIKE with rank 1.0 (exact), 0.5 (prefix),
              0.1 (substring).

Empty query
-----------
When ``query`` is blank/whitespace, every requested arm immediately returns
``{"items": [], "total": 0}`` — no SQL is executed.

All queries are parametrised. No string interpolation of user input.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services._pagination import (
    InvalidCursorError,
    decode_signed_cursor,
    encode_signed_cursor,
)

# ---------------------------------------------------------------------------
# A-FR-001: AION-N direct-match pattern
# ---------------------------------------------------------------------------

_AION_RE = re.compile(r"^AION-(\d+)$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# v2.29-S6: singular aliases accepted on the wire (frontend sends
# entity=share_post / entity=bounty); normalised to the plural arm key
# before dispatch so the response envelope always uses the arm name.
_ENTITY_ALIASES = {"share_post": "share_posts", "bounty": "bounties"}

_VALID_ENTITIES = frozenset(
    {
        "all",
        "problems",
        "tickets",
        "components",
        "labels",
        "users",
        "share_posts",
        "bounties",
        *_ENTITY_ALIASES,
    }
)
_EXCERPT_LEN = 120

# v2.29-S6: share_posts / bounties snippets truncate at ~160 chars.
_SNIPPET_LEN = 160


def _cursor_secret() -> str:
    """Same secret as the JWT layer — cursors share rotation lifecycle."""
    return get_settings().JWT_SECRET.get_secret_value()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trunc(value: str | None, length: int = _EXCERPT_LEN) -> str:
    if not value:
        return ""
    return value[:length] + "..." if len(value) > length else value


def _empty_arm() -> dict[str, Any]:
    # WP14 (F1): ``total_authority`` is always present on arm responses.
    # An empty arm has no live/snapshot distinction; we report ``snapshot``
    # (the WP10 default) so clients can rely on the field being non-null.
    return {"items": [], "total": 0, "next_cursor": None, "total_authority": "snapshot"}


def _ilike_rank(col_expr: str, query: str) -> str:
    """Return a SQL CASE expression that assigns 1.0/0.5/0.1 rank.

    col_expr must already be lower()-wrapped in the calling SQL if needed.
    This is injected directly into the SQL template — it is NOT user input.
    The query value is bound via :q_lower / :q_prefix parameters.

    ESCAPE E'\\\\' is required because _escape_like() uses backslash as the
    escape character, and with standard_conforming_strings=on (PG default since
    9.1) the LIKE operator does NOT treat backslash as an escape unless the
    ESCAPE clause is explicitly specified.
    """
    return (
        f"CASE "
        f"  WHEN lower({col_expr}) = :q_lower THEN 1.0 "
        f"  WHEN lower({col_expr}) LIKE :q_prefix ESCAPE E'\\\\' THEN 0.5 "
        f"  ELSE 0.1 "
        f"END"
    )


def _escape_like(value: str) -> str:
    r"""Escape LIKE metacharacters (%, _, \) in user input before building LIKE patterns.

    Without this, a user query of ``%`` would match every row (wildcard leakage),
    and ``_`` would act as a single-character wildcard. We use backslash as the
    escape character which is the Postgres LIKE default.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ilike_params(query: str) -> dict[str, str]:
    q = query.lower()
    q_escaped = _escape_like(q)
    return {
        "q_lower": q,
        "q_prefix": f"{q_escaped}%",
        "q_ilike": f"%{q_escaped}%",
    }


# ---------------------------------------------------------------------------
# WP62 — cursor helpers
# ---------------------------------------------------------------------------


def _decode_arm_cursor(arm: str, cursor: str | None) -> dict[str, Any] | None:
    """Decode a per-arm cursor; returns None when absent.

    Propagates ``InvalidCursorError`` so the route layer can map to HTTP 400.
    """
    if not cursor:
        return None
    return decode_signed_cursor(arm, cursor, secret=_cursor_secret())


def _build_next_cursor(
    arm: str,
    last_row: dict[str, Any] | None,
    *,
    total: int | None = None,
    total_authority: str = "snapshot",
) -> str | None:
    """Encode the last row's seek tuple as a signed cursor for the next page.

    Returns ``None`` when there is no last row (caller signals end-of-page).
    Each arm encodes the exact fields its ORDER BY uses.

    WP10: when ``total`` is supplied, embed it as the ``t`` field of the
    payload. Subsequent pages read this back to keep the response ``total``
    stable across the scroll session (snapshot taken on first page). The
    field is HMAC-signed via the envelope so it cannot be tampered. Legacy
    cursors that lack ``t`` still decode normally — see
    :func:`_total_from_cursor`.

    WP14 (F1): additionally embed ``"a"`` (``total_authority``) — ``"snapshot"``
    when the pinned total flows from the WP10 first-page snapshot, ``"live"``
    when the caller forced a re-count via ``refresh_total=True`` and the new
    total reflects the current DB state. The field is HMAC-signed via the
    envelope so it cannot be tampered. Pre-WP14 cursors lack ``"a"`` and are
    treated by the decoder as ``"snapshot"`` for backwards-compat — see
    :func:`_authority_from_cursor`.
    """
    if last_row is None:
        return None
    if arm == "problems":
        payload = {"rank": float(last_row["rank"]), "id": str(last_row["id"])}
    elif arm in ("tickets", "share_posts", "bounties"):
        payload = {
            "rank": float(last_row["rank"]),
            "created_at": last_row["created_at"].isoformat(),
            "id": str(last_row["id"]),
        }
    elif arm in ("components", "labels"):
        payload = {
            "rank": float(last_row["rank"]),
            "name": last_row["name"],
            "id": str(last_row["id"]),
        }
    elif arm == "users":
        payload = {
            "rank": float(last_row["rank"]),
            "handle": last_row["handle"],
            "id": str(last_row["id"]),
        }
    else:
        raise ValueError(f"Unknown arm: {arm!r}")
    if total is not None:
        payload["t"] = int(total)
        # Only meaningful alongside a total — emit ``a`` whenever ``t`` is set.
        payload["a"] = total_authority
    return encode_signed_cursor(arm, payload, secret=_cursor_secret())


def _total_from_cursor(cursor: dict[str, Any] | None) -> int | None:
    """Return the snapshot ``total`` carried by a decoded cursor, or None.

    WP10 stable-total mode: cursors minted from WP10 onward embed a ``t``
    field. Legacy cursors (pre-WP10) lack ``t`` and this returns ``None`` —
    callers fall back to the live count.
    """
    if cursor is None:
        return None
    val = cursor.get("t")
    if isinstance(val, int):
        return val
    return None


def _authority_from_cursor(cursor: dict[str, Any] | None) -> str:
    """Return the ``total_authority`` carried by a decoded cursor.

    WP14 (F1): cursors minted from WP14 onward embed an ``"a"`` field with
    value ``"snapshot"`` (WP10 pinned total) or ``"live"`` (post-
    ``refresh_total`` recount). Pre-WP14 cursors lack ``"a"`` and are
    treated as ``"snapshot"`` so the wire contract is forwards-compatible.
    """
    if cursor is None:
        return "snapshot"
    val = cursor.get("a")
    if val in ("snapshot", "live"):
        return val
    return "snapshot"


# ---------------------------------------------------------------------------
# A-FR-001: Direct-key resolution
# ---------------------------------------------------------------------------


async def resolve_direct_match(
    db: AsyncSession,
    query: str,
) -> dict[str, Any] | None:
    """Return a normalised SearchItem dict when *query* is a valid AION-N ticket ID.

    Accepts leading/trailing whitespace (stripped before matching).
    Rejects AION-0 (seq must be >= 1) and bare AION- (no number) — returns None.
    Returns None when no ticket with that display_id exists.
    """
    stripped = query.strip()
    m = _AION_RE.match(stripped)
    if m is None:
        return None

    seq = int(m.group(1))
    if seq < 1:
        return None

    display_id = stripped.upper()

    row = (
        await db.execute(
            text(
                "SELECT id, display_id, title, description, project_id, status "
                "FROM tickets "
                "WHERE lower(display_id) = lower(:display_id) "
                "LIMIT 1"
            ),
            {"display_id": display_id},
        )
    ).mappings().one_or_none()

    if row is None:
        return None

    return {
        "id": str(row["id"]),
        "display_id": row["display_id"],
        "title": row["title"],
        "subtitle": _trunc(row["description"]),
        "kind": "ticket",
        "href": f"/tickets/{row['display_id']}",
        "rank": 1.0,
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "status": str(row["status"]) if row["status"] else None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_entities(
    db: AsyncSession,
    query: str,
    *,
    entity: str = "all",
    problem_status: str | None = None,
    problem_category_id: uuid.UUID | None = None,
    ticket_status: str | None = None,
    ticket_project_id: uuid.UUID | None = None,
    component_project_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
    problems_cursor: str | None = None,
    tickets_cursor: str | None = None,
    components_cursor: str | None = None,
    labels_cursor: str | None = None,
    users_cursor: str | None = None,
    share_posts_cursor: str | None = None,
    bounties_cursor: str | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    """Search across one or more entity types.

    Parameters
    ----------
    db:
        Async SQLAlchemy session.
    query:
        Free-text search query. Empty / whitespace → all arms return empty.
    entity:
        Which arm(s) to query. One of "all" | "problems" | "tickets" |
        "components" | "labels" | "users".
    problem_status:
        Filter problems arm to this status value (plain string, e.g. "open").
    problem_category_id:
        Filter problems arm to this category UUID.
    ticket_status:
        Filter tickets arm to this TicketStatus value.
    ticket_project_id:
        Filter tickets arm to tickets belonging to this project.
    component_project_id:
        Filter components arm to this project.
    limit:
        Maximum items to return per arm.
    offset:
        Number of rows to skip per arm (for pagination).

    Returns
    -------
    dict[str, {"items": list[dict], "total": int}]
        Only the requested arm keys are present (one key for a single
        entity, five keys for ``entity="all"``).
    """
    if entity not in _VALID_ENTITIES:
        raise ValueError(f"Invalid entity: {entity!r}. Must be one of {sorted(_VALID_ENTITIES)}")

    # v2.29-S6: normalise singular aliases (share_post → share_posts, …)
    entity = _ENTITY_ALIASES.get(entity, entity)

    # Short-circuit on empty query
    if not query or not query.strip():
        if entity == "all":
            return {
                "problems": _empty_arm(),
                "tickets": _empty_arm(),
                "components": _empty_arm(),
                "labels": _empty_arm(),
                "users": _empty_arm(),
                "share_posts": _empty_arm(),
                "bounties": _empty_arm(),
            }
        return {entity: _empty_arm()}

    # Determine which arms to run
    arms = (
        {"problems", "tickets", "components", "labels", "users", "share_posts", "bounties"}
        if entity == "all"
        else {entity}
    )

    result: dict[str, Any] = {}

    if "problems" in arms:
        result["problems"] = await _search_problems(
            db,
            query,
            status=problem_status,
            category_id=problem_category_id,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("problems", problems_cursor),
            refresh_total=refresh_total,
        )

    if "tickets" in arms:
        result["tickets"] = await _search_tickets(
            db,
            query,
            status=ticket_status,
            project_id=ticket_project_id,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("tickets", tickets_cursor),
            refresh_total=refresh_total,
        )

    if "components" in arms:
        result["components"] = await _search_components(
            db,
            query,
            project_id=component_project_id,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("components", components_cursor),
            refresh_total=refresh_total,
        )

    if "labels" in arms:
        result["labels"] = await _search_labels(
            db,
            query,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("labels", labels_cursor),
            refresh_total=refresh_total,
        )

    if "users" in arms:
        result["users"] = await _search_users(
            db,
            query,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("users", users_cursor),
            refresh_total=refresh_total,
        )

    if "share_posts" in arms:
        result["share_posts"] = await _search_share_posts(
            db,
            query,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("share_posts", share_posts_cursor),
            refresh_total=refresh_total,
        )

    if "bounties" in arms:
        result["bounties"] = await _search_bounties(
            db,
            query,
            limit=limit,
            offset=offset,
            cursor=_decode_arm_cursor("bounties", bounties_cursor),
            refresh_total=refresh_total,
        )

    return result


# ---------------------------------------------------------------------------
# Problems arm
# ---------------------------------------------------------------------------

async def _search_problems(
    db: AsyncSession,
    query: str,
    *,
    status: str | None,
    category_id: uuid.UUID | None,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    where_extra = ""
    params: dict[str, Any] = {
        "query": query,
        "lim": limit,
    }

    if status is not None:
        where_extra += " AND p.status = :p_status"
        params["p_status"] = status

    if category_id is not None:
        where_extra += " AND p.category_id = :p_cat"
        params["p_cat"] = str(category_id)

    if cursor is not None:
        # Seek pagination on (rank DESC, id ASC)
        seek_clause = " AND (rank < :c_rank OR (rank = :c_rank AND id > :c_id))"
        params["c_rank"] = float(cursor["rank"])
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    sql = text(f"""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :query) AS q
        ),
        hits AS (
            SELECT
                p.id                AS id,
                p.title             AS title,
                p.description       AS description,
                p.status            AS status,
                ts_rank(p.search_vector, tsq.q) AS rank,
                p.created_at        AS created_at
            FROM problems p, tsq
            WHERE p.search_vector @@ tsq.q
              {where_extra}
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT
            id, title, description, status, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    # WP10: stable-total — if the cursor carries a snapshot, use that.
    # WP14 (F2): when ``refresh_total=True`` the caller opts out of the
    # snapshot and the response surfaces the live count + ``authority="live"``.
    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        # Empty page: honour the snapshot so the UI counter doesn't change
        # when the user scrolls past the end of a set that has since shrunk.
        # If ``refresh_total`` was requested but the recount wasn't run
        # (no rows ⇒ COUNT(*) OVER () not executed), fall back to the
        # snapshot so we never surface ``"live"`` with a stale value.
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": None,
            "title": row["title"],
            "subtitle": _trunc(row["description"]),
            "kind": "problem",
            "href": f"/problems/{row['id']}",
            "rank": float(row["rank"]),
            "project_id": None,
            "status": row["status"],
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "problems", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Tickets arm
# ---------------------------------------------------------------------------

async def _search_tickets(
    db: AsyncSession,
    query: str,
    *,
    status: str | None,
    project_id: uuid.UUID | None,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    # WP61: tsvector FTS on title+description (via the generated search_tsv
    # column), with an ILIKE fallback on display_id only — display_ids like
    # "PROJ-42" don't tokenise cleanly under plainto_tsquery('english').
    # WP62: optional cursor-based seek pagination on (rank, created_at, id).
    where_extra = ""
    escaped_q = _escape_like(query.lower())
    params: dict[str, Any] = {
        "lim": limit,
        "query_text": query,
        "display_like": f"%{escaped_q}%",
    }

    if status is not None:
        where_extra += " AND t.status::text = :t_status"
        params["t_status"] = status

    if project_id is not None:
        where_extra += " AND t.project_id = :t_proj"
        params["t_proj"] = str(project_id)

    if cursor is not None:
        # Seek on (rank DESC, created_at DESC, id ASC). Cast the ISO-string
        # cursor timestamp explicitly so asyncpg doesn't infer text vs.
        # timestamptz inconsistently across the three OR branches.
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND created_at < CAST(:c_created AS timestamptz))"
            " OR (rank = :c_rank AND created_at = CAST(:c_created AS timestamptz)"
            "     AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        # asyncpg requires a real datetime for timestamptz binds — parse the
        # ISO string back. fromisoformat handles "+00:00" suffixes natively
        # on Python 3.11+.
        params["c_created"] = datetime.fromisoformat(cursor["created_at"])
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    # ESCAPE E'\\\\' — the Python f-string becomes E'\\' in SQL, which is the
    # standard-conforming-strings literal backslash that _escape_like() uses.
    sql = text(f"""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :query_text) AS q
        ),
        hits AS (
            SELECT
                t.id            AS id,
                t.display_id    AS display_id,
                t.title         AS title,
                t.description   AS description,
                t.project_id    AS project_id,
                t.status        AS status,
                t.created_at    AS created_at,
                ts_rank(t.search_tsv, tsq.q) AS rank
            FROM tickets t, tsq
            WHERE (
                (t.search_tsv @@ tsq.q)
                OR lower(t.display_id) LIKE :display_like ESCAPE E'\\\\'
            )
            {where_extra}
        )
        , counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT
            id, display_id, title, description, project_id, status,
            created_at, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, created_at DESC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": row["display_id"],
            "title": row["title"],
            "subtitle": _trunc(row["description"]),
            "kind": "ticket",
            "href": f"/tickets/{row['display_id']}",
            "rank": float(row["rank"]),
            "project_id": str(row["project_id"]) if row["project_id"] else None,
            "status": str(row["status"]) if row["status"] else None,
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "tickets", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Components arm
# ---------------------------------------------------------------------------

async def _search_components(
    db: AsyncSession,
    query: str,
    *,
    project_id: uuid.UUID | None,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    where_extra = ""
    params: dict[str, Any] = {
        "lim": limit,
        **_ilike_params(query),
    }

    if project_id is not None:
        where_extra += " AND c.project_id = :c_proj"
        params["c_proj"] = str(project_id)

    rank_expr = _ilike_rank("c.name", query)

    if cursor is not None:
        # Seek on (rank DESC, name ASC, id ASC)
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND name > :c_name)"
            " OR (rank = :c_rank AND name = :c_name AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        params["c_name"] = cursor["name"]
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    sql = text(f"""
        WITH hits AS (
            SELECT
                c.id            AS id,
                c.name          AS name,
                c.description   AS description,
                c.project_id    AS project_id,
                {rank_expr}     AS rank
            FROM components c
            WHERE lower(c.name) LIKE :q_ilike ESCAPE E'\\\\'
            {where_extra}
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT id, name, description, project_id, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, name ASC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": None,
            "title": row["name"],
            "subtitle": _trunc(row["description"]),
            "kind": "component",
            "href": f"/components/{row['id']}",
            "rank": float(row["rank"]),
            "project_id": str(row["project_id"]) if row["project_id"] else None,
            "status": None,
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "components", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Labels (Tags) arm
# ---------------------------------------------------------------------------

async def _search_labels(
    db: AsyncSession,
    query: str,
    *,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    rank_expr = _ilike_rank("t.name", query)
    params: dict[str, Any] = {
        "lim": limit,
        **_ilike_params(query),
    }

    if cursor is not None:
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND name > :c_name)"
            " OR (rank = :c_rank AND name = :c_name AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        params["c_name"] = cursor["name"]
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    sql = text(f"""
        WITH hits AS (
            SELECT
                t.id    AS id,
                t.name  AS name,
                {rank_expr} AS rank
            FROM tags t
            WHERE lower(t.name) LIKE :q_ilike ESCAPE E'\\\\'
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT id, name, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, name ASC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": None,
            "title": row["name"],
            "subtitle": "",
            "kind": "label",
            "href": f"/labels/{row['name']}",
            "rank": float(row["rank"]),
            "project_id": None,
            "status": None,
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "labels", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Users arm — merges User + AgentAccount rows
# ---------------------------------------------------------------------------

async def _search_users(
    db: AsyncSession,
    query: str,
    *,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    # Users: match handle or display_name
    # Agents: match handle or name (agent has no display_name column; name ≈ display_name)
    #
    # Rank: 1.0 if handle exact match, 0.5 if handle prefix, 0.1 otherwise.
    # We compute rank separately for each source table then UNION ALL.

    params: dict[str, Any] = {
        "lim": limit,
        **_ilike_params(query),
    }

    if cursor is not None:
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND handle > :c_handle)"
            " OR (rank = :c_rank AND handle = :c_handle AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        params["c_handle"] = cursor["handle"]
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    # NOTE: rank computed on handle for both sources for consistency.
    user_rank_expr = _ilike_rank("u.handle", query)
    agent_rank_expr = _ilike_rank("a.handle", query)

    sql = text(f"""
        WITH combined AS (
            -- Users
            SELECT
                u.id            AS id,
                u.handle        AS handle,
                u.display_name  AS display_name,
                'user'          AS kind,
                {user_rank_expr} AS rank
            FROM users u
            WHERE lower(u.handle) LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(u.display_name) LIKE :q_ilike ESCAPE E'\\\\'

            UNION ALL

            -- Agent accounts
            SELECT
                a.id            AS id,
                a.handle        AS handle,
                a.name          AS display_name,
                'agent'         AS kind,
                {agent_rank_expr} AS rank
            FROM agent_accounts a
            WHERE lower(a.handle) LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(a.name)   LIKE :q_ilike ESCAPE E'\\\\'
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM combined
        )
        SELECT
            id, handle, display_name, kind, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, handle ASC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": row["handle"],
            "title": row["display_name"],
            "subtitle": f"@{row['handle']}",
            "kind": row["kind"],
            "href": f"/users/{row['handle']}",
            "rank": float(row["rank"]),
            "project_id": None,
            "status": None,
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "users", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Share posts arm — v2.29-S6
# ---------------------------------------------------------------------------

async def _search_share_posts(
    db: AsyncSession,
    query: str,
    *,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    """ILIKE on title/body; rank on title; newest-first secondary sort."""
    rank_expr = _ilike_rank("sp.title", query)
    params: dict[str, Any] = {
        "lim": limit,
        **_ilike_params(query),
    }

    if cursor is not None:
        # Seek on (rank DESC, created_at DESC, id ASC) — same as tickets.
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND created_at < CAST(:c_created AS timestamptz))"
            " OR (rank = :c_rank AND created_at = CAST(:c_created AS timestamptz)"
            "     AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        params["c_created"] = datetime.fromisoformat(cursor["created_at"])
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    sql = text(f"""
        WITH hits AS (
            SELECT
                sp.id           AS id,
                sp.title        AS title,
                sp.body         AS body,
                sp.created_at   AS created_at,
                {rank_expr}     AS rank
            FROM share_posts sp
            WHERE lower(sp.title) LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(sp.body)  LIKE :q_ilike ESCAPE E'\\\\'
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT id, title, body, created_at, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, created_at DESC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": None,
            "title": row["title"],
            "subtitle": _trunc(row["body"], _SNIPPET_LEN),
            "kind": "share_post",
            "href": f"/share#{row['id']}",
            "rank": float(row["rank"]),
            "project_id": None,
            "status": None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "share_posts", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }


# ---------------------------------------------------------------------------
# Bounties arm — v2.29-S6
# ---------------------------------------------------------------------------

async def _search_bounties(
    db: AsyncSession,
    query: str,
    *,
    limit: int,
    offset: int,
    cursor: dict[str, Any] | None = None,
    refresh_total: bool = False,
) -> dict[str, Any]:
    """ILIKE on title/description; rank on title; newest-first secondary sort."""
    rank_expr = _ilike_rank("b.title", query)
    params: dict[str, Any] = {
        "lim": limit,
        **_ilike_params(query),
    }

    if cursor is not None:
        seek_clause = (
            " AND (rank < :c_rank"
            " OR (rank = :c_rank AND created_at < CAST(:c_created AS timestamptz))"
            " OR (rank = :c_rank AND created_at = CAST(:c_created AS timestamptz)"
            "     AND id > CAST(:c_id AS uuid)))"
        )
        params["c_rank"] = float(cursor["rank"])
        params["c_created"] = datetime.fromisoformat(cursor["created_at"])
        params["c_id"] = str(cursor["id"])
        offset_clause = ""
    else:
        seek_clause = ""
        params["off"] = offset
        offset_clause = "OFFSET :off"

    sql = text(f"""
        WITH hits AS (
            SELECT
                b.id            AS id,
                b.title         AS title,
                b.description   AS description,
                b.status        AS status,
                b.created_at    AS created_at,
                {rank_expr}     AS rank
            FROM bounties b
            WHERE lower(b.title)       LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(b.description) LIKE :q_ilike ESCAPE E'\\\\'
        ),
        counted AS (
            SELECT *, COUNT(*) OVER () AS total_count FROM hits
        )
        SELECT id, title, description, status, created_at, rank, total_count
        FROM counted
        WHERE 1=1{seek_clause}
        ORDER BY rank DESC, created_at DESC, id ASC
        LIMIT :lim {offset_clause}
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    snapshot = _total_from_cursor(cursor)
    prior_authority = _authority_from_cursor(cursor)
    if not rows:
        return {
            "items": [],
            "total": snapshot or 0,
            "next_cursor": None,
            "total_authority": prior_authority,
        }

    live_total = int(rows[0]["total_count"])
    if refresh_total or snapshot is None:
        total = live_total
        authority = "live" if refresh_total else "snapshot"
    else:
        total = snapshot
        authority = prior_authority
    items = [
        {
            "id": str(row["id"]),
            "display_id": None,
            "title": row["title"],
            "subtitle": _trunc(row["description"], _SNIPPET_LEN),
            "kind": "bounty",
            "href": f"/bounties#{row['id']}",
            "rank": float(row["rank"]),
            "project_id": None,
            "status": str(row["status"]) if row["status"] else None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
    next_cursor = (
        _build_next_cursor(
            "bounties", dict(rows[-1]), total=total, total_authority=authority
        )
        if len(rows) >= limit
        else None
    )
    return {
        "items": items,
        "total": total,
        "next_cursor": next_cursor,
        "total_authority": authority,
    }
