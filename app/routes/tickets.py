"""Ticket REST routes (Task A14 / R2).

Thin HTTP adapter over :class:`app.services.tickets.TicketService`. Service-layer
domain exceptions are translated to status codes per the design's error
envelope contract (NFR-904):

    TicketNotFoundError        → 404
    OptimisticConcurrencyError → 409 conflict (current_version, current)
    ForbiddenTransitionError /
    InvalidTransitionError     → 422
    AlreadyClaimedError        → 409 already_claimed
    DuplicateLinkError         → 409 link_exists
    ScopeDeniedError /
    ForbiddenError             → 403
    ValidationError            → 400

Each response carries an ``X-Correlation-Id`` header.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.enums import TicketLinkType, TicketStatus
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
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.services.context import Actor, current_trace_id
from app.services.tickets import TicketService

router = APIRouter(prefix="/v1/tickets", tags=["tickets"])


# ---------------------------------------------------------------------------
# Body schemas specific to the routes (kept here to avoid bloating schemas/)
# ---------------------------------------------------------------------------

class TransitionBody(BaseModel):
    to_status: TicketStatus
    reason: Optional[str] = None


class AssignBody(BaseModel):
    assignee_id: Optional[UUID] = None
    assignee_type: Optional[str] = None
    expected_version: int = Field(..., ge=1)


class CommentBody(BaseModel):
    body: str = Field(..., min_length=1)


class LinkBody(BaseModel):
    target_id: UUID
    link_type: TicketLinkType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id") or current_trace_id() or uuid.uuid4().hex


def _attach_corr(response: Response, corr: str) -> None:
    response.headers["X-Correlation-Id"] = corr


def _ticket_dict(ticket) -> dict[str, Any]:
    return ticket.to_dict()


def _service() -> TicketService:
    return TicketService()


def _resolve_id_or_key(id_or_key: str) -> UUID | str:
    try:
        return UUID(id_or_key)
    except (ValueError, AttributeError):
        return id_or_key


# ---------------------------------------------------------------------------
# Exception handlers — module-level helpers that the app installs in main.py
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

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.create(
        db,
        actor=actor,
        title=payload.title,
        description=payload.description,
        ticket_type=payload.ticket_type,
        priority=payload.priority,
        parent_id=payload.parent_id,
        assignee_id=payload.assignee_id,
        assignee_type=payload.assignee_type,
        labels=payload.labels,
        custom_fields=payload.custom_fields,
        story_points=payload.story_points,
        due_date=payload.due_date,
        correlation_id=corr,
    )
    _attach_corr(response, corr)
    return _ticket_dict(ticket)


@router.get("/search")
async def search_tickets(
    request: Request,
    response: Response,
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.search(db, query=q, limit=limit, offset=offset)
    _attach_corr(response, corr)
    return {"items": [t.to_dict() for t in rows]}


@router.get("/{id_or_key}")
async def get_ticket(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.get(db, _resolve_id_or_key(id_or_key))
    _attach_corr(response, corr)
    return _ticket_dict(ticket)


@router.get("")
async def list_tickets(
    request: Request,
    response: Response,
    status_filter: Optional[list[str]] = Query(default=None, alias="status"),
    assignee_id: Optional[UUID] = Query(default=None),
    parent_id: Optional[UUID] = Query(default=None),
    label: Optional[list[str]] = Query(default=None),
    limit: int = Query(default=50, ge=0, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    rows = await svc.list(
        db,
        status=status_filter,
        assignee_id=assignee_id,
        parent_id=parent_id,
        labels=label,
        limit=limit,
        offset=offset,
    )
    _attach_corr(response, corr)
    return {"items": [t.to_dict() for t in rows]}


@router.patch("/{id_or_key}")
async def update_ticket(
    id_or_key: str,
    payload: TicketUpdate,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
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
    return _ticket_dict(ticket)


@router.post("/{id_or_key}/transition")
async def transition_ticket(
    id_or_key: str,
    payload: TransitionBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
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
    return _ticket_dict(ticket)


@router.post("/{id_or_key}/assign")
async def assign_ticket(
    id_or_key: str,
    payload: AssignBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
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
    return _ticket_dict(ticket)


@router.post("/{id_or_key}/claim")
async def claim_ticket(
    id_or_key: str,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    ticket = await svc.claim(
        db, _resolve_id_or_key(id_or_key), actor=actor, correlation_id=corr
    )
    _attach_corr(response, corr)
    return _ticket_dict(ticket)


@router.post("/{id_or_key}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    id_or_key: str,
    payload: CommentBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    comment = await svc.add_comment(
        db,
        _resolve_id_or_key(id_or_key),
        actor=actor,
        body=payload.body,
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


@router.post("/{id_or_key}/links", status_code=status.HTTP_201_CREATED)
async def link_ticket(
    id_or_key: str,
    payload: LinkBody,
    request: Request,
    response: Response,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    src = await svc.get(db, _resolve_id_or_key(id_or_key))
    link = await svc.link(
        db,
        actor=actor,
        source_id=src.id,
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
        "created_by": str(link.created_by) if link.created_by else None,
        "created_by_type": link.created_by_type,
    }


@router.get("/{id_or_key}/subtree")
async def get_subtree(
    id_or_key: str,
    request: Request,
    response: Response,
    max_depth: int = Query(default=5, ge=1, le=10),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
):
    corr = _correlation_id(request)
    svc = _service()
    root = await svc.get(db, _resolve_id_or_key(id_or_key))
    rows = await svc.get_subtree(db, root.id, max_depth=max_depth)
    _attach_corr(response, corr)
    return {
        "items": [
            {"depth": r["depth"], "ticket": r["ticket"].to_dict()} for r in rows
        ]
    }
