"""Share-space REST routes (v2.29-S3).

Mounted at ``/api/v1/share-posts``. Thin HTTP adapter over
:class:`app.services.share_posts.SharePostService`; auth via the standard
``get_actor`` dependency (users AND agents can post / vote).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.bearer_auth import get_actor
from app.models.agent_account import AgentAccount
from app.models.share_post import SharePost
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.share_posts import (
    SharePostCreate,
    SharePostList,
    SharePostOut,
    SharePostVoteOut,
)
from app.services.context import Actor
from app.services.share_posts import SharePostService

router = APIRouter(prefix="/v1/share-posts", tags=["share-posts"])


def _service() -> SharePostService:
    return SharePostService()


async def _hydrate(
    db: AsyncSession,
    actor: Actor,
    posts: list[SharePost],
    svc: SharePostService,
) -> list[SharePostOut]:
    """Resolve author labels, ticket display ids, and viewer votes in batch."""
    user_ids = {p.author_user_id for p in posts if p.author_user_id}
    agent_ids = {p.author_agent_id for p in posts if p.author_agent_id}
    ticket_ids = {p.ticket_id for p in posts if p.ticket_id}

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

    voted = await svc.viewer_voted_post_ids(db, actor, [p.id for p in posts])

    out: list[SharePostOut] = []
    for p in posts:
        if p.source == "agent" and p.author_agent_id is not None:
            label = agent_labels.get(p.author_agent_id, "(unknown agent)")
        elif p.author_user_id is not None:
            label = user_labels.get(p.author_user_id, "(unknown)")
        else:
            label = "(unknown)"
        out.append(
            SharePostOut(
                id=p.id,
                title=p.title,
                body=p.body,
                tags=list(p.tags or []),
                author_kind="agent" if p.source == "agent" else "user",
                author_label=label,
                ticket_id=p.ticket_id,
                ticket_display_id=(
                    ticket_display.get(p.ticket_id) if p.ticket_id else None
                ),
                agent_run_id=p.agent_run_id,
                upvotes=p.upvotes,
                viewer_has_voted=p.id in voted,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
        )
    return out


@router.get("", response_model=SharePostList)
async def list_share_posts(
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
    tag: str | None = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SharePostList:
    svc = _service()
    items, total = await svc.list_posts(db, tag=tag, limit=limit, offset=offset)
    return SharePostList(
        items=await _hydrate(db, actor, items, svc),
        total=total,
    )


@router.post(
    "", response_model=SharePostOut, status_code=status.HTTP_201_CREATED
)
async def create_share_post(
    payload: SharePostCreate,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SharePostOut:
    svc = _service()
    post = await svc.create_post(
        db,
        actor,
        title=payload.title,
        body=payload.body,
        tags=payload.tags,
        ticket_id=payload.ticket_id,
        agent_run_id=payload.agent_run_id,
    )
    return (await _hydrate(db, actor, [post], svc))[0]


@router.get("/{post_id}", response_model=SharePostOut)
async def get_share_post(
    post_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SharePostOut:
    svc = _service()
    post = await svc.get_post(db, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="share post not found",
        )
    return (await _hydrate(db, actor, [post], svc))[0]


@router.put("/{post_id}/vote", response_model=SharePostVoteOut)
async def toggle_share_post_vote(
    post_id: UUID,
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db),
) -> SharePostVoteOut:
    svc = _service()
    try:
        voted, upvotes = await svc.toggle_vote(db, actor, post_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="share post not found",
        ) from exc
    return SharePostVoteOut(voted=voted, upvotes=upvotes)
