"""TicketService — agent-kanban ticket business logic (Tasks S2-S7).

All write paths funnel through this service. Every method:

* takes an ``AsyncSession`` and uses it directly (never opens or commits its
  own transaction);
* writes an ``audit_log`` row in the same transaction via :class:`AuditService`;
* raises domain exceptions from :mod:`app.exceptions` (never ``HTTPException``).

OCC: every mutation bumps ``tickets.version``. Stale writes raise
:class:`OptimisticConcurrencyError`. Status changes go through
:meth:`transition`, which takes a row-level ``SELECT ... FOR UPDATE`` to
serialize concurrent transitions.

Comments (S6) live in the new ``ticket_comments`` table created by migration
``a5_agent_kanban``. The legacy ``comments`` table on the tickets foreign-keyed
row is left untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import (
    String,
    and_,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    TERMINAL_STATUSES,
    ActorType,
    TicketLinkType,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from app.events import stage_event
from app.exceptions import (
    AlreadyClaimedError,
    DuplicateLinkError,
    ForbiddenError,
    InvalidTransitionError,
    OptimisticConcurrencyError,
    TicketNotFoundError,
    ValidationError,
)
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink
from app.models.ticket_transition import TicketTransition
from app.observability.tracing import traced
from app.services.audit import AuditService
from app.services.context import Actor

# Allowed forward transitions. Cancellation is reachable from any non-terminal
# state (escape hatch). Re-opens (done -> in_progress) are NOT allowed — closed
# tickets stay closed; create a new ticket if work resumes.
_ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.todo: frozenset(
        {TicketStatus.in_progress, TicketStatus.blocked, TicketStatus.cancelled}
    ),
    TicketStatus.in_progress: frozenset(
        {
            TicketStatus.in_review,
            TicketStatus.blocked,
            TicketStatus.todo,
            TicketStatus.cancelled,
        }
    ),
    TicketStatus.in_review: frozenset(
        {
            TicketStatus.in_progress,
            TicketStatus.done,
            TicketStatus.blocked,
            TicketStatus.cancelled,
        }
    ),
    TicketStatus.blocked: frozenset(
        {
            TicketStatus.todo,
            TicketStatus.in_progress,
            TicketStatus.cancelled,
        }
    ),
    TicketStatus.done: frozenset(),  # terminal
    TicketStatus.cancelled: frozenset(),  # terminal
}


def _actor_type_str(actor: Actor) -> str:
    return actor.type.value if hasattr(actor.type, "value") else str(actor.type)


class TicketService:
    """Canonical ticket service. Stateless; safe to share across requests."""

    def __init__(self, audit: AuditService | None = None) -> None:
        self._audit = audit or AuditService()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _is_uuid(value: Any) -> bool:
        if isinstance(value, UUID):
            return True
        if not isinstance(value, str):
            return False
        try:
            UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    async def _load(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        for_update: bool = False,
    ) -> Ticket:
        """Resolve UUID or ``TKT-N`` key to a :class:`Ticket` row.

        ``for_update`` issues a ``SELECT ... FOR UPDATE`` to serialize
        concurrent mutations against the same row.
        """
        stmt = select(Ticket).where(Ticket.deleted_at.is_(None))
        if isinstance(ticket_id_or_key, UUID):
            stmt = stmt.where(Ticket.id == ticket_id_or_key)
        elif self._is_uuid(ticket_id_or_key):
            stmt = stmt.where(Ticket.id == UUID(str(ticket_id_or_key)))
        else:
            stmt = stmt.where(Ticket.key == str(ticket_id_or_key))
        if for_update:
            stmt = stmt.with_for_update()
        result = await session.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise TicketNotFoundError(ticket_id_or_key)
        return ticket

    # -- S2: create / get / list -------------------------------------------

    @traced(action="create")
    async def create(
        self,
        session: AsyncSession,
        *,
        actor: Actor,
        title: str,
        description: str | None = None,
        ticket_type: TicketType = TicketType.task,
        priority: TicketPriority = TicketPriority.medium,
        parent_id: UUID | None = None,
        assignee_id: UUID | None = None,
        assignee_type: str | None = None,
        labels: Sequence[str] | None = None,
        custom_fields: dict[str, Any] | None = None,
        story_points: int | None = None,
        due_date=None,
        correlation_id: str = "",
    ) -> Ticket:
        """Insert a new ticket with ``version=1`` plus an audit row.

        Allocates ``seq_number`` from the ``tickets_seq_number_seq`` sequence
        (added by migration ``a5_agent_kanban``) and derives ``key`` as
        ``TKT-<N>``. Both happen inside the caller's transaction.
        """
        if not title or not title.strip():
            raise ValidationError([{"name": "title", "reason": "required"}])
        if (assignee_id is None) != (assignee_type is None):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be paired with assignee_id"}]
            )
        if assignee_type is not None and assignee_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be 'user' or 'agent'"}]
            )

        # Allocate seq atomically via the Postgres sequence.
        seq_result = await session.execute(
            text("SELECT nextval('tickets_seq_number_seq')")
        )
        seq_number = int(seq_result.scalar_one())
        key = f"TKT-{seq_number}"

        ticket = Ticket(
            title=title,
            description=description,
            ticket_type=ticket_type,
            status=TicketStatus.todo,
            priority=priority,
            reporter_id=actor.id,
            reporter_type=_actor_type_str(actor),
            assignee_id=assignee_id,
            assignee_type=assignee_type,
            parent_id=parent_id,
            labels=list(labels or []),
            custom_fields=dict(custom_fields or {}),
            story_points=story_points,
            due_date=due_date,
            version=1,
            seq_number=seq_number,
            key=key,
        )
        session.add(ticket)
        try:
            await session.flush([ticket])
        except IntegrityError as exc:
            raise ValidationError(
                [{"name": "parent_id", "reason": "constraint violated"}]
            ) from exc

        # Initial transition row (NULL -> todo) for full status history.
        session.add(
            TicketTransition(
                ticket_id=ticket.id,
                from_status=None,
                to_status=TicketStatus.todo,
                actor_id=actor.id,
                actor_type=_actor_type_str(actor),
                reason=None,
                correlation_id=correlation_id or "",
            )
        )

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="create",
            actor=actor,
            diff={"before": None, "after": ticket.to_dict()},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.created",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket": ticket.to_dict(),
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "ticket_key": ticket.key,
            },
        )
        return ticket

    async def get(
        self, session: AsyncSession, ticket_id_or_key: UUID | str
    ) -> Ticket:
        """Resolve UUID or ``TKT-N`` key to a ticket; raise if missing."""
        return await self._load(session, ticket_id_or_key)

    async def list(
        self,
        session: AsyncSession,
        *,
        status: Sequence[TicketStatus | str] | None = None,
        assignee_id: UUID | None = None,
        parent_id: UUID | None = None,
        labels: Sequence[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        """Filter tickets by status / assignee / parent / labels (intersection).

        Returns the rows ordered by ``updated_at`` desc, falling back to
        ``created_at`` for never-updated rows. Soft-deleted rows excluded.
        """
        if limit < 0 or offset < 0:
            raise ValidationError(
                [{"name": "limit", "reason": "must be non-negative"}]
            )
        limit = min(limit, 200)

        stmt = select(Ticket).where(Ticket.deleted_at.is_(None))
        if status:
            normalised = [
                s if isinstance(s, TicketStatus) else TicketStatus(s) for s in status
            ]
            stmt = stmt.where(Ticket.status.in_(normalised))
        if assignee_id is not None:
            stmt = stmt.where(Ticket.assignee_id == assignee_id)
        if parent_id is not None:
            stmt = stmt.where(Ticket.parent_id == parent_id)
        if labels:
            # labels filter is "contains all" (AND across requested labels).
            stmt = stmt.where(Ticket.labels.contains(list(labels)))

        stmt = (
            stmt.order_by(
                func.coalesce(Ticket.updated_at, Ticket.created_at).desc()
            )
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # -- S3: OCC update -----------------------------------------------------

    @traced(action="update")
    async def update(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        actor: Actor,
        expected_version: int,
        patch: dict[str, Any],
        correlation_id: str = "",
    ) -> Ticket:
        """OCC update. Bumps ``version`` on success.

        ``patch`` is a dict of mutable fields. Unknown / forbidden keys raise
        :class:`ValidationError`. Status changes are NOT permitted here — use
        :meth:`transition`.
        """
        mutable = {
            "title",
            "description",
            "priority",
            "parent_id",
            "labels",
            "custom_fields",
            "story_points",
            "due_date",
        }
        unknown = set(patch) - mutable
        if unknown:
            raise ValidationError(
                [{"name": k, "reason": "not updatable via update()"} for k in unknown]
            )

        ticket = await self._load(session, ticket_id_or_key, for_update=True)
        if ticket.version != expected_version:
            raise OptimisticConcurrencyError(
                current_version=ticket.version, current=ticket.to_dict()
            )

        before = ticket.to_dict()

        # Apply patch.
        for k, v in patch.items():
            if k == "priority" and v is not None and not isinstance(v, TicketPriority):
                v = TicketPriority(v)
            setattr(ticket, k, v)
        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        await session.flush([ticket])

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="update",
            actor=actor,
            diff={"before": before, "after": ticket.to_dict()},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.updated",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_key": ticket.key,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "patch": {k: str(v) for k, v in patch.items()},
                "version": ticket.version,
            },
        )
        return ticket

    # -- S4: transition (status machine + row lock) ------------------------

    @traced(action="transition")
    async def transition(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        actor: Actor,
        target_status: TicketStatus | str,
        reason: str | None = None,
        correlation_id: str = "",
    ) -> Ticket:
        """Atomic state-machine transition with row lock.

        Steps:
            1. ``SELECT ... FOR UPDATE`` on the ticket row.
            2. Validate the transition against the allow-table.
            3. Insert ``ticket_transitions`` row.
            4. Update ``status``, ``version``, ``closed_at`` (if terminal).
            5. Insert audit row.

        Concurrent callers serialize on step 1; the second caller observes the
        new status and either succeeds (if the new transition is still legal)
        or raises :class:`InvalidTransitionError`.
        """
        target = (
            target_status
            if isinstance(target_status, TicketStatus)
            else TicketStatus(target_status)
        )

        ticket = await self._load(session, ticket_id_or_key, for_update=True)
        current = ticket.status

        if current == target:
            raise InvalidTransitionError(current.value, target.value)
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransitionError(current.value, target.value)

        before = ticket.to_dict()

        session.add(
            TicketTransition(
                ticket_id=ticket.id,
                from_status=current,
                to_status=target,
                actor_id=actor.id,
                actor_type=_actor_type_str(actor),
                reason=reason,
                correlation_id=correlation_id or "",
            )
        )

        ticket.status = target
        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        if target in TERMINAL_STATUSES:
            ticket.closed_at = datetime.now(timezone.utc)
        await session.flush([ticket])

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="transition",
            actor=actor,
            diff={
                "before": before,
                "after": ticket.to_dict(),
                "from_status": current.value,
                "to_status": target.value,
                "reason": reason,
            },
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.transitioned",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_key": ticket.key,
                "from_status": current.value,
                "to_status": target.value,
                "reason": reason,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "version": ticket.version,
            },
        )
        return ticket

    # -- S5: assign + claim ------------------------------------------------

    @traced(action="assign")
    async def assign(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        actor: Actor,
        assignee_id: UUID | None,
        assignee_type: str | None,
        expected_version: int,
        correlation_id: str = "",
    ) -> Ticket:
        """OCC-protected assignment. Pass ``(None, None)`` to unassign."""
        if (assignee_id is None) != (assignee_type is None):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be paired with assignee_id"}]
            )
        if assignee_type is not None and assignee_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be 'user' or 'agent'"}]
            )

        ticket = await self._load(session, ticket_id_or_key, for_update=True)
        if ticket.version != expected_version:
            raise OptimisticConcurrencyError(
                current_version=ticket.version, current=ticket.to_dict()
            )

        before = ticket.to_dict()
        ticket.assignee_id = assignee_id
        ticket.assignee_type = assignee_type
        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        await session.flush([ticket])

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="assign",
            actor=actor,
            diff={"before": before, "after": ticket.to_dict()},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.assigned",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_key": ticket.key,
                "assignee_id": str(assignee_id) if assignee_id else None,
                "assignee_type": assignee_type,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "version": ticket.version,
            },
        )
        return ticket

    @traced(action="claim")
    async def claim(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        actor: Actor,
        correlation_id: str = "",
    ) -> Ticket:
        """Atomic unassigned-only claim.

        Executes a conditional ``UPDATE ... WHERE assignee_id IS NULL``. If no
        row is updated, the ticket is already claimed (or missing); we read
        back the current state to decide which exception to raise.

        Designed for high-concurrency contention: N parallel agents calling
        :meth:`claim` will see exactly one winner.
        """
        if actor.type != ActorType.agent and str(getattr(actor, "type", "")) != "agent":
            raise ForbiddenError("only agents can claim tickets")

        # Resolve key->id first if we got a string key.
        if isinstance(ticket_id_or_key, UUID):
            target_id = ticket_id_or_key
        elif self._is_uuid(ticket_id_or_key):
            target_id = UUID(str(ticket_id_or_key))
        else:
            lookup = await session.execute(
                select(Ticket.id, Ticket.assignee_id).where(
                    Ticket.key == str(ticket_id_or_key),
                    Ticket.deleted_at.is_(None),
                )
            )
            row = lookup.first()
            if row is None:
                raise TicketNotFoundError(ticket_id_or_key)
            target_id = row[0]

        stmt = (
            update(Ticket)
            .where(
                Ticket.id == target_id,
                Ticket.assignee_id.is_(None),
                Ticket.deleted_at.is_(None),
            )
            .values(
                assignee_id=actor.id,
                assignee_type="agent",
                version=Ticket.version + 1,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Ticket.id)
        )
        result = await session.execute(stmt)
        updated_id = result.scalar_one_or_none()

        if updated_id is None:
            # Either missing or already claimed — disambiguate.
            existing = await session.execute(
                select(Ticket.assignee_id).where(
                    Ticket.id == target_id, Ticket.deleted_at.is_(None)
                )
            )
            existing_row = existing.first()
            if existing_row is None:
                raise TicketNotFoundError(ticket_id_or_key)
            raise AlreadyClaimedError(current_assignee_id=existing_row[0])

        # Reload fresh row for the audit diff + return.
        await session.commit if False else None  # no-op; keep on caller's TX
        ticket = await self._load(session, target_id)

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="claim",
            actor=actor,
            diff={"after": ticket.to_dict()},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.claimed",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_key": ticket.key,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "version": ticket.version,
            },
        )
        return ticket

    # -- S6: add_comment + link --------------------------------------------

    @traced(action="add_comment")
    async def add_comment(
        self,
        session: AsyncSession,
        ticket_id_or_key: UUID | str,
        *,
        actor: Actor,
        body: str,
        correlation_id: str = "",
    ) -> TicketComment:
        """Append a comment. Validates non-empty body and ticket existence."""
        if not body or not body.strip():
            raise ValidationError([{"name": "body", "reason": "required"}])

        ticket = await self._load(session, ticket_id_or_key)

        comment = TicketComment(
            ticket_id=ticket.id,
            author_id=actor.id,
            author_type=_actor_type_str(actor),
            body=body,
            correlation_id=correlation_id or "",
        )
        session.add(comment)
        await session.flush([comment])

        await self._audit.record(
            session,
            entity_type="ticket_comment",
            entity_id=comment.id,
            action="comment",
            actor=actor,
            diff={"after": {"ticket_id": str(ticket.id), "body": body}},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.commented",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_key": ticket.key,
                "comment_id": str(comment.id),
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
                "body": body,
            },
        )
        return comment

    async def link(
        self,
        session: AsyncSession,
        *,
        actor: Actor,
        source_id: UUID,
        target_id: UUID,
        link_type: TicketLinkType | str,
        correlation_id: str = "",
    ) -> TicketLink:
        """Create a directional link. Rejects self-link + duplicates."""
        if source_id == target_id:
            raise ValidationError(
                [{"name": "target_id", "reason": "cannot link a ticket to itself"}]
            )
        lt = (
            link_type
            if isinstance(link_type, TicketLinkType)
            else TicketLinkType(link_type)
        )

        # Ensure both rows exist (and are not soft-deleted).
        await self._load(session, source_id)
        await self._load(session, target_id)

        row = TicketLink(
            source_id=source_id,
            target_id=target_id,
            link_type=lt,
            created_by=actor.id,
            created_by_type=_actor_type_str(actor),
        )
        session.add(row)
        try:
            await session.flush([row])
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateLinkError(
                f"link {source_id}->{target_id} ({lt.value}) already exists"
            ) from exc

        await self._audit.record(
            session,
            entity_type="ticket_link",
            entity_id=row.id,
            action="link",
            actor=actor,
            diff={
                "after": {
                    "source_id": str(source_id),
                    "target_id": str(target_id),
                    "link_type": lt.value,
                }
            },
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.linked",
            ticket_id=source_id,
            correlation_id=correlation_id,
            payload={
                "source_id": str(source_id),
                "target_id": str(target_id),
                "link_type": lt.value,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )
        return row

    # -- S7: get_subtree + search ------------------------------------------

    async def get_subtree(
        self,
        session: AsyncSession,
        root_id: UUID,
        *,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """Return root + descendants via recursive CTE, ordered DFS.

        Output rows are ``{"ticket": Ticket, "depth": int}`` dicts. Depth 0 is
        the root. Soft-deleted rows are excluded from both anchor and
        recursion. ``max_depth`` caps how deep we walk.
        """
        # Confirm the root exists (gives us a clean TicketNotFoundError).
        await self._load(session, root_id)

        cte_sql = text(
            """
            WITH RECURSIVE subtree(id, depth) AS (
                SELECT t.id, 0 AS depth
                  FROM tickets t
                 WHERE t.id = :root_id AND t.deleted_at IS NULL
                UNION ALL
                SELECT c.id, s.depth + 1
                  FROM tickets c
                  JOIN subtree s ON c.parent_id = s.id
                 WHERE c.deleted_at IS NULL
                   AND s.depth + 1 <= :max_depth
            )
            SELECT id, depth FROM subtree ORDER BY depth, id
            """
        )
        result = await session.execute(
            cte_sql, {"root_id": root_id, "max_depth": max_depth}
        )
        rows = result.all()
        if not rows:
            return []

        ids = [r[0] for r in rows]
        depth_by_id = {r[0]: r[1] for r in rows}

        ticket_rows = await session.execute(
            select(Ticket).where(Ticket.id.in_(ids))
        )
        by_id = {t.id: t for t in ticket_rows.scalars().all()}
        return [
            {"ticket": by_id[i], "depth": depth_by_id[i]}
            for i in ids
            if i in by_id
        ]

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str | None = None,
        labels: Sequence[str] | None = None,
        status: Sequence[TicketStatus | str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        """Full-text search on ``search_tsv`` with optional label/status filters.

        When ``query`` is empty/None we delegate the filter+sort path to
        :meth:`list`. Otherwise we rank by ``ts_rank_cd`` against the
        ``plainto_tsquery`` parse of ``query``.
        """
        if not query:
            return await self.list(
                session, status=status, labels=labels, limit=limit, offset=offset
            )

        ts_query = func.plainto_tsquery("english", query)
        stmt = (
            select(Ticket)
            .where(Ticket.deleted_at.is_(None))
            .where(Ticket.search_tsv.op("@@")(ts_query))
        )
        if labels:
            stmt = stmt.where(Ticket.labels.contains(list(labels)))
        if status:
            normalised = [
                s if isinstance(s, TicketStatus) else TicketStatus(s) for s in status
            ]
            stmt = stmt.where(Ticket.status.in_(normalised))

        rank = func.ts_rank_cd(Ticket.search_tsv, ts_query)
        stmt = stmt.order_by(rank.desc()).limit(min(limit, 200)).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())
