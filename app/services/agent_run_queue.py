"""V4a: AgentRunQueue — in-process sequential worker.

A thin shim over the ``agent_run`` table that exposes:

* ``enqueue(...) -> run_id``     — insert (or recover) a pending row.
* ``process_one(session) -> run_id | None`` — claim the oldest pending
  row under ``SELECT ... FOR UPDATE SKIP LOCKED``, invoke the provider,
  and persist the result.

**Sequential invariant**: at most one ``process_one`` body runs at a
time.  This is enforced both at the Python level (``asyncio.Lock``) and
at the SQL level (``FOR UPDATE SKIP LOCKED``) — belt and braces — so
that even multi-process callers don't double-dispatch.

This slice does NOT post the resulting ``comment_body`` to
``ticket_comments`` or fire notifications.  Both land in V4b.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_account import AgentAccount
from app.models.agent_run import AgentRun
from app.models.ticket_comment import TicketComment
from app.models.ticket_notification import TicketNotification
from app.services import project_lessons
from app.services.agent_provider import AgentProvider

_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _format_structured_comment(
    *,
    handle: str,
    display_id: str,
    summary: str,
    details: str,
    locations: list[str],
) -> str:
    """v2.29 S5 — render the structured agent-completion markdown.

    Shape::

        @{handle} finished on {display_id}

        **Summary**: <one-line result>

        **Details**: <prose>

        **Locations**:
        - <pointer>
    """
    parts = [
        f"@{handle} finished on {display_id}",
        "",
        f"**Summary**: {summary}",
        "",
        f"**Details**: {details}",
    ]
    if locations:
        parts.append("")
        parts.append("**Locations**:")
        parts.extend(f"- {loc}" for loc in locations)
    return "\n".join(parts)


def _make_idempotency_key(
    *, agent_id: UUID, ticket_id: UUID, prompt: str
) -> str:
    """Deterministic 32-char hex digest of (agent_id, ticket_id, prompt)."""
    raw = f"{agent_id}:{ticket_id}:{prompt}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


class AgentRunQueue:
    """In-process FIFO worker fronting the ``agent_run`` table."""

    def __init__(self, *, provider: AgentProvider) -> None:
        self._provider = provider
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        agent_id: UUID,
        ticket_id: UUID,
        comment_id: UUID | None,
        prompt: str,
    ) -> UUID:
        """Insert a pending ``agent_run`` row (or recover an existing one).

        Returns the row id.  If a row with the same idempotency_key
        already exists, no new row is inserted; the existing id is
        returned instead.
        """
        idem = _make_idempotency_key(
            agent_id=agent_id, ticket_id=ticket_id, prompt=prompt,
        )
        existing = (
            await session.execute(
                select(AgentRun).where(AgentRun.idempotency_key == idem)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id

        row = AgentRun(
            agent_id=agent_id,
            ticket_id=ticket_id,
            comment_id=comment_id,
            status="pending",
            prompt=prompt,
            idempotency_key=idem,
        )
        session.add(row)
        await session.flush()
        return row.id

    async def process_one(self, session: AsyncSession) -> UUID | None:
        """Claim and process the oldest pending row, if any.

        Returns the processed row id, or ``None`` when the queue is
        empty.  On provider failure the row is marked ``error`` and the
        method returns its id (caller can decide to retry by re-enqueueing
        with a fresh prompt).
        """
        async with self._lock:
            stmt = (
                select(AgentRun)
                .where(AgentRun.status == "pending")
                .order_by(AgentRun.enqueued_at.asc(), AgentRun.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None

            row.status = "running"
            row.started_at = _now()
            await session.flush()

            try:
                result = await self._provider.run(
                    agent_id=row.agent_id,
                    ticket_id=row.ticket_id,
                    comment_id=row.comment_id,
                    prompt=row.prompt,
                )
            except Exception as exc:  # provider must not poison the worker
                _log.exception(
                    "agent_run_queue: provider raised for run %s", row.id,
                )
                row.status = "error"
                row.error = str(exc)
                row.finished_at = _now()
                await session.flush()
                return row.id

            if result.status == "ok":
                row.status = "done"
                row.response_body = result.comment_body
                # V4b: persist the agent's response as a ticket_comment +
                # fan a notification out to the agent's owner.  Best-effort
                # — failures here are logged but do not poison the queue
                # entry (which has already been marked ``done``).
                #
                # V4c (additive): when the run originated from a comment
                # whose author is NOT the agent's owner, emit a second
                # ``agent_invoked_in_comment`` notification so the owner
                # learns their agent was pulled into someone else's
                # thread.  Same-user invocation (owner @-mentions their
                # own agent) skips this row — the V4b ``agent_responded``
                # already covers it.
                originating_comment_id = row.comment_id
                try:
                    # v2.29 S5 — structured completion comment.  When the
                    # provider supplies ``summary`` (and optionally
                    # ``locations``) the posted comment is formatted as
                    # structured markdown.  ``response_body`` (set above)
                    # keeps storing the RAW provider body either way.
                    # ``getattr`` keeps backward compat with provider
                    # implementations returning older result shapes.
                    body_to_post = result.comment_body
                    _summary = getattr(result, "summary", None)
                    _locations = list(getattr(result, "locations", None) or [])
                    if _summary:
                        from app.models.ticket import Ticket as _TicketFmt
                        _handle: str | None = (
                            await session.execute(
                                select(AgentAccount.handle).where(
                                    AgentAccount.id == row.agent_id
                                )
                            )
                        ).scalar_one_or_none()
                        _display_id: str | None = (
                            await session.execute(
                                select(_TicketFmt.display_id).where(
                                    _TicketFmt.id == row.ticket_id
                                )
                            )
                        ).scalar_one_or_none()
                        if _handle and _display_id:
                            body_to_post = _format_structured_comment(
                                handle=_handle,
                                display_id=_display_id,
                                summary=_summary,
                                details=result.comment_body,
                                locations=_locations,
                            )

                    comment = TicketComment(
                        ticket_id=row.ticket_id,
                        author_id=row.agent_id,
                        author_type="agent",
                        body=body_to_post,
                    )
                    session.add(comment)
                    await session.flush([comment])
                    # Link the new comment back onto the agent_run row so
                    # the UI can deep-link to it.  ``originating_comment_id``
                    # (captured above) preserves the V4c trigger for the
                    # cross-user notification block below.
                    row.comment_id = comment.id

                    owner_id: UUID | None = (
                        await session.execute(
                            select(AgentAccount.created_by).where(
                                AgentAccount.id == row.agent_id
                            )
                        )
                    ).scalar_one_or_none()
                    if owner_id is not None:
                        # Look up the ticket's display_id for the inbox row.
                        from app.models.ticket import Ticket as _Ticket  # local
                        display_id: str | None = (
                            await session.execute(
                                select(_Ticket.display_id).where(
                                    _Ticket.id == row.ticket_id
                                )
                            )
                        ).scalar_one_or_none()

                        await session.execute(
                            pg_insert(TicketNotification).values(
                                kind="agent_responded",
                                recipient_type="user",
                                recipient_id=owner_id,
                                actor_type="agent",
                                actor_id=row.agent_id,
                                target_type="ticket",
                                target_id=row.ticket_id,
                                target_display_id=display_id,
                                comment_id=comment.id,
                                excerpt=None,
                            )
                        )

                        # V4c — cross-user invocation path.  Look up the
                        # originating comment's author; if it's not the
                        # owner, emit the ``agent_invoked_in_comment``
                        # row.  ``comment_id`` on the notification row
                        # points at the ORIGINATING comment (so the UI
                        # can deep-link to the trigger).  The response
                        # comment id is encoded in ``excerpt`` since the
                        # table has no metadata column.
                        if originating_comment_id is not None:
                            originating_author_id: UUID | None = (
                                await session.execute(
                                    select(TicketComment.author_id).where(
                                        TicketComment.id
                                        == originating_comment_id
                                    )
                                )
                            ).scalar_one_or_none()
                            if (
                                originating_author_id is not None
                                and originating_author_id != owner_id
                            ):
                                await session.execute(
                                    pg_insert(TicketNotification).values(
                                        kind="agent_invoked_in_comment",
                                        recipient_type="user",
                                        recipient_id=owner_id,
                                        actor_type="user",
                                        actor_id=originating_author_id,
                                        target_type="ticket",
                                        target_id=row.ticket_id,
                                        target_display_id=display_id,
                                        comment_id=originating_comment_id,
                                        excerpt=(
                                            f"response_comment_id:{comment.id}"
                                        ),
                                    )
                                )

                    # V6b — auto-emit lessons.  Each entry in
                    # ``result.lessons_emitted`` becomes one
                    # ``project_lesson`` row scoped to the ticket's
                    # project, with ``source='agent'`` and the agent
                    # carried via ``author_agent_id``.  The partial
                    # UNIQUE on ``(agent_run_id, lesson_index)`` plus
                    # ``ON CONFLICT DO NOTHING`` makes defensive replay
                    # safe.  Body convention: split on the first newline
                    # so callers may pack ``"title\nbody"``.
                    if result.lessons_emitted:
                        from app.models.ticket import Ticket as _Ticket2
                        project_id: UUID | None = (
                            await session.execute(
                                select(_Ticket2.project_id).where(
                                    _Ticket2.id == row.ticket_id
                                )
                            )
                        ).scalar_one_or_none()
                        if project_id is not None:
                            for idx, lesson in enumerate(
                                result.lessons_emitted
                            ):
                                if "\n" in lesson:
                                    title, body_text = lesson.split(
                                        "\n", 1
                                    )
                                else:
                                    title, body_text = lesson, ""
                                await project_lessons.record_agent_lesson(
                                    session,
                                    project_id=project_id,
                                    agent_id=row.agent_id,
                                    agent_run_id=row.id,
                                    lesson_index=idx,
                                    title=title,
                                    body=body_text,
                                )
                except Exception as exc:
                    _log.exception(
                        "agent_run_queue: side-effects after provider OK "
                        "failed for run %s",
                        row.id,
                    )
                    row.error = (
                        f"side-effects failed: {exc!s}"
                        if row.error is None
                        else row.error
                    )
            else:
                row.status = "error"
                row.error = result.error or "provider returned status=error"
            row.finished_at = _now()
            await session.flush()
            return row.id


def get_default_queue(session: AsyncSession) -> AgentRunQueue:
    """Return an :class:`AgentRunQueue` bound to the supplied session.

    V4b uses this from the ticket-assignment path and from the
    ``POST /agent-runs/process-next`` route.  The provider is a
    :class:`MockAgentProvider`; V8a replaces it with a real backend
    selected per project.

    The queue keeps an ``asyncio.Lock`` for in-process sequentiality.
    SQL-level ``SELECT ... FOR UPDATE SKIP LOCKED`` guarantees the
    invariant across processes, so building a fresh queue per request
    (rather than memoising) is safe and avoids leaking sessions between
    requests.
    """
    from app.services.agent_provider import MockAgentProvider  # local import
    return AgentRunQueue(provider=MockAgentProvider(session=session))
