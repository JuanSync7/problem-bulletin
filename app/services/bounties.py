"""Bounty-space service (v2.29-S4).

Operations over ``bounties``:

* :meth:`BountyService.create_bounty` — user-only create (agents may
  claim but not post; raises :class:`PermissionDeniedError` otherwise),
  audited as ``entity_type='bounty', action='create'``.
* :meth:`BountyService.list_bounties` — newest-first, optional status
  filter, ``(items, total)`` envelope.
* :meth:`BountyService.get_bounty` — single row or ``None``.
* Transitions — :meth:`claim`, :meth:`unclaim`, :meth:`award`,
  :meth:`withdraw`. Each takes a ``SELECT ... FOR UPDATE`` row lock
  (same idiom as :meth:`app.services.share_posts.SharePostService.toggle_vote`)
  and raises :class:`LookupError` when the row is missing (route → 404),
  :class:`ValueError` on an illegal state (route → 409), or
  :class:`PermissionDeniedError` when the actor lacks the role
  (route → 403). Every transition is audited.

The service NEVER commits — the caller's session/transaction owns the
write, so the audit row and the mutation commit together (NFR-181).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bounty import Bounty
from app.services.audit import AuditService
from app.services.context import Actor
from app.services.exceptions import PermissionDeniedError


def _actor_type_str(actor: Actor) -> str:
    t = actor.type
    return t.value if hasattr(t, "value") else str(t)


class BountyService:
    """Service facade for the Bounty space."""

    def __init__(self, audit: AuditService | None = None) -> None:
        self._audit = audit or AuditService()

    # ------------------------------------------------------------------
    # create / read
    # ------------------------------------------------------------------

    async def create_bounty(
        self,
        db: AsyncSession,
        actor: Actor,
        *,
        title: str,
        description: str = "",
        points: int,
        ticket_id: UUID | None = None,
        problem_id: UUID | None = None,
    ) -> Bounty:
        """Insert a bounty posted by ``actor`` (users only) and audit it."""
        if _actor_type_str(actor) != "user":
            raise PermissionDeniedError("only users can post bounties")

        row = Bounty(
            title=title,
            description=description,
            points=points,
            status="open",
            poster_user_id=actor.id,
            ticket_id=ticket_id,
            problem_id=problem_id,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)

        await self._audit.record(
            db,
            entity_type="bounty",
            entity_id=row.id,
            action="create",
            actor=actor,
            diff={"after": {"title": title, "points": points}},
        )
        return row

    async def list_bounties(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Bounty], int]:
        """Return ``(items, total)`` newest-first, optionally by status."""
        where = []
        if status:
            where.append(Bounty.status == status)

        stmt = (
            select(Bounty)
            .where(*where)
            .order_by(Bounty.created_at.desc(), Bounty.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await db.execute(stmt)).scalars().all())

        count_stmt = select(func.count()).select_from(Bounty).where(*where)
        total = int((await db.execute(count_stmt)).scalar_one())
        return items, total

    async def get_bounty(
        self, db: AsyncSession, bounty_id: UUID
    ) -> Bounty | None:
        return (
            await db.execute(select(Bounty).where(Bounty.id == bounty_id))
        ).scalar_one_or_none()

    # ------------------------------------------------------------------
    # transitions
    # ------------------------------------------------------------------

    async def _locked(self, db: AsyncSession, bounty_id: UUID) -> Bounty:
        """Fetch the bounty FOR UPDATE or raise :class:`LookupError`."""
        row = (
            await db.execute(
                select(Bounty)
                .where(Bounty.id == bounty_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("bounty not found")
        return row

    async def _record(
        self, db: AsyncSession, actor: Actor, row: Bounty, action: str
    ) -> None:
        await self._audit.record(
            db,
            entity_type="bounty",
            entity_id=row.id,
            action=action,
            actor=actor,
            diff={"after": {"status": row.status}},
        )

    async def claim(
        self, db: AsyncSession, actor: Actor, bounty_id: UUID
    ) -> Bounty:
        """Claim an open bounty as ``actor`` (user OR agent)."""
        row = await self._locked(db, bounty_id)
        if row.status != "open":
            raise ValueError("not open")
        row.claimant_id = actor.id
        row.claimant_type = _actor_type_str(actor)
        row.claimed_at = datetime.now(timezone.utc)
        row.status = "claimed"
        await db.flush()
        # Materialize the server-side onupdate (updated_at) so the route
        # can serialize the row without an illegal async lazy-load.
        await db.refresh(row)
        await self._record(db, actor, row, "claim")
        return row

    async def unclaim(
        self, db: AsyncSession, actor: Actor, bounty_id: UUID
    ) -> Bounty:
        """Release a claimed bounty back to open (claimant only)."""
        row = await self._locked(db, bounty_id)
        if row.status != "claimed":
            raise ValueError("not claimed")
        if (
            row.claimant_id != actor.id
            or row.claimant_type != _actor_type_str(actor)
        ):
            raise PermissionDeniedError("only the claimant can unclaim")
        row.claimant_id = None
        row.claimant_type = None
        row.claimed_at = None
        row.status = "open"
        await db.flush()
        await db.refresh(row)
        await self._record(db, actor, row, "unclaim")
        return row

    async def award(
        self, db: AsyncSession, actor: Actor, bounty_id: UUID
    ) -> Bounty:
        """Award a claimed bounty (poster only)."""
        row = await self._locked(db, bounty_id)
        if (
            _actor_type_str(actor) != "user"
            or row.poster_user_id != actor.id
        ):
            raise PermissionDeniedError("only the poster can award")
        if row.status != "claimed":
            raise ValueError("not claimed")
        row.awarded_at = datetime.now(timezone.utc)
        row.status = "awarded"
        await db.flush()
        await db.refresh(row)
        await self._record(db, actor, row, "award")
        return row

    async def withdraw(
        self, db: AsyncSession, actor: Actor, bounty_id: UUID
    ) -> Bounty:
        """Withdraw an open bounty (poster only)."""
        row = await self._locked(db, bounty_id)
        if (
            _actor_type_str(actor) != "user"
            or row.poster_user_id != actor.id
        ):
            raise PermissionDeniedError("only the poster can withdraw")
        if row.status != "open":
            raise ValueError("not open")
        row.status = "withdrawn"
        await db.flush()
        await db.refresh(row)
        await self._record(db, actor, row, "withdraw")
        return row
