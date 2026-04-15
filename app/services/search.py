"""Full-text search and similar-problem suggestion service.

REQ-350, REQ-352, REQ-354, REQ-356, REQ-358, REQ-360, REQ-362, REQ-364.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem import Problem


# ---------------------------------------------------------------------------
# Helper: manually refresh search_vector for a problem
# ---------------------------------------------------------------------------

async def update_search_vector(db: AsyncSession, problem: Problem) -> None:
    """Recompute and persist the tsvector for a single problem."""
    await db.execute(
        text(
            "UPDATE problems "
            "SET search_vector = to_tsvector('english', title || ' ' || description) "
            "WHERE id = :id"
        ),
        {"id": str(problem.id)},
    )


# ---------------------------------------------------------------------------
# Core search
# ---------------------------------------------------------------------------

_EXCERPT_LEN = 120


def _truncate(value: str | None, length: int = _EXCERPT_LEN) -> str:
    """Return the first *length* characters of *value*, adding ellipsis if truncated."""
    if not value:
        return ""
    if len(value) <= length:
        return value
    return value[:length] + "..."


async def search_problems(
    db: AsyncSession,
    query: str,
    *,
    sort: str = "relevance",
    category_id: uuid.UUID | None = None,
    tag_ids: list[uuid.UUID] | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Full-text search across problems, solutions, and comments.

    Returns ``{"results": [...], "total": int}`` or
    ``{"results": [], "message": "No results found"}`` when empty (REQ-360).
    """
    if not query or not query.strip():
        return {"results": [], "message": "No results found"}

    # Check if query is an AION-XXX ticket ID
    import re
    ticket_match = re.match(r'^AION-(\d+)$', query.strip(), re.IGNORECASE)
    if ticket_match:
        seq = int(ticket_match.group(1))
        from app.models.problem import Problem
        from sqlalchemy import select
        result = await db.execute(
            select(Problem).where(Problem.seq_number == seq)
        )
        problem = result.scalar_one_or_none()
        if problem:
            return {"results": [{
                "problem_id": str(problem.id),
                "title": problem.title,
                "excerpt": _truncate(problem.description),
                "rank": 1.0,
                "match_source": "ticket_id",
                "upstar_count": 0,
                "created_at": problem.created_at.isoformat() if problem.created_at else None,
            }]}
        return {"results": [], "message": "No results found"}

    # Raw SQL for clarity with PostgreSQL-specific full-text operators.

    # Base WHERE fragments
    where_clauses: list[str] = []
    params: dict[str, Any] = {"query": query, "lim": limit, "off": offset}

    if category_id is not None:
        where_clauses.append("p.category_id = :category_id")
        params["category_id"] = str(category_id)

    if status is not None:
        where_clauses.append("p.status = :status")
        params["status"] = status

    tag_join = ""
    if tag_ids:
        placeholders = ", ".join(f":tag_{i}" for i in range(len(tag_ids)))
        tag_join = (
            f" INNER JOIN problem_tags pt ON pt.problem_id = p.id"
            f" AND pt.tag_id IN ({placeholders})"
        )
        for i, tid in enumerate(tag_ids):
            params[f"tag_{i}"] = str(tid)

    filter_clause = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    # --- Sort (REQ-356) -------------------------------------------------------
    sort_sql_map = {
        "relevance": "rank DESC",
        "upvotes": "upstar_count DESC",
        "newest": "p_created_at DESC",
    }
    order_by = sort_sql_map.get(sort, "rank DESC")

    sql = text(f"""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :query) AS q
        ),

        -- 1. Problems matched directly (REQ-350/352)
        problem_hits AS (
            SELECT
                p.id            AS problem_id,
                p.title         AS title,
                LEFT(p.description, 120) AS excerpt,
                ts_rank(p.search_vector, tsq.q) AS rank,
                'problem'       AS match_source,
                (SELECT count(*) FROM upstars u WHERE u.problem_id = p.id) AS upstar_count,
                p.created_at    AS p_created_at
            FROM problems p{tag_join}, tsq
            WHERE p.search_vector @@ tsq.q{filter_clause}
        ),

        -- 2. Solutions whose description matches, rolled up to parent problem (REQ-354)
        solution_hits AS (
            SELECT
                p.id            AS problem_id,
                p.title         AS title,
                LEFT(sv.description, 120) AS excerpt,
                ts_rank(
                    to_tsvector('english', sv.description),
                    tsq.q
                ) AS rank,
                'solution'      AS match_source,
                (SELECT count(*) FROM upstars u WHERE u.problem_id = p.id) AS upstar_count,
                p.created_at    AS p_created_at
            FROM solution_versions sv
            JOIN solutions s ON s.id = sv.solution_id AND s.current_version_id = sv.id
            JOIN problems p ON p.id = s.problem_id{tag_join}, tsq
            WHERE to_tsvector('english', sv.description) @@ tsq.q{filter_clause}
        ),

        -- 3. Comments whose body matches, rolled up to parent problem (REQ-354)
        comment_hits AS (
            SELECT
                p.id            AS problem_id,
                p.title         AS title,
                LEFT(c.body, 120) AS excerpt,
                ts_rank(
                    to_tsvector('english', c.body),
                    tsq.q
                ) AS rank,
                'comment'       AS match_source,
                (SELECT count(*) FROM upstars u WHERE u.problem_id = p.id) AS upstar_count,
                p.created_at    AS p_created_at
            FROM comments c
            JOIN problems p ON p.id = c.problem_id{tag_join}, tsq
            WHERE to_tsvector('english', c.body) @@ tsq.q{filter_clause}
        ),

        -- Combine and deduplicate by problem_id, keeping the best rank per problem
        combined AS (
            SELECT DISTINCT ON (problem_id)
                problem_id,
                title,
                excerpt,
                rank,
                match_source,
                upstar_count,
                p_created_at
            FROM (
                SELECT * FROM problem_hits
                UNION ALL
                SELECT * FROM solution_hits
                UNION ALL
                SELECT * FROM comment_hits
            ) all_hits
            ORDER BY problem_id, rank DESC
        )

        SELECT
            problem_id,
            title,
            excerpt,
            rank,
            match_source,
            upstar_count,
            p_created_at
        FROM combined
        ORDER BY {order_by}
        LIMIT :lim OFFSET :off
    """)

    result = await db.execute(sql, params)
    rows = result.mappings().all()

    if not rows:
        return {"results": [], "message": "No results found"}

    results = [
        {
            "problem_id": str(row["problem_id"]),
            "title": row["title"],
            "excerpt": row["excerpt"] or "",
            "rank": float(row["rank"]),
            "match_source": row["match_source"],
            "upstar_count": row["upstar_count"],
            "created_at": row["p_created_at"].isoformat() if row["p_created_at"] else None,
        }
        for row in rows
    ]

    return {"results": results}


# ---------------------------------------------------------------------------
# Similar-problem suggestions (REQ-362)
# ---------------------------------------------------------------------------

async def suggest_similar(
    db: AsyncSession,
    title: str,
    *,
    exclude_problem_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to *limit* problems whose search_vector matches *title*."""
    if not title or not title.strip():
        return []

    params: dict[str, Any] = {"title": title, "lim": limit}

    exclude_clause = ""
    if exclude_problem_id is not None:
        exclude_clause = "AND p.id != :exclude_id"
        params["exclude_id"] = str(exclude_problem_id)

    sql = text(f"""
        WITH tsq AS (
            SELECT plainto_tsquery('english', :title) AS q
        )
        SELECT
            p.id            AS problem_id,
            p.title         AS title,
            LEFT(p.description, 120) AS excerpt,
            ts_rank(p.search_vector, tsq.q) AS rank
        FROM problems p, tsq
        WHERE p.search_vector @@ tsq.q
            {exclude_clause}
        ORDER BY rank DESC
        LIMIT :lim
    """)

    result = await db.execute(sql, params)
    rows = result.mappings().all()

    return [
        {
            "problem_id": str(row["problem_id"]),
            "title": row["title"],
            "excerpt": row["excerpt"] or "",
            "rank": float(row["rank"]),
        }
        for row in rows
    ]
