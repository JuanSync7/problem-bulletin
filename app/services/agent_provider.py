"""V4a: AgentProvider seam + MockAgentProvider.

Defines the abstract contract every agent backend must implement, plus a
deterministic mock used for tests and local development.  The real
headless-Claude backend lands in V8a; this slice only wires the interface
and the mock so the queue (``app.services.agent_run_queue``) can be
exercised end to end.

Contract:
- ``AgentProvider.run(*, agent_id, ticket_id, comment_id, prompt) ->
  AgentRunResult`` is an awaitable.  The provider is responsible for
  producing a ``comment_body`` string the queue can later post as a
  ticket_comment (V4b) but must not itself perform any DB writes that
  outlive the call — durability is the queue's concern.

Mock rules (deterministic, keyed off ticket title keywords):
- "bug"      → "Found root cause: ..."
- "feature"  → "Drafted implementation plan: ..."
- "test"     → "Wrote unit tests covering ..."
- otherwise  → "Investigated and summarised ..."

Every response embeds both the ticket ``display_id`` and the agent
``handle`` so downstream tests can assert reference integrity.
"""
from __future__ import annotations

import re as _re
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_account import AgentAccount
from app.models.ticket import Ticket


class AgentRunResult(BaseModel):
    """Outcome of one provider invocation.

    ``next_status_hint`` is advisory: V4b uses it to optionally propose a
    workflow transition (e.g. ``in_progress`` → ``in_review``).  The queue
    persists ``comment_body`` to ``agent_run.response_body``.
    """

    status: Literal["ok", "error"]
    comment_body: str
    next_status_hint: str | None = None
    error: str | None = None
    lessons_emitted: list[str] = Field(default_factory=list)
    # v2.29 S5 — optional structured-completion fields.  When ``summary``
    # is present the queue formats the posted comment as structured
    # markdown (header / Summary / Details / Locations).  When absent the
    # flat ``comment_body`` is posted verbatim (backward compat).
    summary: str | None = None
    locations: list[str] = Field(default_factory=list)


class AgentProvider(Protocol):
    """Abstract agent backend.  Implementations may be async."""

    async def run(
        self,
        *,
        agent_id: UUID,
        ticket_id: UUID,
        comment_id: UUID | None,
        prompt: str,
    ) -> AgentRunResult:
        ...


def _classify(title: str) -> tuple[str, str]:
    """Return ``(prefix, hint)`` for the deterministic rule table."""
    lowered = title.lower()
    if "bug" in lowered:
        return ("Found root cause", "in_review")
    if "feature" in lowered:
        return ("Drafted implementation plan", "in_progress")
    if "test" in lowered:
        return ("Wrote unit tests covering", "in_review")
    return ("Investigated and summarised", None or "in_progress")


class MockAgentProvider:
    """Deterministic, DB-aware mock provider.

    Looks up the ticket + agent rows so the response can quote both the
    ticket key (``display_id``) and the agent handle.  Implementations
    MUST be re-entrant; the queue serialises calls but tests may invoke
    ``run`` directly without holding the queue lock.
    """

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def run(
        self,
        *,
        agent_id: UUID,
        ticket_id: UUID,
        comment_id: UUID | None,
        prompt: str,
    ) -> AgentRunResult:
        # Resolve agent handle + ticket key.  Missing rows surface as
        # ``error`` rather than raise — the queue records error and moves
        # on instead of poisoning the worker.
        agent = (
            await self._session.execute(
                select(AgentAccount).where(AgentAccount.id == agent_id)
            )
        ).scalar_one_or_none()
        ticket = (
            await self._session.execute(
                select(Ticket).where(Ticket.id == ticket_id)
            )
        ).scalar_one_or_none()
        if agent is None or ticket is None:
            return AgentRunResult(
                status="error",
                comment_body="",
                error=f"agent={agent_id!s} or ticket={ticket_id!s} not found",
            )

        prefix, hint = _classify(ticket.title)
        body = (
            f"@{agent.handle} on {ticket.display_id}: {prefix} — "
            f"(mock response to prompt {prompt!r})."
        )
        # V6b — emit one deterministic lesson per run.  Title quotes the
        # ticket + agent so a downstream Lessons tab is human-readable;
        # body carries the same prefix-classified hint.  Title and body
        # are joined by a single newline so callers can split on the
        # first \n to recover the pair.
        lesson_title = (
            f"Lesson from {agent.handle} on {ticket.display_id}: {prefix}"
        )
        lesson_body = (
            f"Mock agent {agent.handle} concluded: {prefix.lower()} "
            f"for ticket {ticket.display_id}."
        )
        lesson = f"{lesson_title}\n{lesson_body}"
        # v2.29 S5 — deterministic structured-completion fields.  The
        # summary is a one-liner derived from the rule-table prefix; the
        # locations are fake file pointers keyed off the first prompt
        # keyword (same prompt ⇒ same locations, no randomness).
        keywords = _re.findall(r"[a-z0-9_]+", prompt.lower())
        kw = next((w for w in keywords if len(w) >= 4), keywords[0] if keywords else "task")
        summary = f"{prefix} for {ticket.display_id}"
        locations = [
            f"app/services/{kw}.py — {prefix.lower()} (mock)",
            f"tests/test_{kw}.py — coverage for {ticket.display_id} (mock)",
        ]
        return AgentRunResult(
            status="ok",
            comment_body=body,
            next_status_hint=hint,
            lessons_emitted=[lesson],
            summary=summary,
            locations=locations,
        )
