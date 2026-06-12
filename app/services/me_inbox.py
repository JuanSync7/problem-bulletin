"""Me-inbox aggregation service (V3a).

A single ``get_inbox`` entry point fans out four independent queries and
returns the unified ``MeInboxResponse``. Each list is capped at
``DEFAULT_LIMIT`` rows; the UI re-fetches per tab if it ever needs deeper
pagination (out of scope for V3a).

Design notes:
- ``Problem`` has no ``assignee_id`` column (see ``app/models/problem.py``).
  As a deliberate fallback for V3a, "assigned problems" reads as
  ``problems.author_id = me`` (authored). This is recorded in the V3a
  closeout YAML.
- Mention kinds covered: ``ticket_mention``, ``human_review``,
  ``agent_invoked_in_comment`` — the union surfaced by the prior @-mention
  slices (V2a/V2b/V4c).
- ``my_agent_runs`` joins ``agent_run`` to ``agent_accounts.created_by``.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_account import AgentAccount
from app.models.agent_run import AgentRun
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.models.ticket_notification import TicketNotification
from app.schemas.common import Page
from app.schemas.me_inbox import (
    MeAgentRunItem,
    MeAssignedProblemItem,
    MeAssignedTicketItem,
    MeInboxCounts,
    MeInboxResponse,
    MeMentionItem,
)


DEFAULT_LIMIT = 50

MENTION_KINDS: tuple[str, ...] = (
    "ticket_mention",
    "human_review",
    "agent_invoked_in_comment",
)


async def get_inbox(
    session: AsyncSession,
    *,
    user_id: UUID,
    limit: int = DEFAULT_LIMIT,
) -> MeInboxResponse:
    """Aggregate four "My Space" lists + their counts for ``user_id``."""
    # --- assigned tickets ----------------------------------------------------
    tickets_q = (
        select(Ticket)
        .where(Ticket.assignee_id == user_id, Ticket.assignee_type == "user")
        .order_by(
            Ticket.last_activity_at.desc().nulls_last(),
            Ticket.created_at.desc(),
        )
        .limit(limit)
    )
    tickets_res = await session.execute(tickets_q)
    ticket_rows = list(tickets_res.scalars().all())
    tickets_count_res = await session.execute(
        select(func.count())
        .select_from(Ticket)
        .where(Ticket.assignee_id == user_id, Ticket.assignee_type == "user")
    )
    tickets_count = int(tickets_count_res.scalar_one() or 0)

    ticket_items = [
        MeAssignedTicketItem(
            id=t.id,
            display_id=t.display_id,
            title=t.title,
            status=t.status.value if hasattr(t.status, "value") else str(t.status),
            priority=(
                t.priority.value if hasattr(t.priority, "value") else str(t.priority)
            ),
            project_id=t.project_id,
            last_activity_at=t.last_activity_at,
            created_at=t.created_at,
        )
        for t in ticket_rows
    ]

    # --- assigned problems (fallback: authored by me) ------------------------
    problems_q = (
        select(Problem)
        .where(Problem.author_id == user_id)
        .order_by(
            Problem.activity_at.desc().nulls_last(),
            Problem.created_at.desc(),
        )
        .limit(limit)
    )
    problems_res = await session.execute(problems_q)
    problem_rows = list(problems_res.scalars().all())
    problems_count_res = await session.execute(
        select(func.count())
        .select_from(Problem)
        .where(Problem.author_id == user_id)
    )
    problems_count = int(problems_count_res.scalar_one() or 0)

    problem_items = [
        MeAssignedProblemItem(
            id=p.id,
            title=p.title,
            status=p.status,
            created_at=p.created_at,
            activity_at=p.activity_at,
        )
        for p in problem_rows
    ]

    # --- mentions ------------------------------------------------------------
    mentions_q = (
        select(TicketNotification)
        .where(
            TicketNotification.recipient_type == "user",
            TicketNotification.recipient_id == user_id,
            TicketNotification.kind.in_(MENTION_KINDS),
        )
        .order_by(TicketNotification.created_at.desc())
        .limit(limit)
    )
    mentions_res = await session.execute(mentions_q)
    mention_rows = list(mentions_res.scalars().all())
    mentions_count_res = await session.execute(
        select(func.count())
        .select_from(TicketNotification)
        .where(
            TicketNotification.recipient_type == "user",
            TicketNotification.recipient_id == user_id,
            TicketNotification.kind.in_(MENTION_KINDS),
        )
    )
    mentions_count = int(mentions_count_res.scalar_one() or 0)

    mention_items = [
        MeMentionItem(
            id=m.id,
            kind=m.kind,
            target_type="ticket",
            target_id=m.target_id,
            target_display_id=m.target_display_id,
            excerpt=m.excerpt,
            is_read=m.is_read,
            created_at=m.created_at,
        )
        for m in mention_rows
    ]

    # --- my agent runs -------------------------------------------------------
    owned_agents_subq = (
        select(AgentAccount.id).where(AgentAccount.created_by == user_id)
    ).subquery()

    runs_q = (
        select(AgentRun)
        .where(AgentRun.agent_id.in_(select(owned_agents_subq.c.id)))
        .order_by(AgentRun.enqueued_at.desc())
        .limit(limit)
    )
    runs_res = await session.execute(runs_q)
    run_rows = list(runs_res.scalars().all())
    runs_count_res = await session.execute(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.agent_id.in_(select(owned_agents_subq.c.id)))
    )
    runs_count = int(runs_count_res.scalar_one() or 0)

    def _summary(body: str | None) -> str | None:
        if not body:
            return None
        for line in body.splitlines():
            s = line.strip()
            if s:
                return s[:160]
        return None

    def _prompt_preview(p: str | None) -> str | None:
        if not p:
            return None
        s = p.strip().splitlines()[0] if p.strip() else ""
        return s[:80] if s else None

    run_items = [
        MeAgentRunItem(
            id=r.id,
            agent_id=r.agent_id,
            ticket_id=r.ticket_id,
            status=r.status,
            enqueued_at=r.enqueued_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
            summary=_summary(r.response_body),
            prompt_preview=_prompt_preview(r.prompt),
            error=(r.error or "")[:200] if r.error else None,
        )
        for r in run_rows
    ]

    return MeInboxResponse(
        assigned_tickets=Page[MeAssignedTicketItem](
            items=ticket_items, next_cursor=None, total=tickets_count
        ),
        assigned_problems=Page[MeAssignedProblemItem](
            items=problem_items, next_cursor=None, total=problems_count
        ),
        mentions=Page[MeMentionItem](
            items=mention_items, next_cursor=None, total=mentions_count
        ),
        my_agent_runs=Page[MeAgentRunItem](
            items=run_items, next_cursor=None, total=runs_count
        ),
        counts=MeInboxCounts(
            assigned_tickets=tickets_count,
            assigned_problems=problems_count,
            mentions=mentions_count,
            my_agent_runs=runs_count,
        ),
    )
