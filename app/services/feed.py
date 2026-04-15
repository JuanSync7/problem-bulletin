"""Feed service — cursor pagination, sorting, and filtering for the problem feed.

REQ-168, REQ-170, REQ-172, REQ-174, REQ-176, REQ-178, REQ-180, REQ-182
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import ProblemStatus, SortMode
from app.models.comment import Comment
from app.models.problem import Claim, Problem, Upstar
from app.schemas import CursorPage, ProblemResponse


# ---------------------------------------------------------------------------
# Cursor encode / decode  (REQ-168)
# ---------------------------------------------------------------------------


def encode_cursor(sort_value: Any, row_id: uuid.UUID) -> str:
    """Serialize (sort_value, id) into an opaque base64-JSON cursor."""
    if isinstance(sort_value, datetime):
        payload = {"v": sort_value.isoformat(), "id": str(row_id), "t": "dt"}
    elif isinstance(sort_value, int):
        payload = {"v": sort_value, "id": str(row_id), "t": "int"}
    else:
        payload = {"v": str(sort_value), "id": str(row_id), "t": "str"}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[Any, uuid.UUID]:
    """Decode an opaque cursor back to (sort_value, id).

    Raises HTTPException 400 on malformed input.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
        row_id = uuid.UUID(payload["id"])
        t = payload["t"]
        if t == "dt":
            sort_value = datetime.fromisoformat(payload["v"])
        elif t == "int":
            sort_value = int(payload["v"])
        else:
            sort_value = payload["v"]
        return sort_value, row_id
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed cursor",
        )


# ---------------------------------------------------------------------------
# Sort helpers  (REQ-170)
# ---------------------------------------------------------------------------

# Subqueries used by sort modes that need aggregated counts.
_upstar_count_subq = (
    select(func.count())
    .where(Upstar.problem_id == Problem.id)
    .correlate(Problem)
    .scalar_subquery()
    .label("upstar_count")
)

_comment_count_subq = (
    select(func.count())
    .where(Comment.problem_id == Problem.id)
    .correlate(Problem)
    .scalar_subquery()
    .label("comment_count")
)


def _apply_sort(
    stmt: Select,
    sort: SortMode,
) -> tuple[Select, Any]:
    """Add ORDER BY to *stmt* and return (stmt, sort_column) for keyset pagination."""
    if sort == SortMode.new:
        sort_col = Problem.created_at
        stmt = stmt.order_by(Problem.created_at.desc(), Problem.id.desc())
    elif sort == SortMode.top:
        sort_col = _upstar_count_subq
        stmt = stmt.add_columns(_upstar_count_subq).order_by(
            _upstar_count_subq.desc(), Problem.id.desc()
        )
    elif sort == SortMode.active:
        sort_col = Problem.activity_at
        stmt = stmt.order_by(Problem.activity_at.desc(), Problem.id.desc())
    elif sort == SortMode.discussed:
        sort_col = _comment_count_subq
        stmt = stmt.add_columns(_comment_count_subq).order_by(
            _comment_count_subq.desc(), Problem.id.desc()
        )
    else:
        sort_col = Problem.created_at
        stmt = stmt.order_by(Problem.created_at.desc(), Problem.id.desc())
    return stmt, sort_col


# ---------------------------------------------------------------------------
# Filter composition  (REQ-172)
# ---------------------------------------------------------------------------


def _apply_filters(
    stmt: Select,
    *,
    filter_status: ProblemStatus | None = None,
    category_id: str | None = None,
    tag_ids: list[str] | None = None,
    is_claimed: bool | None = None,
) -> Select:
    """AND together all non-None filters."""
    conditions: list[Any] = []

    if filter_status is not None:
        conditions.append(Problem.status == filter_status.value)

    if category_id is not None:
        conditions.append(Problem.category_id == uuid.UUID(category_id))

    if tag_ids:
        from app.models.problem import ProblemTag

        tag_uuids = [uuid.UUID(t) for t in tag_ids]
        # Problem must have ALL specified tags
        for tag_uuid in tag_uuids:
            conditions.append(
                Problem.id.in_(
                    select(ProblemTag.problem_id).where(ProblemTag.tag_id == tag_uuid)
                )
            )

    if is_claimed is not None:
        claim_exists = select(Claim.id).where(Claim.problem_id == Problem.id).correlate(Problem).exists()
        if is_claimed:
            conditions.append(claim_exists)
        else:
            conditions.append(~claim_exists)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    return stmt


# ---------------------------------------------------------------------------
# Keyset pagination cursor application  (REQ-176)
# ---------------------------------------------------------------------------


def _apply_cursor(
    stmt: Select,
    sort: SortMode,
    cursor_value: Any,
    cursor_id: uuid.UUID,
) -> Select:
    """Apply WHERE (sort_col, id) < (cursor_val, cursor_id) for keyset pagination."""
    if sort == SortMode.new:
        stmt = stmt.where(
            (Problem.created_at < cursor_value)
            | ((Problem.created_at == cursor_value) & (Problem.id < cursor_id))
        )
    elif sort == SortMode.active:
        stmt = stmt.where(
            (Problem.activity_at < cursor_value)
            | ((Problem.activity_at == cursor_value) & (Problem.id < cursor_id))
        )
    elif sort == SortMode.top:
        # For subquery-based sorts we use HAVING-style filtering via a CTE or
        # a wrapping approach.  The simplest correct path: filter in a WHERE
        # clause using the same correlated subquery.
        upstar_cnt = (
            select(func.count())
            .where(Upstar.problem_id == Problem.id)
            .correlate(Problem)
            .scalar_subquery()
        )
        stmt = stmt.where(
            (upstar_cnt < cursor_value)
            | ((upstar_cnt == cursor_value) & (Problem.id < cursor_id))
        )
    elif sort == SortMode.discussed:
        comment_cnt = (
            select(func.count())
            .where(Comment.problem_id == Problem.id)
            .correlate(Problem)
            .scalar_subquery()
        )
        stmt = stmt.where(
            (comment_cnt < cursor_value)
            | ((comment_cnt == cursor_value) & (Problem.id < cursor_id))
        )
    return stmt


# ---------------------------------------------------------------------------
# Main feed query  (REQ-174, REQ-176, REQ-178)
# ---------------------------------------------------------------------------


def _build_response(problem: Problem, upstar_count: int, comment_count: int) -> dict[str, Any]:
    """Build a ProblemResponse-compatible dict from a Problem row."""
    author_dict = None
    if problem.author and not problem.is_anonymous:
        author_dict = {
            "id": str(problem.author.id),
            "display_name": problem.author.display_name,
            "email": problem.author.email,
            "role": problem.author.role,
            "created_at": problem.author.created_at,
        }

    category_dict = {}
    if problem.category:
        category_dict = {
            "id": str(problem.category.id),
            "name": problem.category.name,
            "slug": problem.category.slug,
        }

    domain_dict = None
    if problem.domain:
        domain_dict = {
            "id": str(problem.domain.id),
            "name": problem.domain.name,
            "slug": problem.domain.slug,
        }

    tags_list = [
        {"id": str(t.id), "name": t.name} for t in (problem.tags or [])
    ]

    solution_count = len(problem.solutions) if problem.solutions else 0

    display_id = f"AION-{problem.seq_number:03d}" if problem.seq_number else None

    return {
        "id": str(problem.id),
        "seq_number": problem.seq_number,
        "display_id": display_id,
        "title": problem.title,
        "description": problem.description,
        "author": author_dict,
        "status": problem.status,
        "category": category_dict,
        "domain": domain_dict,
        "tags": tags_list,
        "upstar_count": upstar_count,
        "solution_count": solution_count,
        "comment_count": comment_count,
        "is_pinned": problem.is_pinned,
        "created_at": problem.created_at,
        "activity_at": problem.activity_at,
    }


def _eager_options():
    """Return common selectinload options for feed queries."""
    return [
        selectinload(Problem.author),
        selectinload(Problem.category),
        selectinload(Problem.domain),
        selectinload(Problem.tags),
        selectinload(Problem.solutions),
        selectinload(Problem.upstars),
        selectinload(Problem.comments),
    ]


async def get_feed(
    db: AsyncSession,
    *,
    sort: SortMode = SortMode.new,
    filter_status: ProblemStatus | None = None,
    category_id: str | None = None,
    tag_ids: list[str] | None = None,
    is_claimed: bool | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> CursorPage[ProblemResponse]:
    """Return a paginated, sorted, filtered feed of problems.

    REQ-168, REQ-170, REQ-172, REQ-174, REQ-176, REQ-178
    """
    limit = min(limit, 50)

    # -- Pinned-above logic (REQ-174): first page only ----------------------
    pinned_items: list[dict[str, Any]] = []
    if cursor is None:
        pinned_stmt = (
            select(Problem)
            .where(Problem.is_pinned.is_(True))
            .options(*_eager_options())
        )
        pinned_stmt = _apply_filters(
            pinned_stmt,
            filter_status=filter_status,
            category_id=category_id,
            tag_ids=tag_ids,
            is_claimed=is_claimed,
        )
        # Always sort pinned by newest first
        pinned_stmt = pinned_stmt.order_by(Problem.created_at.desc())
        pinned_result = await db.execute(pinned_stmt)
        pinned_problems = pinned_result.scalars().unique().all()

        for p in pinned_problems:
            u_count = len(p.upstars) if p.upstars else 0
            c_count = len(p.comments) if p.comments else 0
            pinned_items.append(_build_response(p, u_count, c_count))

    # -- Main query ---------------------------------------------------------
    # Exclude pinned from normal results to avoid duplicates
    base_stmt = select(Problem).where(Problem.is_pinned.is_(False)).options(*_eager_options())

    # Apply filters
    base_stmt = _apply_filters(
        base_stmt,
        filter_status=filter_status,
        category_id=category_id,
        tag_ids=tag_ids,
        is_claimed=is_claimed,
    )

    # Apply sort
    base_stmt, sort_col = _apply_sort(base_stmt, sort)

    # Apply cursor for keyset pagination
    if cursor is not None:
        cursor_value, cursor_id = decode_cursor(cursor)
        base_stmt = _apply_cursor(base_stmt, sort, cursor_value, cursor_id)

    # Fetch limit + 1 to detect has_next
    base_stmt = base_stmt.limit(limit + 1)

    result = await db.execute(base_stmt)

    # For sort modes that add_columns (top, discussed), rows are tuples
    if sort in (SortMode.top, SortMode.discussed):
        rows = result.unique().all()
        problems_with_counts = []
        for row in rows:
            problem = row[0]
            aggregated_val = row[1]
            problems_with_counts.append((problem, aggregated_val))
    else:
        raw_problems = result.scalars().unique().all()
        problems_with_counts = [(p, None) for p in raw_problems]

    # Determine has_next
    has_next = len(problems_with_counts) > limit
    if has_next:
        problems_with_counts = problems_with_counts[:limit]

    # Build response items
    items: list[dict[str, Any]] = []
    last_sort_value: Any = None
    last_id: uuid.UUID | None = None

    for problem, agg_val in problems_with_counts:
        u_count = agg_val if sort == SortMode.top else (len(problem.upstars) if problem.upstars else 0)
        c_count = agg_val if sort == SortMode.discussed else (len(problem.comments) if problem.comments else 0)
        items.append(_build_response(problem, u_count, c_count))

        # Track last values for cursor
        if sort == SortMode.new:
            last_sort_value = problem.created_at
        elif sort == SortMode.active:
            last_sort_value = problem.activity_at
        elif sort == SortMode.top:
            last_sort_value = agg_val
        elif sort == SortMode.discussed:
            last_sort_value = agg_val
        last_id = problem.id

    # Build next_cursor
    next_cursor: str | None = None
    if has_next and last_id is not None:
        next_cursor = encode_cursor(last_sort_value, last_id)

    # Prepend pinned items (they don't consume limit slots)
    all_items = pinned_items + items

    return CursorPage(
        items=[ProblemResponse(**item) for item in all_items],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# Activity touch helper  (REQ-182)
# ---------------------------------------------------------------------------


async def touch_activity(db: AsyncSession, problem_id: str) -> None:
    """Update problem.activity_at to now(). Call after comments, solutions, etc."""
    from sqlalchemy import update

    stmt = (
        update(Problem)
        .where(Problem.id == uuid.UUID(problem_id))
        .values(activity_at=func.now())
    )
    await db.execute(stmt)
