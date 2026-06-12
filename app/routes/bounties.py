"""Bounty-space REST routes (v2.29-S4).

Mounted at ``/api/v1/bounties``. Thin HTTP adapter over
:class:`app.services.bounties.BountyService`; auth via the standard
``get_actor`` dependency (users post/award/withdraw, users AND agents
claim/unclaim).

Error mapping: ``LookupError`` → 404, ``ValueError`` → 409,
``PermissionDeniedError`` → 403 (same conventions as share_posts /
projects routes).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.bearer_auth import get_actor
from app.models.agent_account import AgentAccount
from app.models.bounty import Bounty
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.bounties import BountyCreate, BountyList, BountyOut
from app.services.bounties import BountyService
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError

router = APIRouter(prefix="/v1/bounties", tags=["bounties"])


def _service() -> BountyService:
    return BountyService()


async def _hydrate(db: AsyncSession, rows: list[Bounty]) -> list[BountyOut]:
    """Resolve poster/claimant labels and ticket display ids in batch."""
    user_ids = {b.poster_user_id for b in rows if b.poster_user_id}
    user_ids |= {
        b.claimant_id for b in rows if b.claimant_id and b.claimant_type == "user"
    }
    agent_ids = {
        b.claimant_id for b in rows if b.claimant_id and b.claimant_type == "agent"
    }
    ticket_ids = {b.ticket_id for b in rows if b.ticket_id}

    user_labels: dict[UUID, str] = {}
    if user_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
        for u in users:
            user_labels[u.id] = (
                u.display_name or (u.email or "").split("@", 1)[0] or "user"
            )

    agent_labels: dict[UUID, str] = {}
    if agent_ids:
        agents = (
            await db.execute(
                select(AgentAccount).where(AgentAccount.id.in_(agent_ids))
            )
        ).scalars().all()
        for a in agents:
            agent_labels[a.id] = a.name

    ticket_display: dict[UUID, str] = {}
    if ticket_ids:
        pairs = (
            await db.execute(
                select(Ticket.id, Ticket.display_id).where(
                    Ticket.id.in_(ticket_ids)
                )
            )
        ).all()
        for tid, did in pairs:
            ticket_display[tid] = did

    out: list[BountyOut] = []
    for b in rows:
        claimant_label: str | None = None
        if b.claimant_id is not None:
            if b.claimant_type == "agent":
                claimant_label = agent_labels.get(
                    b.claimant_id, "(unknown agent)"
                )
            else:
                claimant_label = user_labels.get(b.claimant_id, "(unknown)")
        out.append(
            BountyOut(
                id=b.id,
                title=b.title,
                description=b.description,
                points=b.points,
                status=b.status,
                poster_user_id=b.poster_user_id,
                poster_label=(
                    user_labels.get(b.poster_user_id, "(unknown)")
                    if b.poster_user_id
                    else "(unknown)"
                ),
                claimant_id=b.claimant_id,
                claimant_type=b.claimant_type,
                claimant_label=claimant_label,
                ticket_id=b.ticket_id,
                ticket_display_id=(
                    ticket_display.get(b.ticket_id) if b.ticket_id else None
                ),
                problem_id=b.problem_id,
                claimed_at=b.claimed_at,
                awarded_at=b.awarded_at,
                created_at=b.created_at,
                updated_at=b.updated_at,
            )
        )
    return out


@router.get("", response_model=BountyList)
async def list_bounties(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(
        None,
        alias="status",
        pattern="^(open|claimed|awarded|withdrawn)$",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> BountyList:
    svc = _service()
    items, total = await svc.list_bounties(
        db, status=status_filter, limit=limit, offset=offset
    )
    return BountyList(items=await _hydrate(db, items), total=total)


@router.post("", response_model=BountyOut, status_code=status.HTTP_201_CREATED)
async def create_bounty(
    payload: BountyCreate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    svc = _service()
    try:
        row = await svc.create_bounty(
            db,
            actor,
            title=payload.title,
            description=payload.description,
            points=payload.points,
            ticket_id=payload.ticket_id,
            problem_id=payload.problem_id,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return (await _hydrate(db, [row]))[0]


@router.get("/{bounty_id}", response_model=BountyOut)
async def get_bounty(
    bounty_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    svc = _service()
    row = await svc.get_bounty(db, bounty_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bounty not found"
        )
    return (await _hydrate(db, [row]))[0]


async def _transition(
    db: AsyncSession, actor: Actor, bounty_id: UUID, action: str
) -> BountyOut:
    svc = _service()
    method = getattr(svc, action)
    try:
        row = await method(db, actor, bounty_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bounty not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return (await _hydrate(db, [row]))[0]


@router.post("/{bounty_id}/claim", response_model=BountyOut)
async def claim_bounty(
    bounty_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    return await _transition(db, actor, bounty_id, "claim")


@router.post("/{bounty_id}/unclaim", response_model=BountyOut)
async def unclaim_bounty(
    bounty_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    return await _transition(db, actor, bounty_id, "unclaim")


@router.post("/{bounty_id}/award", response_model=BountyOut)
async def award_bounty(
    bounty_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    return await _transition(db, actor, bounty_id, "award")


@router.post("/{bounty_id}/withdraw", response_model=BountyOut)
async def withdraw_bounty(
    bounty_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> BountyOut:
    return await _transition(db, actor, bounty_id, "withdraw")
