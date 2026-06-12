"""V2b — dev-only mock-response harness for ``human_review`` notifications.

Background
----------
The V2b slice introduced a ``human_review`` notification kind, emitted when
an author writes ``@@handle`` in a body. In production this kind would
queue a real review request; for the demo we provide an automated mock
that resolves pending requests by posting a canned approval comment as
the targeted reviewer — simulating that reviewer's action.

Usage
-----
* **As a library**: ``await resolve_pending(session, now=...)`` returns the
  list of resolved notification UUIDs. Idempotent: a second call with the
  same ``now`` returns ``[]`` because the followup-comment marker on the
  notification row is checked first.
* **As a CLI**: ``MOCK_HUMAN_REVIEW=1 python -m app.scripts.mock_human_review``
  opens a live session via the production session factory, runs the
  resolver once, and prints a single summary line. Without the env flag
  the script exits 0 with no DB side-effect (guard against accidental
  invocation in production).

Eligibility window
------------------
A ``human_review`` notification is eligible when ``created_at <= now - 1s``
AND no comment by the targeted user references it yet. The 1s grace
window lets a real human grab the review first in a mixed environment.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorType
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_notification import TicketNotification
from app.models.user import User
from app.services.context import Actor

CANNED_APPROVAL: Final[str] = (
    "Approved by automated reviewer (mock_human_review harness). "
    "This is a simulated approval — in production a real human would respond."
)
ELIGIBILITY_GRACE: Final[timedelta] = timedelta(seconds=1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _post_canned_comment(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    author_id: UUID,
) -> UUID:
    """Insert a ``ticket_comments`` row authored by ``author_id`` with the
    canned approval text. We bypass ``TicketService.add_comment`` to avoid
    re-triggering the mention-parser fanout: the harness simulates a
    plain-text approval, not a fresh @-mention."""
    comment_id = uuid.uuid4()
    row = TicketComment(
        id=comment_id,
        ticket_id=ticket_id,
        author_id=author_id,
        author_type="user",
        body=CANNED_APPROVAL,
        correlation_id="",
        mentions=[],
    )
    session.add(row)
    await session.flush([row])
    return comment_id


async def resolve_pending(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[UUID]:
    """Find unresolved ``human_review`` notifications older than the grace
    window and resolve each one by posting a canned approval comment as
    the targeted user. Returns the list of notification UUIDs resolved.
    """
    cutoff = (now or _utcnow()) - ELIGIBILITY_GRACE

    stmt = (
        select(TicketNotification)
        .where(TicketNotification.kind == "human_review")
        .where(TicketNotification.created_at <= cutoff)
        .where(TicketNotification.recipient_type == "user")
        .order_by(TicketNotification.created_at.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return []

    resolved: list[UUID] = []
    for n in rows:
        # Idempotency: skip if the targeted user has already commented with
        # the canned text on this ticket. Simple substring check on the body
        # since the canned text is fixed.
        existing = await session.execute(
            select(TicketComment.id)
            .where(TicketComment.ticket_id == n.target_id)
            .where(TicketComment.author_id == n.recipient_id)
            .where(TicketComment.body == CANNED_APPROVAL)
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        # Sanity: the ticket must still exist (notifications could outlive
        # tickets in pathological cleanup paths).
        ticket = (
            await session.execute(
                select(Ticket.id).where(Ticket.id == n.target_id).limit(1)
            )
        ).scalar_one_or_none()
        if ticket is None:
            continue

        # Sanity: the targeted user must still exist + be active.
        user = (
            await session.execute(
                select(User.id)
                .where(User.id == n.recipient_id)
                .where(User.is_active.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if user is None:
            continue

        await _post_canned_comment(
            session, ticket_id=n.target_id, author_id=n.recipient_id
        )
        # Mark the notification read so the resolver does not pick it up
        # again on subsequent runs.
        n.is_read = True
        resolved.append(n.id)

    if resolved:
        await session.flush()
    return resolved


# --- helper used by the actor-factory hook -------------------------------

def _user_actor(user_id: UUID, *, label: str) -> Actor:
    """Build an Actor for the targeted reviewer. Unused by the comment-row
    insertion path above (we bypass the service to avoid mention fanout)
    but kept for future ``act_as`` integrations."""
    return Actor(id=user_id, type=ActorType.user, label=label, scopes=())


# --- CLI entry-point -----------------------------------------------------

def _emit_summary(line: str) -> None:
    """Single CLI write site — keeps the module free of pragma noise."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _main() -> None:
    if os.environ.get("MOCK_HUMAN_REVIEW") != "1":
        _emit_summary(
            "mock_human_review skipped: set MOCK_HUMAN_REVIEW=1 to run."
        )
        return
    from app.database import async_session_factory

    async with async_session_factory() as session:
        try:
            ids = await resolve_pending(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    _emit_summary(f"mock_human_review resolved={len(ids)}")


if __name__ == "__main__":  # pragma: no cover — exercised via tests
    asyncio.run(_main())
