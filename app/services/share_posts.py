"""Share-space service (v2.29-S3).

Operations over ``share_posts`` / ``share_post_votes``:

* :meth:`SharePostService.create_post` — dual-author create (user/agent),
  audited as ``entity_type='share_post', action='create'``.
* :meth:`SharePostService.list_posts` — newest-first, optional tag filter,
  ``(items, total)`` envelope.
* :meth:`SharePostService.get_post` — single row or ``None``.
* :meth:`SharePostService.toggle_vote` — insert-or-delete a vote row and
  update the denormalized ``upvotes`` counter atomically inside the
  caller's transaction (post row locked via ``SELECT ... FOR UPDATE``,
  same idiom as :mod:`app.services.voting`). Audited as ``action='vote'``
  / ``action='unvote'``.

The service NEVER commits — the caller's session/transaction owns the
write, so the audit row and the mutation commit together (NFR-181).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_post import SharePost, SharePostVote
from app.services.audit import AuditService
from app.services.context import Actor


def _actor_type_str(actor: Actor) -> str:
    t = actor.type
    return t.value if hasattr(t, "value") else str(t)


class SharePostService:
    """Service facade for the Share space."""

    def __init__(self, audit: AuditService | None = None) -> None:
        self._audit = audit or AuditService()

    async def create_post(
        self,
        db: AsyncSession,
        actor: Actor,
        *,
        title: str,
        body: str,
        tags: list[str] | tuple[str, ...] = (),
        ticket_id: UUID | None = None,
        agent_run_id: UUID | None = None,
    ) -> SharePost:
        """Insert a post authored by ``actor`` and audit the create."""
        source = _actor_type_str(actor)
        row = SharePost(
            title=title,
            body=body,
            tags=list(tags),
            source=source,
            author_user_id=actor.id if source == "user" else None,
            author_agent_id=actor.id if source == "agent" else None,
            ticket_id=ticket_id,
            agent_run_id=agent_run_id,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)

        await self._audit.record(
            db,
            entity_type="share_post",
            entity_id=row.id,
            action="create",
            actor=actor,
            diff={"after": {"title": title, "tags": list(tags)}},
        )
        return row

    async def list_posts(
        self,
        db: AsyncSession,
        *,
        tag: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SharePost], int]:
        """Return ``(items, total)`` newest-first, optionally tag-filtered."""
        where = []
        if tag:
            # tags @> ARRAY[tag] — rows whose tag array contains `tag`.
            where.append(SharePost.tags.contains([tag]))

        stmt = (
            select(SharePost)
            .where(*where)
            .order_by(SharePost.created_at.desc(), SharePost.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await db.execute(stmt)).scalars().all())

        count_stmt = select(func.count()).select_from(SharePost).where(*where)
        total = int((await db.execute(count_stmt)).scalar_one())
        return items, total

    async def get_post(
        self, db: AsyncSession, post_id: UUID
    ) -> SharePost | None:
        return (
            await db.execute(select(SharePost).where(SharePost.id == post_id))
        ).scalar_one_or_none()

    async def toggle_vote(
        self,
        db: AsyncSession,
        actor: Actor,
        post_id: UUID,
    ) -> tuple[bool, int]:
        """Toggle ``actor``'s vote on ``post_id``.

        Returns ``(voted, upvotes)`` where *voted* indicates whether the
        vote now exists and *upvotes* is the post's denormalized count
        after the toggle. Raises :class:`LookupError` when the post does
        not exist (route maps to 404).
        """
        post = (
            await db.execute(
                select(SharePost)
                .where(SharePost.id == post_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if post is None:
            raise LookupError("share post not found")

        voter_type = _actor_type_str(actor)
        existing = (
            await db.execute(
                select(SharePostVote).where(
                    SharePostVote.post_id == post_id,
                    SharePostVote.voter_id == actor.id,
                    SharePostVote.voter_type == voter_type,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            await db.execute(
                delete(SharePostVote).where(SharePostVote.id == existing.id)
            )
            voted = False
        else:
            db.add(
                SharePostVote(
                    post_id=post_id,
                    voter_id=actor.id,
                    voter_type=voter_type,
                )
            )
            voted = True

        await db.flush()

        count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(SharePostVote)
                    .where(SharePostVote.post_id == post_id)
                )
            ).scalar_one()
        )
        post.upvotes = count
        await db.flush()

        await self._audit.record(
            db,
            entity_type="share_post",
            entity_id=post_id,
            action="vote" if voted else "unvote",
            actor=actor,
            diff={"after": {"voted": voted, "upvotes": count}},
        )
        return voted, count

    async def viewer_voted_post_ids(
        self,
        db: AsyncSession,
        actor: Actor,
        post_ids: list[UUID],
    ) -> set[UUID]:
        """Return the subset of ``post_ids`` the actor has voted on."""
        if not post_ids:
            return set()
        voter_type = _actor_type_str(actor)
        res = await db.execute(
            select(SharePostVote.post_id).where(
                SharePostVote.post_id.in_(post_ids),
                SharePostVote.voter_id == actor.id,
                SharePostVote.voter_type == voter_type,
            )
        )
        return {r[0] for r in res.all()}
