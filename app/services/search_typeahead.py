"""Typeahead search service — A2a.

Implements the ranking pipeline for ``mode=typeahead`` on ``/api/search/v2``:

  1. ts_rank (Postgres full-text) — primary lexical score
  2. pg_trgm fallback — when no tsvector hit, use trigram similarity ≥ 0.3
  3. Recency boost — multiplicative: ``rank *= (1 + w * exp(-age_days / 30))``
     where ``w = Settings.SEARCH_RECENCY_BOOST`` (default 0.3).
  4. Personalisation boost — +0.2 when ``current_user_id`` is assignee/reporter.
  5. Per-entity weight — from ``Settings.SEARCH_ENTITY_WEIGHTS``.
  6. Each arm is capped at 5 items.
  7. ``combined`` list is the top ≤ 15 items across all arms, globally ranked.

Public API
----------
``search_typeahead(db, query, *, entity, current_user_id) -> dict``

Return shape::

    {
        # per-arm keys (same shape as search_entities, but items ≤ 5):
        "problems":   {"items": [...], "total": int, ...},
        "tickets":    {"items": [...], "total": int, ...},
        ...
        # merged globally-ranked list ≤ 15:
        "combined":   [SearchItem, ...],
    }
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.search_multi import (
    _VALID_ENTITIES,
    _empty_arm,
    _escape_like,
    _ilike_params,
    _ilike_rank,
    _trunc,
)

_TYPEAHEAD_ARM_CAP = 5
_TYPEAHEAD_COMBINED_CAP = 15
_TRGM_SIMILARITY_THRESHOLD = 0.25  # lowered from 0.3 to be more forgiving


def _recency_boost(rank: float, created_at: datetime | None, boost_weight: float) -> float:
    """Apply exponential recency decay to the rank.

    final_rank = rank * (1 + weight * exp(-age_days / 30))

    A 1-day-old item gets approximately +30% when weight=0.3.
    A 6-month-old item gets approximately +3% boost.
    """
    if created_at is None:
        return rank
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    multiplier = 1.0 + boost_weight * math.exp(-age_days / 30.0)
    return rank * multiplier


def _personalisation_boost(item: dict[str, Any], current_user_id: uuid.UUID | None) -> float:
    """Return +0.2 if current_user_id matches assignee or reporter."""
    if current_user_id is None:
        return 0.0
    user_str = str(current_user_id)
    if item.get("assignee_id") == user_str or item.get("reporter_id") == user_str:
        return 0.2
    return 0.0


async def search_typeahead(
    db: AsyncSession,
    query: str,
    *,
    entity: str = "all",
    current_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Typeahead search pipeline.

    Returns a dict with per-arm keys (items capped at ``_TYPEAHEAD_ARM_CAP``)
    plus a ``combined`` key with the merged globally-ranked list (≤ 15 items).
    """
    if entity not in _VALID_ENTITIES:
        raise ValueError(f"Invalid entity: {entity!r}")

    settings = get_settings()
    recency_weight = settings.SEARCH_RECENCY_BOOST
    entity_weights = settings.SEARCH_ENTITY_WEIGHTS

    # Short-circuit on empty query
    if not query or not query.strip():
        base: dict[str, Any]
        if entity == "all":
            base = {
                "problems": _empty_arm(),
                "tickets": _empty_arm(),
                "components": _empty_arm(),
                "labels": _empty_arm(),
                "users": _empty_arm(),
            }
        else:
            base = {entity: _empty_arm()}
        base["combined"] = []
        return base

    arms_to_run = (
        {"problems", "tickets", "components", "labels", "users"}
        if entity == "all"
        else {entity}
    )

    result: dict[str, Any] = {}

    if "problems" in arms_to_run:
        result["problems"] = await _ta_problems(
            db, query, current_user_id=current_user_id,
            recency_weight=recency_weight, entity_weights=entity_weights,
        )

    if "tickets" in arms_to_run:
        result["tickets"] = await _ta_tickets(
            db, query, current_user_id=current_user_id,
            recency_weight=recency_weight, entity_weights=entity_weights,
        )

    if "components" in arms_to_run:
        result["components"] = await _ta_components(
            db, query,
            recency_weight=recency_weight, entity_weights=entity_weights,
        )

    if "labels" in arms_to_run:
        result["labels"] = await _ta_labels(
            db, query, entity_weights=entity_weights,
        )

    if "users" in arms_to_run:
        result["users"] = await _ta_users(
            db, query, entity_weights=entity_weights,
        )

    # Build combined list: gather all items, sort by final_rank desc, cap at 15
    all_items: list[dict[str, Any]] = []
    for arm_key, arm_data in result.items():
        for item in arm_data.get("items", []):
            all_items.append(item)

    all_items.sort(key=lambda i: i.get("final_rank", i.get("rank", 0.0)), reverse=True)
    combined = all_items[:_TYPEAHEAD_COMBINED_CAP]

    # Normalise: remove internal tracking fields from the combined items
    clean_combined = []
    for item in combined:
        clean = {k: v for k, v in item.items() if k not in ("final_rank", "assignee_id", "reporter_id")}
        clean_combined.append(clean)

    # Also strip internal fields from per-arm items
    for arm_key in result:
        arm_items = result[arm_key].get("items", [])
        result[arm_key]["items"] = [
            {k: v for k, v in it.items() if k not in ("final_rank", "assignee_id", "reporter_id")}
            for it in arm_items
        ]

    result["combined"] = clean_combined
    return result


# ---------------------------------------------------------------------------
# Problems arm — typeahead
# ---------------------------------------------------------------------------

async def _ta_problems(
    db: AsyncSession,
    query: str,
    *,
    current_user_id: uuid.UUID | None,
    recency_weight: float,
    entity_weights: dict[str, float],
) -> dict[str, Any]:
    weight = entity_weights.get("problem", 0.9)
    params: dict[str, Any] = {
        "query": query,
        "lim": _TYPEAHEAD_ARM_CAP,
        "trgm_thresh": _TRGM_SIMILARITY_THRESHOLD,
        **_ilike_params(query),
    }

    sql = text("""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :query) AS q
        ),
        fts_hits AS (
            SELECT
                p.id, p.title, p.description, p.status, p.created_at,
                NULL::uuid AS assignee_id, NULL::uuid AS reporter_id,
                ts_rank(p.search_vector, tsq.q) AS base_rank,
                'fts' AS match_mode
            FROM problems p, tsq
            WHERE p.search_vector @@ tsq.q
        ),
        trgm_hits AS (
            SELECT
                p.id, p.title, p.description, p.status, p.created_at,
                NULL::uuid AS assignee_id, NULL::uuid AS reporter_id,
                similarity(p.title, :query) * 0.5 AS base_rank,
                'trgm' AS match_mode
            FROM problems p
            WHERE similarity(p.title, :query) >= :trgm_thresh
              AND NOT EXISTS (
                  SELECT 1 FROM fts_hits f WHERE f.id = p.id
              )
        ),
        all_hits AS (
            SELECT * FROM fts_hits
            UNION ALL
            SELECT * FROM trgm_hits
        )
        SELECT id, title, description, status, created_at,
               assignee_id, reporter_id, base_rank, match_mode
        FROM all_hits
        ORDER BY base_rank DESC
        LIMIT :lim
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for row in rows:
        br = float(row["base_rank"] or 0.0)
        final_rank = _recency_boost(br, row["created_at"], recency_weight) * weight
        items.append({
            "id": str(row["id"]),
            "display_id": None,
            "title": row["title"],
            "subtitle": _trunc(row["description"]),
            "kind": "problem",
            "href": f"/problems/{row['id']}",
            "rank": br,
            "final_rank": final_rank,
            "project_id": None,
            "status": row["status"],
            "assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
            "reporter_id": str(row["reporter_id"]) if row["reporter_id"] else None,
        })

    items.sort(key=lambda i: i["final_rank"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "next_cursor": None,
        "total_authority": "snapshot",
    }


# ---------------------------------------------------------------------------
# Tickets arm — typeahead
# ---------------------------------------------------------------------------

async def _ta_tickets(
    db: AsyncSession,
    query: str,
    *,
    current_user_id: uuid.UUID | None,
    recency_weight: float,
    entity_weights: dict[str, float],
) -> dict[str, Any]:
    weight = entity_weights.get("ticket", 1.0)
    escaped_q = _escape_like(query.lower())
    params: dict[str, Any] = {
        "query_text": query,
        "display_like": f"%{escaped_q}%",
        "lim": _TYPEAHEAD_ARM_CAP,
        "trgm_thresh": _TRGM_SIMILARITY_THRESHOLD,
    }

    sql = text(r"""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :query_text) AS q
        ),
        fts_hits AS (
            SELECT
                t.id, t.display_id, t.title, t.description,
                t.project_id, t.status, t.created_at,
                t.assignee_id, t.reporter_id,
                ts_rank(t.search_tsv, tsq.q) AS base_rank,
                'fts' AS match_mode
            FROM tickets t, tsq
            WHERE (
                t.search_tsv @@ tsq.q
                OR lower(t.display_id) LIKE :display_like ESCAPE E'\\'
            )
        ),
        trgm_hits AS (
            SELECT
                t.id, t.display_id, t.title, t.description,
                t.project_id, t.status, t.created_at,
                t.assignee_id, t.reporter_id,
                similarity(t.title, :query_text) * 0.5 AS base_rank,
                'trgm' AS match_mode
            FROM tickets t
            WHERE similarity(t.title, :query_text) >= :trgm_thresh
              AND NOT EXISTS (
                  SELECT 1 FROM fts_hits f WHERE f.id = t.id
              )
        ),
        all_hits AS (
            SELECT * FROM fts_hits
            UNION ALL
            SELECT * FROM trgm_hits
        )
        SELECT id, display_id, title, description, project_id, status,
               created_at, assignee_id, reporter_id, base_rank, match_mode
        FROM all_hits
        ORDER BY base_rank DESC
        LIMIT :lim
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for row in rows:
        br = float(row["base_rank"] or 0.0)
        pers = _personalisation_boost(
            {"assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
             "reporter_id": str(row["reporter_id"]) if row["reporter_id"] else None},
            current_user_id,
        )
        final_rank = (_recency_boost(br, row["created_at"], recency_weight) + pers) * weight
        items.append({
            "id": str(row["id"]),
            "display_id": row["display_id"],
            "title": row["title"],
            "subtitle": _trunc(row["description"]),
            "kind": "ticket",
            "href": f"/tickets/{row['display_id']}",
            "rank": br,
            "final_rank": final_rank,
            "project_id": str(row["project_id"]) if row["project_id"] else None,
            "status": str(row["status"]) if row["status"] else None,
            "assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
            "reporter_id": str(row["reporter_id"]) if row["reporter_id"] else None,
        })

    items.sort(key=lambda i: i["final_rank"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "next_cursor": None,
        "total_authority": "snapshot",
    }


# ---------------------------------------------------------------------------
# Components arm — typeahead
# ---------------------------------------------------------------------------

async def _ta_components(
    db: AsyncSession,
    query: str,
    *,
    recency_weight: float,
    entity_weights: dict[str, float],
) -> dict[str, Any]:
    weight = entity_weights.get("component", 0.7)
    rank_expr = _ilike_rank("c.name", query)
    params: dict[str, Any] = {
        "lim": _TYPEAHEAD_ARM_CAP,
        "trgm_thresh": _TRGM_SIMILARITY_THRESHOLD,
        "query": query,
        **_ilike_params(query),
    }

    sql = text(f"""
        WITH ilike_hits AS (
            SELECT
                c.id, c.name, c.description, c.project_id,
                NULL::timestamptz AS created_at,
                {rank_expr} AS base_rank,
                'ilike' AS match_mode
            FROM components c
            WHERE lower(c.name) LIKE :q_ilike ESCAPE E'\\\\'
        ),
        trgm_hits AS (
            SELECT
                c.id, c.name, c.description, c.project_id,
                NULL::timestamptz AS created_at,
                similarity(c.name, :query) * 0.5 AS base_rank,
                'trgm' AS match_mode
            FROM components c
            WHERE similarity(c.name, :query) >= :trgm_thresh
              AND NOT EXISTS (
                  SELECT 1 FROM ilike_hits h WHERE h.id = c.id
              )
        ),
        all_hits AS (
            SELECT * FROM ilike_hits UNION ALL SELECT * FROM trgm_hits
        )
        SELECT id, name, description, project_id, created_at, base_rank, match_mode
        FROM all_hits
        ORDER BY base_rank DESC
        LIMIT :lim
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for row in rows:
        br = float(row["base_rank"] or 0.0)
        final_rank = br * weight
        items.append({
            "id": str(row["id"]),
            "display_id": None,
            "title": row["name"],
            "subtitle": _trunc(row["description"]),
            "kind": "component",
            "href": f"/components/{row['id']}",
            "rank": br,
            "final_rank": final_rank,
            "project_id": str(row["project_id"]) if row["project_id"] else None,
            "status": None,
        })

    items.sort(key=lambda i: i["final_rank"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "next_cursor": None,
        "total_authority": "snapshot",
    }


# ---------------------------------------------------------------------------
# Labels arm — typeahead
# ---------------------------------------------------------------------------

async def _ta_labels(
    db: AsyncSession,
    query: str,
    *,
    entity_weights: dict[str, float],
) -> dict[str, Any]:
    weight = entity_weights.get("label", 0.6)
    rank_expr = _ilike_rank("t.name", query)
    params: dict[str, Any] = {
        "lim": _TYPEAHEAD_ARM_CAP,
        "trgm_thresh": _TRGM_SIMILARITY_THRESHOLD,
        "query": query,
        **_ilike_params(query),
    }

    sql = text(f"""
        WITH ilike_hits AS (
            SELECT
                t.id, t.name,
                {rank_expr} AS base_rank,
                'ilike' AS match_mode
            FROM tags t
            WHERE lower(t.name) LIKE :q_ilike ESCAPE E'\\\\'
        ),
        trgm_hits AS (
            SELECT
                t.id, t.name,
                similarity(t.name, :query) * 0.5 AS base_rank,
                'trgm' AS match_mode
            FROM tags t
            WHERE similarity(t.name, :query) >= :trgm_thresh
              AND NOT EXISTS (
                  SELECT 1 FROM ilike_hits h WHERE h.id = t.id
              )
        ),
        all_hits AS (
            SELECT * FROM ilike_hits UNION ALL SELECT * FROM trgm_hits
        )
        SELECT id, name, base_rank, match_mode
        FROM all_hits
        ORDER BY base_rank DESC
        LIMIT :lim
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for row in rows:
        br = float(row["base_rank"] or 0.0)
        final_rank = br * weight
        items.append({
            "id": str(row["id"]),
            "display_id": None,
            "title": row["name"],
            "subtitle": "",
            "kind": "label",
            "href": f"/labels/{row['name']}",
            "rank": br,
            "final_rank": final_rank,
            "project_id": None,
            "status": None,
        })

    items.sort(key=lambda i: i["final_rank"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "next_cursor": None,
        "total_authority": "snapshot",
    }


# ---------------------------------------------------------------------------
# Users arm — typeahead
# ---------------------------------------------------------------------------

async def _ta_users(
    db: AsyncSession,
    query: str,
    *,
    entity_weights: dict[str, float],
) -> dict[str, Any]:
    weight = entity_weights.get("user", 0.5)
    user_rank_expr = _ilike_rank("u.handle", query)
    agent_rank_expr = _ilike_rank("a.handle", query)
    params: dict[str, Any] = {
        "lim": _TYPEAHEAD_ARM_CAP,
        "trgm_thresh": _TRGM_SIMILARITY_THRESHOLD,
        "query": query,
        **_ilike_params(query),
    }

    sql = text(f"""
        WITH ilike_hits AS (
            SELECT
                u.id, u.handle, u.display_name, 'user' AS kind,
                {user_rank_expr} AS base_rank
            FROM users u
            WHERE lower(u.handle) LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(u.display_name) LIKE :q_ilike ESCAPE E'\\\\'
            UNION ALL
            SELECT
                a.id, a.handle, a.name AS display_name, 'agent' AS kind,
                {agent_rank_expr} AS base_rank
            FROM agent_accounts a
            WHERE lower(a.handle) LIKE :q_ilike ESCAPE E'\\\\'
               OR lower(a.name) LIKE :q_ilike ESCAPE E'\\\\'
        )
        SELECT id, handle, display_name, kind, base_rank
        FROM ilike_hits
        ORDER BY base_rank DESC
        LIMIT :lim
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    items = []
    for row in rows:
        br = float(row["base_rank"] or 0.0)
        w = entity_weights.get(row["kind"], weight)
        final_rank = br * w
        items.append({
            "id": str(row["id"]),
            "display_id": row["handle"],
            "title": row["display_name"],
            "subtitle": f"@{row['handle']}",
            "kind": row["kind"],
            "href": f"/users/{row['handle']}",
            "rank": br,
            "final_rank": final_rank,
            "project_id": None,
            "status": None,
        })

    items.sort(key=lambda i: i["final_rank"], reverse=True)
    return {
        "items": items,
        "total": len(items),
        "next_cursor": None,
        "total_authority": "snapshot",
    }
