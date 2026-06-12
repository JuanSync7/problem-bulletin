"""Slice V7a — Orchestrator-as-user demo driver.

Runs the seeded Problem-Bulletin demo end-to-end against a single
session: ensures the seed exists, enqueues any missing ``agent_run``
rows for tickets that are assigned to agents, then drains the in-process
queue.  Every successful run produces a ticket comment + notifications +
project_lesson by way of the V4b / V4c / V6b side-effect chain wired
inside :meth:`AgentRunQueue.process_one`.

Runnable via ``python -m app.scripts.orchestrate_demo``.  Supports
``--dry-run`` to enumerate the work WITHOUT mutating durable rows.

Idempotency is composed:
* ``seed_demo.seed`` is naturally-keyed (no duplicate rows on replay).
* ``AgentRunQueue.enqueue`` collapses on the deterministic
  ``idempotency_key``.
* Lesson + notification side-effects rely on the V4b / V6b unique
  indexes.

So a second invocation against the same DB processes zero new runs and
leaves comment / lesson / notification counts unchanged.
"""
from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_account import AgentAccount
from app.models.agent_run import AgentRun
from app.models.project import ProjectMember
from app.models.ticket import Ticket
from app.scripts import seed_demo
from app.services.agent_run_queue import get_default_queue


class PlannedEnqueue(BaseModel):
    """One ticket the orchestrator would enqueue an ``agent_run`` for."""

    ticket_id: UUID
    agent_id: UUID
    display_id: str | None = None


class OrchestrateReport(BaseModel):
    """Outcome of a single :func:`orchestrate` invocation.

    ``planned``           — number of agent_runs the orchestrator
                            considered drainable when it started
                            (existing pending rows + planned enqueues).
    ``planned_enqueues``  — agent-assigned tickets without an existing
                            ``agent_run`` row that the orchestrator
                            would enqueue.  Populated in both dry-run
                            and live modes (live mode also performs the
                            enqueue).
    ``runs_processed``    — number of ``queue.process_one`` calls that
                            claimed a row.  0 in dry-run.
    ``comments_posted``   — count of agent ticket_comments inserted by
                            this invocation (delta).
    ``lessons_emitted``   — count of project_lesson rows inserted by
                            this invocation (delta).
    ``summary_lines``     — one structured log line per processed run.
    """

    planned: int = 0
    planned_enqueues: list[PlannedEnqueue] = Field(default_factory=list)
    runs_processed: int = 0
    comments_posted: int = 0
    lessons_emitted: int = 0
    summary_lines: list[str] = Field(default_factory=list)


async def _count_agent_comments(session: AsyncSession, project_id: UUID) -> int:
    """Count ticket_comments with author_type='agent' on a project."""
    from sqlalchemy import text

    row = await session.execute(
        text(
            "SELECT count(*) FROM ticket_comments "
            "WHERE author_type = 'agent' AND ticket_id IN "
            "(SELECT id FROM tickets WHERE project_id = :p)"
        ),
        {"p": project_id},
    )
    return int(row.scalar_one())


async def _count_agent_lessons(session: AsyncSession, project_id: UUID) -> int:
    """Count project_lesson rows with source='agent' on a project."""
    from sqlalchemy import text

    row = await session.execute(
        text(
            "SELECT count(*) FROM project_lesson "
            "WHERE project_id = :p AND source = 'agent'"
        ),
        {"p": project_id},
    )
    return int(row.scalar_one())


async def _plan_agent_assignee_enqueues(
    session: AsyncSession, *, project_id: UUID
) -> list[PlannedEnqueue]:
    """Find PB tickets assigned to an agent that have no existing run.

    The seed_demo does not currently assign tickets to agents, so this
    walk is usually empty — but the contract is to fill in any agent
    assignee that LACKS a queued/done run, so the orchestrator behaves
    sensibly if a developer hand-assigns tickets to an agent in the dev
    DB between runs.
    """
    rows = (
        await session.execute(
            select(Ticket.id, Ticket.assignee_id, Ticket.display_id)
            .where(
                Ticket.project_id == project_id,
                Ticket.assignee_type == "agent",
                Ticket.assignee_id.is_not(None),
            )
        )
    ).all()
    out: list[PlannedEnqueue] = []
    for ticket_id, assignee_id, display_id in rows:
        if assignee_id is None:
            continue
        existing = (
            await session.execute(
                select(AgentRun.id).where(
                    AgentRun.ticket_id == ticket_id,
                    AgentRun.agent_id == assignee_id,
                )
            )
        ).first()
        if existing is not None:
            continue
        out.append(
            PlannedEnqueue(
                ticket_id=ticket_id,
                agent_id=assignee_id,
                display_id=display_id,
            )
        )
    return out


async def _plan_seed_driven_enqueues(
    session: AsyncSession, *, project_id: UUID
) -> list[PlannedEnqueue]:
    """Plan one ``agent_run`` per (agent project-member, first task ticket).

    The seeded PB project owns three agent members and four task
    tickets.  To produce a meaningful demo without requiring a separate
    assignee migration, the orchestrator drives each agent against the
    first task ticket (ordered by ``seq_number``) — that single ticket
    becomes the demo's collaboration anchor.  The queue's
    ``idempotency_key`` ensures replays insert no new rows.
    """
    # First task ticket in seq_number order — anchors the demo.
    first_task = (
        await session.execute(
            select(Ticket.id, Ticket.display_id)
            .where(Ticket.project_id == project_id)
            .order_by(Ticket.seq_number.asc())
            .limit(1)
        )
    ).first()
    if first_task is None:
        return []
    ticket_id, display_id = first_task

    # Agent members of the project.
    agent_ids_rows = (
        await session.execute(
            select(AgentAccount.id)
            .join(
                ProjectMember,
                (ProjectMember.member_id == AgentAccount.id)
                & (ProjectMember.member_type == "agent"),
            )
            .where(ProjectMember.project_id == project_id)
        )
    ).all()
    out: list[PlannedEnqueue] = []
    for (agent_id,) in agent_ids_rows:
        existing = (
            await session.execute(
                select(AgentRun.id).where(
                    AgentRun.ticket_id == ticket_id,
                    AgentRun.agent_id == agent_id,
                )
            )
        ).first()
        if existing is not None:
            continue
        out.append(
            PlannedEnqueue(
                ticket_id=ticket_id,
                agent_id=agent_id,
                display_id=display_id,
            )
        )
    return out


async def _count_pending(session: AsyncSession, *, project_id: UUID) -> int:
    """Count ``agent_run`` rows with status='pending' scoped to PB."""
    row = await session.execute(
        select(AgentRun.id)
        .join(Ticket, Ticket.id == AgentRun.ticket_id)
        .where(
            Ticket.project_id == project_id,
            AgentRun.status == "pending",
        )
    )
    return len(row.all())


async def orchestrate(
    session: AsyncSession, *, dry_run: bool = False
) -> OrchestrateReport:
    """Play the user: seed → enqueue → drain.

    See module docstring for the idempotency / dry-run contract.
    """
    report = OrchestrateReport()

    # Step 1 — ensure the demo cast exists.  ``seed_demo.seed`` is
    # idempotent (natural-keyed), so re-calling on a populated DB is a
    # no-op.  In dry-run we still call it: the seed is a precondition
    # for any plan and re-seeding produces zero new rows.
    seed_report = await seed_demo.seed(session)
    project_id = seed_report.project_id
    await session.flush()

    # Pre-run counters (for the live-mode delta).
    comments_before = await _count_agent_comments(session, project_id)
    lessons_before = await _count_agent_lessons(session, project_id)

    # Step 2 — planning.  Two sources contribute to the work list:
    #   * Tickets in PB whose assignee_type='agent' but lack an
    #     ``agent_run`` (covers hand-assigned dev-DB tickets).
    #   * The seeded baseline: each agent project-member runs against
    #     the first task ticket once.  This is what materialises the
    #     demo when seed_demo runs against an empty DB.
    # In dry-run we record but do not enqueue; in live mode we enqueue
    # immediately so the drain below picks the rows up.
    planned_enqueues = await _plan_agent_assignee_enqueues(
        session, project_id=project_id
    )
    planned_enqueues.extend(
        await _plan_seed_driven_enqueues(session, project_id=project_id)
    )
    report.planned_enqueues = planned_enqueues

    queue = get_default_queue(session)
    if not dry_run:
        for p in planned_enqueues:
            await queue.enqueue(
                session,
                agent_id=p.agent_id,
                ticket_id=p.ticket_id,
                comment_id=None,
                prompt=(
                    f"orchestrate_demo: drive {p.display_id or p.ticket_id}"
                ),
            )
        await session.flush()

    # Step 3 — drain (or count, in dry-run).  We compute planned AFTER
    # any live-mode enqueues so the field reflects "what we are about
    # to process" in both modes.
    pending_now = await _count_pending(session, project_id=project_id)
    report.planned = pending_now + (len(planned_enqueues) if dry_run else 0)

    if dry_run:
        return report

    # Live drain — cap at a generous bound so a regression that
    # accidentally re-enqueues mid-loop can't spin forever.
    DRAIN_CAP = 200
    for _ in range(DRAIN_CAP):
        run_id = await queue.process_one(session)
        if run_id is None:
            break
        report.runs_processed += 1
        # Pull the row back for the summary line.  ``process_one``
        # leaves the row attached to the session, so a fresh select is
        # cheap and gives us the final status / comment_id.
        run = (
            await session.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
        ).scalar_one()
        report.summary_lines.append(
            f"[run {run.id}] agent={run.agent_id} ticket={run.ticket_id} "
            f"status={run.status} comment={run.comment_id}"
        )

    # Live-mode deltas.
    comments_after = await _count_agent_comments(session, project_id)
    lessons_after = await _count_agent_lessons(session, project_id)
    report.comments_posted = comments_after - comments_before
    report.lessons_emitted = lessons_after - lessons_before

    return report


def _emit_cli_summary(line: str) -> None:
    """Write a one-line CLI summary to stdout.

    Mirrors :func:`app.scripts.seed_demo._emit_cli_summary` — wrapping
    the lone ``sys.stdout.write`` call keeps the module free of
    structural-lint pragma noise.
    """
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _main() -> None:  # pragma: no cover — CLI entry-point
    """Open a session via the production factory and run :func:`orchestrate`."""
    from app.database import async_session_factory

    dry_run = "--dry-run" in sys.argv[1:]
    async with async_session_factory() as session:
        try:
            report = await orchestrate(session, dry_run=dry_run)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    _emit_cli_summary(
        "orchestrate_demo OK: "
        f"dry_run={dry_run} planned={report.planned} "
        f"processed={report.runs_processed} "
        f"comments_posted={report.comments_posted} "
        f"lessons_emitted={report.lessons_emitted}"
    )
    for line in report.summary_lines:
        _emit_cli_summary(line)


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    asyncio.run(_main())
