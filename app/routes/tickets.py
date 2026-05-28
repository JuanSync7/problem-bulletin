"""Ticket REST routes (Step 3 — Kanban work-tracker).

Thin HTTP adapter over :class:`app.services.tickets.TicketService`. Service-
layer domain exceptions translate to status codes per the error envelope
contract (NFR-904):

    TicketNotFoundError        -> 404
    OptimisticConcurrencyError -> 409 conflict (current_version, current)
    InvalidTransitionError     -> 422
    AlreadyClaimedError        -> 409 already_claimed
    DuplicateLinkError         -> 409 link_exists
    ScopeDeniedError / ForbiddenError -> 403
    ValidationError            -> 400 (HierarchyError / HasChildrenError too)

Each response carries an ``X-Correlation-Id`` header.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    AlreadyClaimedError,
    AuthError,
    DuplicateLinkError,
    ForbiddenError,
    ForbiddenTransitionError,
    InvalidTransitionError,
    OptimisticConcurrencyError,
    ScopeDeniedError,
    TicketNotFoundError,
    ValidationError,
)
from app.middleware.bearer_auth import get_actor
from app.schemas.common import Page
from app.schemas.tickets import (
    ActivityPage,
    TicketAssignBody,
    TicketAttachmentBody,
    TicketAttachmentRead,
    TicketCommentBody,
    TicketCommentRead,
    TicketCommentsList,
    TicketCreate,
    TicketLinkBody,
    TicketLinkRead,
    TicketLinksGrouped,
    TicketRead,
    TicketSubtreeResponse,
    TicketTransitionBody,
    TicketUpdate,
    TicketWatcherBody,
    TicketWatcherRead,
)
from app.services.context import Actor, current_trace_id
from app.services.tickets import TicketService

router = APIRouter(prefix="/v1/tickets", tags=["tickets"])


def _correlation_id(request: Request) -> str:
    return (
        request.headers.get("X-Correlation-Id")
        or current_trace_id()
        or uuid.uuid4().hex
    )


def _attach_corr(response: Response, corr: str) -> None:
    response.headers["X-Correlation-Id"] = corr


def _service() -> TicketService:
    return TicketService()


def _resolve_id_or_key(id_or_key: str) -> UUID | str:
    try:
        return UUID(id_or_key)
    except (ValueError, AttributeError):
        return id_or_key


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

def _envelope(code: str, message: str, *, correlation_id: str, **extras) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": extras,
            "correlation_id": correlation_id,
        }
    }


async def ticket_not_found_handler(request: Request, exc: TicketNotFoundError):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=404,
        content=_envelope("not_found", str(exc) or "ticket not found", correlation_id=corr),
        headers={"X-Correlation-Id": corr},
    )


async def occ_conflict_handler(request: Request, exc: OptimisticConcurrencyError):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=409,
        content=_envelope(
            "conflict",
            "stale version",
            correlation_id=corr,
            current_version=exc.current_version,
            current=exc.current,
        ),
        headers={"X-Correlation-Id": corr},
    )


async def invalid_transition_handler(request: Request, exc):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=422,
        content=_envelope("invalid_transition", str(exc), correlation_id=corr),
        headers={"X-Correlation-Id": corr},
    )


async def already_claimed_handler(request: Request, exc: AlreadyClaimedError):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=409,
        content=_envelope(
            "already_claimed",
            "ticket already claimed",
            correlation_id=corr,
            current_assignee_id=str(exc.current_assignee_id) if exc.current_assignee_id else None,
        ),
        headers={"X-Correlation-Id": corr},
    )


async def duplicate_link_handler(request: Request, exc: DuplicateLinkError):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=409,
        content=_envelope("link_exists", str(exc) or "duplicate link", correlation_id=corr),
        headers={"X-Correlation-Id": corr},
    )


async def forbidden_handler(request: Request, exc):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=403,
        content=_envelope("forbidden", str(exc) or "forbidden", correlation_id=corr),
        headers={"X-Correlation-Id": corr},
    )


async def validation_handler(request: Request, exc: ValidationError):
    corr = _correlation_id(request)
    fields = getattr(exc, "fields", None) or []
    return JSONResponse(
        status_code=400,
        content=_envelope(
            "validation", "validation failed", correlation_id=corr, fields=fields
        ),
        headers={"X-Correlation-Id": corr},
    )


async def auth_handler(request: Request, exc: AuthError):
    corr = _correlation_id(request)
    return JSONResponse(
        status_code=401,
        content=_envelope("unauthorized", str(exc) or "unauthorized", correlation_id=corr),
        headers={"X-Correlation-Id": corr},
    )


EXCEPTION_HANDLERS = {
    TicketNotFoundError: ticket_not_found_handler,
    OptimisticConcurrencyError: occ_conflict_handler,
    InvalidTransitionError: invalid_transition_handler,
    ForbiddenTransitionError: invalid_transition_handler,
    AlreadyClaimedError: already_claimed_handler,
    DuplicateLinkError: duplicate_link_handler,
    ScopeDeniedError: forbidden_handler,
    ForbiddenError: forbidden_handler,
    ValidationError: validation_handler,
    AuthError: auth_handler,
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=TicketRead)
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.create(
        db,
        actor=actor,
        title=payload.title,
        description=payload.description,
        type=payload.type,
        priority=payload.priority,
        parent_id=payload.parent_id,
        assignee_id=payload.assignee_id,
        assignee_type=payload.assignee_type,
        labels=payload.labels,
        custom_fields=payload.custom_fields,
        story_points=payload.story_points,
        due_date=payload.due_date,
        project_id=payload.project_id,
        project_key=payload.project_key,
        sprint_id=payload.sprint_id,
        component_id=payload.component_id,
        fix_versions=payload.fix_versions,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.get("/search", response_model=Page[TicketRead])
async def search_tickets(
    request: Request,
    response: Response,
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[TicketRead]:
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.search(db, query=q, limit=limit, offset=offset)
    _attach_corr(response, corr)
    items = [t.to_dict() for t in rows]
    return Page[TicketRead](items=items, next_cursor=None, total=None)


def _parse_id_sentinel(
    name: str, value: Optional[str], *, allow_me: bool = False, me_id: UUID | None = None
) -> UUID | str | None:
    """Validate a filter param that may be a UUID, the literal "null", or
    (when ``allow_me``) the literal "me". Returns the value the service
    layer expects:

      * ``None`` — filter not applied
      * ``"null"`` — service maps to ``WHERE col IS NULL``
      * ``UUID`` — straight equality

    Unknown non-UUID strings raise 400. (v2.1-WP10.)
    """
    if value is None:
        return None
    if value == "null":
        return "null"
    if allow_me and value == "me":
        if me_id is None:
            raise ValidationError(
                [{"name": name, "reason": "'me' requires an authenticated actor"}]
            )
        return me_id
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(
            [
                {
                    "name": name,
                    "reason": (
                        f"must be a UUID or 'null'"
                        + (" or 'me'" if allow_me else "")
                        + f"; got {value!r}"
                    ),
                }
            ]
        ) from exc


@router.get("")
async def list_tickets(
    request: Request,
    response: Response,
    status_filter: Optional[list[str]] = Query(default=None, alias="status"),
    type_filter: Optional[list[str]] = Query(default=None, alias="type"),
    assignee_id: Optional[str] = Query(default=None),
    parent_id: Optional[UUID] = Query(default=None),
    project_id: Optional[UUID] = Query(default=None),
    sprint_id: Optional[str] = Query(default=None),
    component_id: Optional[str] = Query(default=None),
    epic_id: Optional[str] = Query(default=None),
    label: Optional[list[str]] = Query(default=None),
    limit: int = Query(default=50, ge=0, le=500),
    cursor: Optional[str] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    order_by: Literal["created_at", "last_activity_at"] = Query(
        default="created_at",
        description=(
            "Column to sort by (v2.3-WP22). "
            "``created_at`` is the backward-compatible default. "
            "``last_activity_at`` surfaces recently-active tickets first "
            "so terminal-status (done/cancelled) rows are not starved past "
            "the 500-row fetch cap on busy projects."
        ),
    ),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List tickets with cursor pagination (v2.1-WP10).

    Returns a generic ``Page[TicketRead]``-shaped envelope
    ``{items, next_cursor, total}``. ``total`` is included when the
    request scopes by ``project_id`` (cheap COUNT on the existing
    keyset-friendly WHERE); otherwise ``null``.

    Filter sentinels: pass ``sprint_id=null`` / ``assignee_id=null`` /
    ``epic_id=null`` / ``component_id=null`` to match rows with the
    column ``IS NULL``. Pass ``assignee_id=me`` to match the calling
    actor's own UUID. Omitting the param entirely means "no filter".
    """
    corr = _correlation_id(request)
    svc = _service()

    parsed_assignee = _parse_id_sentinel(
        "assignee_id", assignee_id, allow_me=True, me_id=actor.id
    )
    parsed_sprint = _parse_id_sentinel("sprint_id", sprint_id)
    parsed_component = _parse_id_sentinel("component_id", component_id)
    parsed_epic = _parse_id_sentinel("epic_id", epic_id)

    # Cheap total: only when a project_id filter is applied. The Kanban
    # always scopes by project, so this gives WP11 (WIP limits) a real
    # number for free. Org-wide listings skip it to keep the route fast.
    # v2.1-WP11: ``column_counts`` follows the same trade-off — only paid
    # for under a project_id filter (single GROUP BY status). The aggregate
    # is independent of limit/cursor so Load-more pagination keeps the
    # WIP-limit chips accurate.
    count_total = project_id is not None
    include_column_counts = project_id is not None

    page = await svc.list_page(
        db,
        status=status_filter,
        type=type_filter,
        assignee_id=parsed_assignee,
        parent_id=parent_id,
        project_id=project_id,
        sprint_id=parsed_sprint,
        component_id=parsed_component,
        epic_id=parsed_epic,
        labels=label,
        limit=limit,
        offset=offset,
        cursor=cursor,
        count_total=count_total,
        include_column_counts=include_column_counts,
        order_by=order_by,
    )
    _attach_corr(response, corr)
    return {
        "items": [t.to_dict() for t in page["items"]],
        "next_cursor": page["next_cursor"],
        "total": page["total"],
        "column_counts": page.get("column_counts"),
    }


@router.get("/{id_or_key}", response_model=TicketRead)
async def get_ticket(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.get(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.patch("/{id_or_key}", response_model=TicketRead)
async def update_ticket(
    id_or_key: str,
    payload: TicketUpdate,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    patch = payload.model_dump(exclude={"version"}, exclude_unset=True)
    ticket = await svc.update(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        expected_version=payload.version,
        patch=patch,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.delete("/{id_or_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    await svc.delete(db, _resolve_id_or_key(id_or_key), actor=actor, correlation_id=corr)
    return Response(status_code=204, headers={"X-Correlation-Id": corr})


_ACTIVITY_INCLUDE_ALLOWED = frozenset({"comments", "links"})


@router.get("/{id_or_key}/transitions", response_model=ActivityPage)
async def list_transitions(
    id_or_key: str,
    request: Request,
    response: Response,
    include: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=0, le=500),
    cursor: Optional[str] = Query(default=None),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> ActivityPage:
    """Return a cursor-paginated activity feed for a ticket (v2.2-WP16).

    By default only ``ticket_transitions`` rows are returned. Pass
    ``?include=comments,links`` for a merged feed (UNION) ordered by
    ``created_at DESC``. Allowed include values: ``comments``, ``links``.
    Unknown values raise 400.

    Pagination uses an opaque ``cursor`` query parameter (same shape as
    ``GET /api/v1/tickets``). An invalid cursor raises 400.
    """
    corr = _correlation_id(request)
    include_set: set[str] = set()
    if include:
        for raw in include.split(","):
            value = raw.strip()
            if not value:
                continue
            if value not in _ACTIVITY_INCLUDE_ALLOWED:
                raise ValidationError(
                    [
                        {
                            "name": "include",
                            "reason": (
                                f"unknown include value {value!r}; "
                                f"allowed: {sorted(_ACTIVITY_INCLUDE_ALLOWED)}"
                            ),
                        }
                    ]
                )
            include_set.add(value)

    svc = _service()
    page = await svc.list_activity(
        db,
        _resolve_id_or_key(id_or_key),
        include=include_set,
        limit=limit,
        cursor=cursor,
    )
    _attach_corr(response, corr)
    return ActivityPage.model_validate(page)


@router.post("/{id_or_key}/transition", response_model=TicketRead)
async def transition_ticket(
    id_or_key: str,
    payload: TicketTransitionBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.transition(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        target_status=payload.to_status,
        reason=payload.reason,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.post("/{id_or_key}/assign", response_model=TicketRead)
async def assign_ticket(
    id_or_key: str,
    payload: TicketAssignBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.assign(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        assignee_id=payload.assignee_id,
        assignee_type=payload.assignee_type,
        expected_version=payload.expected_version,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.post("/{id_or_key}/claim", response_model=TicketRead)
async def claim_ticket(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.claim(db, _resolve_id_or_key(id_or_key), actor=actor, correlation_id=corr)
    _attach_corr(response, corr)
    return ticket.to_dict()


@router.get("/{id_or_key}/subtree", response_model=TicketSubtreeResponse)
async def get_subtree(
    id_or_key: str,
    request: Request,
    response: Response,
    max_depth: int = Query(default=5, ge=1, le=10),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.get_subtree(db, _resolve_id_or_key(id_or_key), max_depth=max_depth)
    _attach_corr(response, corr)
    return {
        "items": [
            {"depth": r["depth"], "ticket": r["ticket"].to_dict()} for r in rows
        ]
    }


@router.get("/{id_or_key}/comments", response_model=TicketCommentsList)
async def list_comments(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    comments = await svc.list_comments(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)
    return {
        "items": [
            {
                "id": str(c.id),
                "ticket_id": str(c.ticket_id),
                "author_id": str(c.author_id),
                "author_type": c.author_type,
                "body": c.body,
                "correlation_id": c.correlation_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ]
    }


@router.post(
    "/{id_or_key}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketCommentRead,
)
async def add_comment(
    id_or_key: str,
    payload: TicketCommentBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    comment = await svc.add_comment(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        body=payload.body,
        mentions=payload.mentions,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return {
        "id": str(comment.id),
        "ticket_id": str(comment.ticket_id),
        "author_id": str(comment.author_id),
        "author_type": comment.author_type,
        "body": comment.body,
        "correlation_id": comment.correlation_id,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.post(
    "/{id_or_key}/links",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketLinkRead,
)
async def create_link(
    id_or_key: str,
    payload: TicketLinkBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    source_ticket = await svc.get(db, _resolve_id_or_key(id_or_key))
    link = await svc.link(
        db,
        actor=actor,
        source_id=source_ticket.id,
        target_id=payload.target_id,
        link_type=payload.link_type,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return {
        "id": str(link.id),
        "source_id": str(link.source_id),
        "target_id": str(link.target_id),
        "link_type": link.link_type.value if hasattr(link.link_type, "value") else link.link_type,
        "created_by": str(link.created_by),
        "created_by_type": link.created_by_type,
    }


@router.get("/{id_or_key}/links", response_model=TicketLinksGrouped)
async def list_links(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    links = await svc.list_links(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)

    def _ser(link):
        return {
            "id": str(link.id),
            "source_id": str(link.source_id),
            "target_id": str(link.target_id),
            "link_type": link.link_type.value if hasattr(link.link_type, "value") else link.link_type,
            "created_by": str(link.created_by),
            "created_by_type": link.created_by_type,
        }

    return {
        "outgoing": [_ser(link) for link in links["outgoing"]],
        "incoming": [_ser(link) for link in links["incoming"]],
    }


# ---------------------------------------------------------------------------
# Watchers (Ticketing v2)
# ---------------------------------------------------------------------------

@router.get("/{id_or_key}/watchers", response_model=Page[TicketWatcherRead])
async def list_watchers(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[TicketWatcherRead]:
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.list_watchers(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)
    items = [w.to_dict() for w in rows]
    return Page[TicketWatcherRead](items=items, next_cursor=None, total=len(items))


@router.post(
    "/{id_or_key}/watchers",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketWatcherRead,
)
async def add_watcher(
    id_or_key: str,
    payload: TicketWatcherBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    w = await svc.add_watcher(
        db,
        _resolve_id_or_key(id_or_key),
        watcher_id=payload.watcher_id,
        watcher_type=payload.watcher_type,
        actor=actor,
    )
    _attach_corr(response, corr)
    return w.to_dict()


@router.delete(
    "/{id_or_key}/watchers/{watcher_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_watcher(
    id_or_key: str,
    watcher_id: UUID,
    request: Request,
    response: Response,
    watcher_type: str = Query(default="user"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    await svc.remove_watcher(
        db,
        _resolve_id_or_key(id_or_key),
        watcher_id=watcher_id,
        watcher_type=watcher_type,
    )
    return Response(status_code=204, headers={"X-Correlation-Id": corr})


# ---------------------------------------------------------------------------
# Attachments (Ticketing v2 — metadata-only registration; storage upload
# is out-of-scope for the JSON API and mirrors the existing
# `app/routes/attachments.py` flow for problems if a multipart endpoint is
# needed later).
# ---------------------------------------------------------------------------

@router.get("/{id_or_key}/attachments", response_model=Page[TicketAttachmentRead])
async def list_attachments(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> Page[TicketAttachmentRead]:
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.list_attachments(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)
    items = [a.to_dict() for a in rows]
    return Page[TicketAttachmentRead](items=items, next_cursor=None, total=len(items))


@router.post(
    "/{id_or_key}/attachments",
    status_code=status.HTTP_201_CREATED,
    response_model=TicketAttachmentRead,
)
async def add_attachment(
    id_or_key: str,
    payload: TicketAttachmentBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corr = _correlation_id(request)
    svc = _service()
    a = await svc.add_attachment(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        filename=payload.filename,
        content_type=payload.content_type,
        byte_size=payload.byte_size,
        storage_path=payload.storage_path,
    )
    _attach_corr(response, corr)
    return a.to_dict()


@router.delete(
    "/{id_or_key}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attachment(
    id_or_key: str,
    attachment_id: UUID,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    await svc.delete_attachment(
        db, _resolve_id_or_key(id_or_key), attachment_id
    )
    return Response(status_code=204, headers={"X-Correlation-Id": corr})
