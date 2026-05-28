"""Search routes — full-text search and similar-problem suggestions.

REQ-350 through REQ-364.

WP56: adds GET /search/v2 — multi-entity search backed by search_entities().
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services._pagination import InvalidCursorError
from app.services.search import search_problems, suggest_similar
from app.services.search_multi import _VALID_ENTITIES, search_entities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# ---------------------------------------------------------------------------
# v2.11-WP13 (E1) — v1 /api/search deprecation
# ---------------------------------------------------------------------------
#
# The v1 ``GET /api/search`` endpoint is **deprecated** in favour of
# ``/api/search/v2`` (multi-entity, cursor-paginated). v2.10-WP09 confirmed
# zero live callers in source (only stale built artifacts referenced the
# v1 surface). This module emits RFC 8594 ``Deprecation`` / ``Sunset``
# headers on every v1 response and logs a WARN-level instrumentation
# line so any straggling caller surfaces in monitoring before removal.
#
# Sunset date: ~60 days from the deprecation landing (2026-05-22) →
# **Sun, 22 Jul 2026 00:00:00 GMT** (RFC 1123). Update if the monitoring
# window needs to be extended.
V1_SEARCH_SUNSET_RFC1123 = "Sun, 22 Jul 2026 00:00:00 GMT"


def _resolve_v1_caller(request: Request) -> str:
    """Best-effort caller resolver for v1 /api/search instrumentation.

    Prefers ``Authorization`` header presence (logged as ``auth:<scheme>``
    without leaking the credential), falling back to the client IP. Never
    raises — returns ``"unknown"`` on any failure.
    """
    try:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth:
            scheme = auth.split(" ", 1)[0] if " " in auth else auth.split(".", 1)[0]
            return f"auth:{scheme[:16]}"
        client = getattr(request, "client", None)
        host = getattr(client, "host", None) if client else None
        if host:
            return f"ip:{host}"
    except Exception:  # pragma: no cover — defensive
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# WP56 — Pydantic response models for /v2
# ---------------------------------------------------------------------------

_ENTITY_VALUES = frozenset(_VALID_ENTITIES)


class SearchItem(BaseModel):
    """Normalised search result item (common shape for all entity arms)."""

    id: str
    display_id: str | None
    title: str
    subtitle: str
    kind: str
    href: str
    rank: float
    project_id: str | None
    status: str | None

    model_config = {"extra": "allow"}


class SearchArm(BaseModel):
    """One entity arm: list of items + total count + optional next-page cursor.

    WP62: ``next_cursor`` is an opaque HMAC-signed string. Clients pass it
    back as the per-arm ``<arm>_cursor`` query param (or ``cursor=`` in
    single-arm mode) to fetch the next page. ``null`` when there is no
    next page.
    """

    items: list[SearchItem]
    total: int
    next_cursor: str | None = None
    # v2.11-WP14 (F1): "snapshot" when ``total`` reflects the WP10 first-page
    # pinned count; "live" when the caller forced a re-count via
    # ``refresh_total=1``. Optional from the client's perspective —
    # absent on older arms is treated as "snapshot".
    total_authority: str | None = None


class SearchV2Response(BaseModel):
    """Response envelope for GET /search/v2.

    Keys present depend on the ``entity`` query parameter:
    - ``entity=all``  → all five arms (problems, tickets, components, labels, users)
    - ``entity=<x>``  → only the ``<x>`` arm
    """

    problems: SearchArm | None = None
    tickets: SearchArm | None = None
    components: SearchArm | None = None
    labels: SearchArm | None = None
    users: SearchArm | None = None


@router.get("/v2", response_model=SearchV2Response, summary="Multi-entity search (WP56)")
async def search_v2(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., description="Search query. Empty string returns empty arms."),
    entity: str = Query(
        "all",
        description="Entity scope: all | problems | tickets | components | labels | users",
    ),
    problem_status: str | None = Query(None, description="Filter problems by status"),
    problem_category_id: uuid.UUID | None = Query(None, description="Filter problems by category UUID"),
    ticket_status: str | None = Query(None, description="Filter tickets by status"),
    ticket_project_id: uuid.UUID | None = Query(None, description="Filter tickets by project UUID"),
    component_project_id: uuid.UUID | None = Query(None, description="Filter components by project UUID"),
    limit: int = Query(20, ge=1, le=100, description="Max items per arm"),
    offset: int = Query(0, ge=0, description="Pagination offset (applied to each arm independently)"),
    cursor: str | None = Query(
        None,
        description="WP62: single-arm cursor. When set with entity=<arm>, paginates that arm.",
    ),
    problems_cursor: str | None = Query(None, description="WP62: cursor for problems arm (entity=all)"),
    tickets_cursor: str | None = Query(None, description="WP62: cursor for tickets arm (entity=all)"),
    components_cursor: str | None = Query(None, description="WP62: cursor for components arm (entity=all)"),
    labels_cursor: str | None = Query(None, description="WP62: cursor for labels arm (entity=all)"),
    users_cursor: str | None = Query(None, description="WP62: cursor for users arm (entity=all)"),
    refresh_total: bool = Query(
        False,
        description=(
            "v2.11-WP14: when true, force a live re-count on the current page "
            "instead of honouring the WP10 cursor-pinned snapshot total. The "
            "response arm's ``total_authority`` will read 'live'."
        ),
    ),
):
    """Multi-entity search across Problems, Tickets, Components, Labels, and Users.

    Returns one envelope per requested entity arm: ``{arm: {items: [...], total: int}}``.
    When ``entity=all`` (default), all five arms are returned; when ``entity=<x>``, only
    the ``<x>`` arm is returned.

    Empty ``q`` is allowed and immediately returns arms with ``items=[]`` and ``total=0``
    without hitting the database.
    """
    if entity not in _ENTITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid entity {entity!r}. "
                f"Must be one of: {sorted(_ENTITY_VALUES)}"
            ),
        )

    # WP62: single-arm `cursor` is shorthand for the matching `<arm>_cursor`.
    # Reject ambiguous combinations (e.g. cursor= with entity=all) up front.
    arm_cursors = {
        "problems": problems_cursor,
        "tickets": tickets_cursor,
        "components": components_cursor,
        "labels": labels_cursor,
        "users": users_cursor,
    }
    if cursor is not None:
        if entity == "all":
            raise HTTPException(
                status_code=400,
                detail="cursor= is only valid with entity=<arm>; use <arm>_cursor= for entity=all",
            )
        if arm_cursors[entity] is not None:
            raise HTTPException(
                status_code=400,
                detail=f"cursor= and {entity}_cursor= are mutually exclusive",
            )
        arm_cursors[entity] = cursor

    try:
        raw = await search_entities(
            db,
            q,
            entity=entity,
            problem_status=problem_status,
            problem_category_id=problem_category_id,
            ticket_status=ticket_status,
            ticket_project_id=ticket_project_id,
            component_project_id=component_project_id,
            limit=limit,
            offset=offset,
            problems_cursor=arm_cursors["problems"],
            tickets_cursor=arm_cursors["tickets"],
            components_cursor=arm_cursors["components"],
            labels_cursor=arm_cursors["labels"],
            users_cursor=arm_cursors["users"],
            refresh_total=refresh_total,
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=f"invalid cursor: {exc}") from exc

    # Build the response model from the raw dict returned by the service.
    # Only arms present in `raw` are set; the rest remain None.
    return SearchV2Response(
        **{arm: SearchArm(**data) for arm, data in raw.items()}
    )


@router.get("", deprecated=True)
async def search(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    q: str = Query("", description="Search query string"),
    sort: str = Query("relevance", description="Sort mode: relevance | upvotes | newest"),
    category_id: uuid.UUID | None = Query(None, description="Filter by category"),
    tag_ids: list[uuid.UUID] | None = Query(None, description="Filter by tag IDs"),
    status: str | None = Query(None, description="Filter by problem status"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Full-text search across problems, solutions, and comments (REQ-350..REQ-360).

    **DEPRECATED (v2.11-WP13).** Use ``GET /api/search/v2`` instead. This
    endpoint emits ``Deprecation: true`` and ``Sunset: <RFC1123>`` headers
    per RFC 8594 and logs a WARN-level hit counter so straggling callers
    surface in monitoring. It will be removed after the monitoring
    window (sunset date in :data:`V1_SEARCH_SUNSET_RFC1123`).
    """
    # RFC 8594 deprecation signalling.
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = V1_SEARCH_SUNSET_RFC1123

    # Hit-count instrumentation — WARN level so it shows up in default
    # production log scraping. ``v1_search.hit`` is the grep tag.
    caller = _resolve_v1_caller(request)
    logger.warning("v1_search.hit caller=%s q_len=%d", caller, len(q or ""))

    return await search_problems(
        db,
        q,
        sort=sort,
        category_id=category_id,
        tag_ids=tag_ids,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/suggest")
async def suggest(
    db: AsyncSession = Depends(get_db),
    title: str = Query("", description="Problem title to find similar problems for"),
    exclude_id: uuid.UUID | None = Query(None, description="Problem ID to exclude from results"),
    limit: int = Query(5, ge=1, le=20, description="Max suggestions to return"),
):
    """Suggest similar problems based on a title (REQ-362)."""
    results = await suggest_similar(
        db,
        title,
        exclude_problem_id=exclude_id,
        limit=limit,
    )
    if not results:
        return {"results": [], "message": "No similar problems found"}
    return {"results": results}
