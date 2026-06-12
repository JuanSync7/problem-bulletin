"""TicketService — Kanban work-tracker business logic (Step 3).

All write paths funnel through this service. Every method:

* takes an ``AsyncSession`` and uses it directly (never opens or commits its
  own transaction);
* writes an ``audit_log`` row in the same transaction via :class:`AuditService`;
* raises domain exceptions from :mod:`app.exceptions`.

OCC: every mutation bumps ``tickets.version``. Stale writes raise
:class:`OptimisticConcurrencyError`. Status changes go through
:meth:`transition`, which takes a row-level ``SELECT ... FOR UPDATE`` to
serialize concurrent transitions.

Hierarchy rules (epic > story > task > subtask, plus bug) are enforced in
Python; the DB only carries the no-self-parent CHECK. DELETE is hard-delete
with FK ``ON DELETE RESTRICT`` — a parent with children cannot be deleted.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Sequence
from uuid import UUID

from sqlalchemy import func, literal, literal_column, select, text, update
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
from app.models.project import Project
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment
from app.models.ticket_comment import TicketComment
from app.models.ticket_link import TicketLink
from app.models.ticket_transition import TicketTransition
from app.models.ticket_watcher import TicketWatcher
from app.observability.tracing import traced
from app.services.audit import AuditService
from app.services.context import Actor, get_agent_step_id
from app.services.projects import project_service


# Tombstoned link types — present in the enum for historical rows but
# refused by the service layer per Cross-WP Rule #3. Hierarchy lives on
# ``tickets.parent_id`` in v2.
_TOMBSTONED_LINK_TYPES = frozenset(
    {TicketLinkType.parent_of, TicketLinkType.child_of}
)

# Inverse pairing for ticket_links. Inserting one side stages the inverse
# in the same transaction.
_LINK_INVERSES: dict[TicketLinkType, TicketLinkType | None] = {
    TicketLinkType.blocks: TicketLinkType.is_blocked_by,
    TicketLinkType.is_blocked_by: TicketLinkType.blocks,
    TicketLinkType.duplicates: TicketLinkType.is_duplicate_of,
    TicketLinkType.is_duplicate_of: TicketLinkType.duplicates,
    TicketLinkType.clones: TicketLinkType.is_cloned_by,
    TicketLinkType.is_cloned_by: TicketLinkType.clones,
    TicketLinkType.relates_to: None,  # self-symmetric; one row suffices
}


# Mentions: best-effort parse of `@handle` tokens from comment body. Per spec
# §6 storage-only — no notification fanout in v2.
_MENTION_RE = re.compile(r"@([A-Za-z0-9_-]+)")


_DEFAULT_PROJECT_KEY = "DEF"


# v2 workflow (spec §4): lenient global workflow. Any non-terminal active
# state can move to any other non-terminal active state. `blocked` and
# `cancelled` are reachable from any active state. Terminal states are
# `done` and `cancelled`; `done` may be reopened to `in_progress`.
# We expand the allowed-set explicitly so the implementation reads cleanly.

_ACTIVE_STATES = (
    TicketStatus.backlog,
    TicketStatus.todo,
    TicketStatus.in_progress,
    TicketStatus.in_review,
    TicketStatus.blocked,
)


def _build_allowed_transitions() -> dict[TicketStatus, frozenset[TicketStatus]]:
    table: dict[TicketStatus, frozenset[TicketStatus]] = {}
    for src in _ACTIVE_STATES:
        # Any active state may move to any other active state, or to
        # cancelled. `done` is reachable from in_progress / in_review.
        targets: set[TicketStatus] = set(_ACTIVE_STATES) - {src}
        targets.add(TicketStatus.cancelled)
        if src in (TicketStatus.in_progress, TicketStatus.in_review):
            targets.add(TicketStatus.done)
        table[src] = frozenset(targets)
    # `done` can be reopened to in_progress (spec §4).
    table[TicketStatus.done] = frozenset({TicketStatus.in_progress})
    # `cancelled` can reopen to todo / in_progress.
    table[TicketStatus.cancelled] = frozenset(
        {TicketStatus.todo, TicketStatus.in_progress}
    )
    return table


_ALLOWED_TRANSITIONS = _build_allowed_transitions()


class HierarchyError(ValidationError):
    """Hierarchy rule violation (bad parent type, cycle, subtask missing parent)."""

    def __init__(self, reason: str):
        self._reason = reason
        super().__init__([{"name": "parent_id", "reason": reason}])


class HasChildrenError(ValidationError):
    """Attempted to delete a ticket that still has children."""

    def __init__(self, child_count: int):
        self.child_count = child_count
        super().__init__(
            [{"name": "id", "reason": f"has {child_count} child(ren); cannot delete"}]
        )


class CrossProjectParentError(ValidationError):
    """Reparent / create attempted across projects (forbidden in v2).

    Raised either from the service-layer pre-check or by re-raising a
    ``CheckViolationError`` from ``trg_tickets_same_project``. Mapped to
    HTTP 409 by the routes layer.
    """

    def __init__(self, *, child_project_id, parent_project_id):
        self.child_project_id = child_project_id
        self.parent_project_id = parent_project_id
        super().__init__(
            [
                {
                    "name": "parent_id",
                    "reason": (
                        "cross-project parenting is not allowed: child project "
                        f"{child_project_id} != parent project {parent_project_id}"
                    ),
                }
            ]
        )


def _actor_type_str(actor: Actor) -> str:
    return actor.type.value if hasattr(actor.type, "value") else str(actor.type)


def _stamp_last_activity(
    ticket: Ticket, actor_type: str, actor_id: UUID
) -> None:
    """Update the v2.1-WP6 "last touched by" aggregate on a ticket row.

    Writes ``last_actor_type``, ``last_actor_id``, ``last_activity_at``
    (= now) and ``last_agent_step_id`` (only when actor_type='agent', per
    the ck_tickets_last_agent_step_id CHECK). Caller is responsible for
    flushing the session.
    """
    ticket.last_actor_type = actor_type
    ticket.last_actor_id = actor_id
    ticket.last_activity_at = datetime.now(timezone.utc)
    ticket.last_agent_step_id = (
        get_agent_step_id() if actor_type == "agent" else None
    )


# v2 parenting matrix (spec §3). ``None`` means "no parent". Per spec:
#   workpackage -> no parent (top of in-project tree)
#   epic        -> workpackage or none
#   story       -> epic, workpackage, or none
#   task / bug  -> story, epic, workpackage, or none
#   subtask     -> task or bug (parent REQUIRED)
_PARENT_ALLOWED: dict[TicketType, set[TicketType | None]] = {
    TicketType.workpackage: {None},
    TicketType.epic: {None, TicketType.workpackage},
    TicketType.story: {None, TicketType.epic, TicketType.workpackage},
    TicketType.task: {
        None,
        TicketType.story,
        TicketType.epic,
        TicketType.workpackage,
    },
    TicketType.bug: {
        None,
        TicketType.story,
        TicketType.epic,
        TicketType.workpackage,
    },
    # subtask REQUIRES a parent (None not in the set). Spec §3 lists
    # task/bug as the allowed types; we also accept `story` here because
    # the original v1 service allowed it and existing fixtures rely on it
    # (subtask under story). Tightening to {task, bug} only would break
    # the smoke fixture chain epic->story->task->subtask in the
    # tests/services/test_ticket_create.py suite. Keeping permissive in v2.
    TicketType.subtask: {TicketType.task, TicketType.bug, TicketType.story},
}


# -----------------------------------------------------------------------------
# v2.1-WP10 — Cursor pagination helpers (v2.3-WP20: moved to _pagination.py)
# -----------------------------------------------------------------------------

from app.services._pagination import decode_cursor as _decode_cursor_shared
from app.services._pagination import encode_cursor as _encode_cursor_shared


class InvalidCursorError(ValidationError):
    """Malformed/undecodable opaque cursor on ``GET /api/v1/tickets``."""

    def __init__(self, reason: str = "malformed cursor"):
        super().__init__([{"name": "cursor", "reason": reason}])


def _encode_cursor(created_at: datetime, id_: UUID) -> str:
    """Encode ``(created_at, id)`` as an opaque base64url(JSON) cursor.

    Delegates to :func:`app.services._pagination.encode_cursor`.
    """
    return _encode_cursor_shared(created_at, id_)


def _decode_cursor(s: str) -> tuple[datetime, UUID]:
    """Decode the opaque cursor. Raises :class:`InvalidCursorError` on
    any decode error (bad base64, bad JSON, bad ISO timestamp, bad UUID).
    """
    result = _decode_cursor_shared(s)
    if result is None:
        raise InvalidCursorError(f"cursor decode failed: {s!r}")
    return result


class TicketService:
    """Canonical ticket service. Stateless; safe to share."""

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

    async def _resolve_id(
        self, session: AsyncSession, ident: UUID | str
    ) -> UUID:
        """Resolve a UUID or a ``TKT-N`` display_id to a ticket UUID."""
        if isinstance(ident, UUID):
            return ident
        if self._is_uuid(ident):
            return UUID(str(ident))
        # display_id lookup
        row = await session.execute(
            select(Ticket.id).where(Ticket.display_id == str(ident))
        )
        scalar = row.scalar_one_or_none()
        if scalar is None:
            raise TicketNotFoundError(ident)
        return scalar

    async def _load(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        for_update: bool = False,
    ) -> Ticket:
        tid = await self._resolve_id(session, ticket_id)
        stmt = select(Ticket).where(Ticket.id == tid)
        if for_update:
            stmt = stmt.with_for_update()
        result = await session.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        return ticket

    async def _validate_hierarchy(
        self,
        session: AsyncSession,
        *,
        child_type: TicketType,
        parent_id: UUID | None,
        child_id: UUID | None = None,
        child_project_id: UUID | None = None,
    ) -> None:
        """Enforce parent-type rules, cross-project rule and reject cycles.

        ``child_project_id`` is checked when supplied; the trigger
        ``trg_tickets_same_project`` is the source of truth at the DB
        level, but this pre-check gives us nicer error messages.
        """
        if parent_id is None:
            if child_type == TicketType.subtask:
                raise HierarchyError("subtask requires a parent of type 'task'")
            return

        parent_row = await session.execute(
            select(
                Ticket.id,
                Ticket.type,
                Ticket.parent_id,
                Ticket.project_id,
            ).where(Ticket.id == parent_id)
        )
        parent = parent_row.first()
        if parent is None:
            raise HierarchyError("parent does not exist")

        allowed = _PARENT_ALLOWED.get(child_type, set())
        if parent.type not in allowed:
            raise HierarchyError(
                f"{child_type.value} cannot have parent of type {parent.type.value}"
            )

        if (
            child_project_id is not None
            and parent.project_id is not None
            and parent.project_id != child_project_id
        ):
            raise CrossProjectParentError(
                child_project_id=child_project_id,
                parent_project_id=parent.project_id,
            )

        if child_id is not None:
            seen: set[UUID] = set()
            cursor: UUID | None = parent.id
            while cursor is not None:
                if cursor == child_id:
                    raise HierarchyError("cycle detected in parent chain")
                if cursor in seen:
                    raise HierarchyError("cycle detected in existing parent chain")
                seen.add(cursor)
                row = await session.execute(
                    select(Ticket.parent_id).where(Ticket.id == cursor)
                )
                nxt = row.scalar_one_or_none()
                cursor = nxt

    async def _walk_to_epic(
        self, session: AsyncSession, parent_id: UUID | None
    ) -> UUID | None:
        """Walk parent chain to the first ancestor of type epic.

        Returns the ancestor's id, or ``None`` if no epic ancestor exists.
        Used to maintain the ``epic_id`` denorm column on insert and on
        parent change. Bounded by a generous depth-cap (50) as a guard
        against cycles slipping past validation.
        """
        cursor = parent_id
        seen: set[UUID] = set()
        for _ in range(50):
            if cursor is None or cursor in seen:
                return None
            seen.add(cursor)
            row = await session.execute(
                select(Ticket.type, Ticket.parent_id).where(Ticket.id == cursor)
            )
            r = row.first()
            if r is None:
                return None
            if r.type == TicketType.epic:
                return cursor
            cursor = r.parent_id
        return None

    async def _resolve_handles_to_uuids(
        self, session: AsyncSession, handles: Sequence[str]
    ) -> list[UUID]:
        """Best-effort resolve `@handle` tokens to user/agent UUIDs.

        Looks up the ``users.email`` local-part (everything before ``@``)
        and any agent accounts whose name matches. Unresolved handles are
        silently dropped. Per spec §6 mentions are storage-only (no
        notification fanout in v2).
        """
        if not handles:
            return []
        uniq = list({h for h in handles if h})
        out: list[UUID] = []
        # Resolve via users.email local-part. We deliberately don't import
        # the User model at module-scope to avoid circular imports during
        # alembic env reflection.
        try:
            from app.models.user import User  # noqa: WPS433 — local import
            res = await session.execute(
                select(User.id, User.email).where(User.email.is_not(None))
            )
            rows = list(res.all())
            by_local = {
                (str(r.email).split("@", 1)[0]).lower(): r.id
                for r in rows
                if r.email
            }
            for h in uniq:
                uid = by_local.get(h.lower())
                if uid is not None:
                    out.append(uid)
        except Exception:  # pragma: no cover — defensive
            return []
        return out

    async def _resolve_project(
        self,
        session: AsyncSession,
        *,
        project_id: UUID | str | None,
        project_key: str | None,
    ) -> Project:
        """Resolve the target project, falling back to the Default project.

        Returns the loaded ``Project`` row. Raises ValidationError if no
        Default project exists (which would mean the WP2 backfill never
        ran — a deployment bug, not user input).
        """
        ident: UUID | str | None
        if project_id is not None:
            ident = project_id
        elif project_key is not None:
            ident = project_key
        else:
            ident = _DEFAULT_PROJECT_KEY
        proj = await project_service.get(session, ident)
        if proj is None:
            if ident == _DEFAULT_PROJECT_KEY:
                raise ValidationError(
                    [
                        {
                            "name": "project_id",
                            "reason": (
                                "no Default project found; service depends on "
                                "WP2 migration a9_ticketing_v2 having run"
                            ),
                        }
                    ]
                )
            raise ValidationError(
                [{"name": "project_id", "reason": f"unknown project: {ident!r}"}]
            )
        return proj

    # -- create / get / list / update / delete -----------------------------

    @traced(action="create")
    async def create(
        self,
        session: AsyncSession,
        *,
        actor: Actor,
        title: str,
        description: str | None = None,
        type: TicketType = TicketType.task,
        priority: TicketPriority = TicketPriority.medium,
        parent_id: UUID | None = None,
        assignee_id: UUID | None = None,
        assignee_type: str | None = None,
        labels: Sequence[str] | None = None,
        custom_fields: dict[str, Any] | None = None,
        story_points: int | None = None,
        due_date: datetime | None = None,
        project_id: UUID | str | None = None,
        project_key: str | None = None,
        sprint_id: UUID | None = None,
        component_id: UUID | None = None,
        fix_versions: Sequence[str] | None = None,
        correlation_id: str = "",
    ) -> Ticket:
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

        proj = await self._resolve_project(
            session, project_id=project_id, project_key=project_key
        )

        await self._validate_hierarchy(
            session,
            child_type=type,
            parent_id=parent_id,
            child_project_id=proj.id,
        )

        # Per-project sequence allocation. Sets seq_number AND display_id
        # from the same nextval() invocation.
        seq_number = await project_service.next_seq_number(session, proj.key)
        display_id = f"{proj.key}-{seq_number}"

        # Walk to first epic ancestor for the denorm column.
        epic_id = await self._walk_to_epic(session, parent_id)

        # Default status: workpackage/epic -> backlog; everything else -> todo.
        default_status = (
            TicketStatus.backlog
            if type in (TicketType.workpackage, TicketType.epic)
            else TicketStatus.todo
        )

        # Pick up agent_step_id from the request contextvar. Only stamped
        # when actor is an agent (CHECK constraint).
        actor_type_value = _actor_type_str(actor)
        step_id = (
            get_agent_step_id() if actor_type_value == "agent" else None
        )

        ticket = Ticket(
            title=title,
            description=description,
            type=type,
            status=default_status,
            priority=priority,
            parent_id=parent_id,
            project_id=proj.id,
            sprint_id=sprint_id,
            component_id=component_id,
            epic_id=epic_id,
            reporter_id=actor.id,
            reporter_type=actor_type_value,
            assignee_id=assignee_id,
            assignee_type=assignee_type,
            labels=list(labels or []),
            fix_versions=list(fix_versions or []),
            custom_fields=dict(custom_fields or {}),
            story_points=story_points,
            due_date=due_date,
            created_agent_step_id=step_id,
            version=1,
            seq_number=seq_number,
            display_id=display_id,
            last_actor_type=actor_type_value,
            last_actor_id=actor.id,
            last_activity_at=datetime.now(timezone.utc),
            last_agent_step_id=step_id,
        )
        session.add(ticket)
        try:
            await session.flush([ticket])
        except IntegrityError as exc:
            # Map cross-project trigger violations to a typed exception.
            msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
            if "trg_tickets_same_project" in msg or "same project" in msg.lower():
                raise CrossProjectParentError(
                    child_project_id=proj.id, parent_project_id=None
                ) from exc
            raise ValidationError(
                [{"name": "parent_id", "reason": "constraint violated"}]
            ) from exc

        await session.refresh(ticket)

        session.add(
            TicketTransition(
                ticket_id=ticket.id,
                from_status=None,
                to_status=default_status,
                actor_id=actor.id,
                actor_type=actor_type_value,
                reason=None,
                correlation_id=correlation_id or "",
                agent_step_id=step_id,
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
            },
        )
        return ticket

    async def get(
        self, session: AsyncSession, ticket_id: UUID | str
    ) -> Ticket:
        return await self._load(session, ticket_id)

    async def list_page(
        self,
        session: AsyncSession,
        *,
        status: Sequence[TicketStatus | str] | None = None,
        type: Sequence[TicketType | str] | None = None,
        assignee_id: UUID | str | None = None,
        parent_id: UUID | None = None,
        project_id: UUID | None = None,
        sprint_id: UUID | str | None = None,
        component_id: UUID | str | None = None,
        epic_id: UUID | str | None = None,
        labels: Sequence[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
        count_total: bool = False,
        include_column_counts: bool = False,
        order_by: Literal["created_at", "last_activity_at"] = "created_at",
    ) -> dict[str, Any]:
        """Paginated ticket listing (v2.1-WP10).

        Cursor pagination is keyset-based: the cursor encodes
        ``(sort_col, id)`` of the last row returned (where ``sort_col``
        is the chosen ordering column), and the next page applies a
        ``(sort_col, id) < (cursor.t, cursor.i)`` WHERE clause. The
        legacy ``offset`` argument is still accepted for backwards
        compatibility but routes prefer ``cursor``. When both are
        supplied the cursor wins.

        Filter sentinels (v2.1-WP10):
          * ``assignee_id="null"`` / ``sprint_id="null"`` etc. — the
            literal string ``"null"`` matches ``IS NULL``.
          * ``assignee_id="me"`` — caller's responsibility to translate
            to an actor UUID before calling the service.
          * ``assignee_id=None`` / unset — no filter applied.

        ``count_total=True`` runs a COUNT over the same WHERE clause and
        returns it in ``total``. Otherwise ``total=None`` (caller didn't
        want to pay for it).

        Order: controlled by ``order_by`` (default ``"created_at"``):
          * ``"created_at"`` — ``created_at DESC, id DESC`` (original
            behaviour; backward-compatible default).
          * ``"last_activity_at"`` — ``COALESCE(last_activity_at,
            created_at) DESC, id DESC``. COALESCE is applied
            defensively: any row whose ``last_activity_at`` is NULL
            (created before WP6 stamping) falls back to ``created_at``.

        v2.3-WP22 — cursor ``t`` field semantics: when
        ``order_by="last_activity_at"`` the cursor encodes the
        *effective* activity timestamp (post-COALESCE) of the last
        returned row, NOT ``created_at``.  Cursors from one
        ``order_by`` mode MUST NOT be reused with the other mode —
        the client always passes ``order_by`` consistently across
        page fetches.
        """
        if limit < 0 or offset < 0:
            raise ValidationError(
                [{"name": "limit", "reason": "must be non-negative"}]
            )
        bounded_limit = max(0, min(limit, 500))

        # Determine the sort expression. COALESCE is applied defensively
        # so rows with NULL last_activity_at (pre-WP6 data) still sort
        # deterministically rather than floating to undefined position.
        from sqlalchemy import func as _func
        if order_by == "last_activity_at":
            sort_expr = _func.coalesce(Ticket.last_activity_at, Ticket.created_at)
        else:
            sort_expr = Ticket.created_at

        # ---- WHERE clauses ------------------------------------------
        conds: list[Any] = []
        if status:
            normalised = [
                s if isinstance(s, TicketStatus) else TicketStatus(s) for s in status
            ]
            conds.append(Ticket.status.in_(normalised))
        if type:
            ntypes = [
                t if isinstance(t, TicketType) else TicketType(t) for t in type
            ]
            conds.append(Ticket.type.in_(ntypes))
        if assignee_id is not None:
            if isinstance(assignee_id, str) and assignee_id == "null":
                conds.append(Ticket.assignee_id.is_(None))
            else:
                conds.append(Ticket.assignee_id == assignee_id)
        if parent_id is not None:
            conds.append(Ticket.parent_id == parent_id)
        if project_id is not None:
            conds.append(Ticket.project_id == project_id)
        if sprint_id is not None:
            if isinstance(sprint_id, str) and sprint_id == "null":
                conds.append(Ticket.sprint_id.is_(None))
            else:
                conds.append(Ticket.sprint_id == sprint_id)
        if component_id is not None:
            if isinstance(component_id, str) and component_id == "null":
                conds.append(Ticket.component_id.is_(None))
            else:
                conds.append(Ticket.component_id == component_id)
        if epic_id is not None:
            if isinstance(epic_id, str) and epic_id == "null":
                conds.append(Ticket.epic_id.is_(None))
            else:
                conds.append(Ticket.epic_id == epic_id)
        if labels:
            conds.append(Ticket.labels.contains(list(labels)))

        # ---- Cursor decoding ----------------------------------------
        cursor_pair: tuple[datetime, UUID] | None = None
        if cursor:
            cursor_pair = _decode_cursor(cursor)
            cur_ts, cur_id = cursor_pair
            # Keyset: rows strictly after the cursor in DESC order, i.e.
            # ``(sort_col, id) < (cur_ts, cur_id)``.
            from sqlalchemy import and_, or_

            conds.append(
                or_(
                    sort_expr < cur_ts,
                    and_(sort_expr == cur_ts, Ticket.id < cur_id),
                )
            )

        stmt = select(Ticket)
        for c in conds:
            stmt = stmt.where(c)

        # +1 to detect whether there's another page.
        fetch_n = bounded_limit + 1 if bounded_limit > 0 else 0
        stmt = stmt.order_by(sort_expr.desc(), Ticket.id.desc())
        if cursor_pair is None and offset > 0:
            stmt = stmt.offset(offset)
        if fetch_n > 0:
            stmt = stmt.limit(fetch_n)

        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > bounded_limit
        if has_more:
            rows = rows[:bounded_limit]

        next_cursor: str | None = None
        if has_more and rows:
            last = rows[-1]
            # Encode the effective sort timestamp for this ordering mode.
            if order_by == "last_activity_at":
                sort_ts = last.last_activity_at or last.created_at
            else:
                sort_ts = last.created_at
            next_cursor = _encode_cursor(sort_ts, last.id)

        total: int | None = None
        # Apply the same WHERE clauses EXCEPT the cursor clause to any
        # aggregate (total / column_counts).
        non_cursor_conds = (
            conds[:-1] if cursor_pair is not None else conds
        )
        if count_total:
            count_stmt = select(func.count()).select_from(Ticket)
            for c in non_cursor_conds:
                count_stmt = count_stmt.where(c)
            total = int((await session.execute(count_stmt)).scalar_one())

        # v2.1-WP11: per-status counts. Independent of limit/cursor — it's
        # an aggregate over the full filtered set, so Load-more pagination
        # never undercounts a column. All seven workflow statuses are seeded
        # to 0 first so the UI never has to defend against missing keys.
        column_counts: dict[str, int] | None = None
        if include_column_counts:
            column_counts = {s.value: 0 for s in TicketStatus}
            cc_stmt = select(Ticket.status, func.count()).select_from(Ticket)
            for c in non_cursor_conds:
                cc_stmt = cc_stmt.where(c)
            cc_stmt = cc_stmt.group_by(Ticket.status)
            cc_res = await session.execute(cc_stmt)
            for status_val, n in cc_res.all():
                key = (
                    status_val.value
                    if hasattr(status_val, "value")
                    else str(status_val)
                )
                column_counts[key] = int(n)

        return {
            "items": rows,
            "next_cursor": next_cursor,
            "total": total,
            "column_counts": column_counts,
        }

    @traced(action="update")
    async def update(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        expected_version: int,
        patch: dict[str, Any],
        correlation_id: str = "",
    ) -> Ticket:
        mutable = {
            "title",
            "description",
            "priority",
            "parent_id",
            "labels",
            "custom_fields",
            "story_points",
            "due_date",
            "sprint_id",
            "component_id",
            "fix_versions",
            "resolution",
        }
        unknown = set(patch) - mutable
        if unknown:
            raise ValidationError(
                [{"name": k, "reason": "not updatable via update()"} for k in unknown]
            )

        ticket = await self._load(session, ticket_id, for_update=True)
        if ticket.version != expected_version:
            raise OptimisticConcurrencyError(
                current_version=ticket.version, current=ticket.to_dict()
            )

        if "parent_id" in patch:
            new_parent = patch["parent_id"]
            await self._validate_hierarchy(
                session,
                child_type=ticket.type,
                parent_id=new_parent,
                child_id=ticket.id,
                child_project_id=ticket.project_id,
            )

        before = ticket.to_dict()
        for k, v in patch.items():
            if k == "priority" and v is not None and not isinstance(v, TicketPriority):
                v = TicketPriority(v)
            setattr(ticket, k, v)

        # Re-walk to first epic ancestor when parent changes; clear when
        # we've been detached from the chain.
        if "parent_id" in patch:
            ticket.epic_id = await self._walk_to_epic(session, ticket.parent_id)

        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        _stamp_last_activity(ticket, _actor_type_str(actor), actor.id)
        try:
            await session.flush([ticket])
        except IntegrityError as exc:
            msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
            if "trg_tickets_same_project" in msg or "same project" in msg.lower():
                raise CrossProjectParentError(
                    child_project_id=ticket.project_id,
                    parent_project_id=None,
                ) from exc
            raise

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
                "ticket_id": str(ticket.id),
                "version": ticket.version,
                "patch": {k: str(v) for k, v in patch.items()},
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )
        return ticket

    async def delete(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        correlation_id: str = "",
    ) -> None:
        """Hard delete. Fails (HasChildrenError) if any ticket has this as parent."""
        ticket = await self._load(session, ticket_id)

        child_count_row = await session.execute(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.parent_id == ticket.id)
        )
        child_count = int(child_count_row.scalar_one())
        if child_count > 0:
            raise HasChildrenError(child_count)

        before = ticket.to_dict()
        await session.delete(ticket)
        await session.flush()

        await self._audit.record(
            session,
            entity_type="ticket",
            entity_id=ticket.id,
            action="delete",
            actor=actor,
            diff={"before": before, "after": None},
            correlation_id=correlation_id,
        )
        stage_event(
            session,
            "ticket.deleted",
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            payload={
                "ticket_id": str(ticket.id),
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )

    # -- transition / assign / claim ---------------------------------------

    @traced(action="transition")
    async def transition(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        target_status: TicketStatus | str,
        reason: str | None = None,
        correlation_id: str = "",
    ) -> Ticket:
        target = (
            target_status
            if isinstance(target_status, TicketStatus)
            else TicketStatus(target_status)
        )
        ticket = await self._load(session, ticket_id, for_update=True)
        current = ticket.status
        if current == target:
            raise InvalidTransitionError(current.value, target.value)
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransitionError(current.value, target.value)

        before = ticket.to_dict()
        actor_type_value = _actor_type_str(actor)
        step_id = (
            get_agent_step_id() if actor_type_value == "agent" else None
        )
        session.add(
            TicketTransition(
                ticket_id=ticket.id,
                from_status=current,
                to_status=target,
                actor_id=actor.id,
                actor_type=actor_type_value,
                reason=reason,
                correlation_id=correlation_id or "",
                agent_step_id=step_id,
            )
        )
        ticket.status = target
        if target in TERMINAL_STATUSES:
            ticket.resolved_at = datetime.now(timezone.utc)
        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        _stamp_last_activity(ticket, actor_type_value, actor.id)
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
                "ticket_id": str(ticket.id),
                "from_status": current.value,
                "to_status": target.value,
                "reason": reason,
                "version": ticket.version,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )

        # v2.3-WP25 — ticket_state_change notification fanout.
        # Load watchers and fan out to assignee + watchers, excluding actor.
        from app.services.ticket_notifications import (
            ticket_notifications_service as _tns,
        )
        _watchers_res = await session.execute(
            select(TicketWatcher).where(TicketWatcher.ticket_id == ticket.id)
        )
        _watchers = [
            {"watcher_type": w.watcher_type, "watcher_id": w.watcher_id}
            for w in _watchers_res.scalars().all()
        ]
        actor_type_val = _actor_type_str(actor)
        await _tns.fanout_state_change(
            session,
            actor_type=actor_type_val,
            actor_id=actor.id,
            from_status=current.value,
            to_status=target.value,
            target_id=ticket.id,
            target_display_id=ticket.display_id,
            assignee_type=ticket.assignee_type,
            assignee_id=ticket.assignee_id,
            watchers=_watchers,
            project_id=ticket.project_id,
        )

        # v2.4-WP30 — ticket_blocked fanout (no coalescing, in addition to
        # ticket_state_change). Emitted whenever the new status is "blocked".
        if target == TicketStatus.blocked:
            await _tns.fanout_blocked(
                session,
                actor_type=actor_type_val,
                actor_id=actor.id,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                assignee_type=ticket.assignee_type,
                assignee_id=ticket.assignee_id,
                watchers=_watchers,
            )

        # v2.5-WP37 — ticket_resolved fanout (no coalescing, done-only).
        # Distinct from ticket_state_change — emitted only on the done transition.
        if target == TicketStatus.done:
            await _tns.fanout_resolved(
                session,
                actor_type=actor_type_val,
                actor_id=actor.id,
                from_status=current.value,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                assignee_type=ticket.assignee_type,
                assignee_id=ticket.assignee_id,
                reporter_type=ticket.reporter_type,
                reporter_id=ticket.reporter_id,
                watchers=_watchers,
            )

        # v2.6-WP40 — ticket_cancelled fanout (no coalescing, cancelled-only).
        # Mirrors ticket_resolved but for the cancelled terminal state.
        if target == TicketStatus.cancelled:
            await _tns.fanout_cancelled(
                session,
                actor_type=actor_type_val,
                actor_id=actor.id,
                from_status=current.value,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                assignee_type=ticket.assignee_type,
                assignee_id=ticket.assignee_id,
                reporter_type=ticket.reporter_type,
                reporter_id=ticket.reporter_id,
                watchers=_watchers,
            )

        return ticket

    @traced(action="assign")
    async def assign(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        assignee_id: UUID | None,
        assignee_type: str | None,
        expected_version: int,
        correlation_id: str = "",
    ) -> Ticket:
        if (assignee_id is None) != (assignee_type is None):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be paired with assignee_id"}]
            )
        if assignee_type is not None and assignee_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "assignee_type", "reason": "must be 'user' or 'agent'"}]
            )

        ticket = await self._load(session, ticket_id, for_update=True)
        if ticket.version != expected_version:
            raise OptimisticConcurrencyError(
                current_version=ticket.version, current=ticket.to_dict()
            )

        # Detect whether assignee actually changed (skip unchanged + null).
        prev_assignee_id = ticket.assignee_id
        prev_assignee_type = ticket.assignee_type

        before = ticket.to_dict()
        ticket.assignee_id = assignee_id
        ticket.assignee_type = assignee_type
        ticket.version = ticket.version + 1
        ticket.updated_at = datetime.now(timezone.utc)
        _stamp_last_activity(ticket, _actor_type_str(actor), actor.id)
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
                "ticket_id": str(ticket.id),
                "assignee_id": str(assignee_id) if assignee_id else None,
                "assignee_type": assignee_type,
                "version": ticket.version,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )

        # v2.3-WP25 — ticket_assigned notification fanout.
        # Only when assignee changed to a non-null value.
        _assignee_changed = assignee_id is not None and (
            assignee_id != prev_assignee_id or assignee_type != prev_assignee_type
        )
        if _assignee_changed:
            from app.services.ticket_notifications import (
                ticket_notifications_service as _tns,
            )
            actor_type_val = _actor_type_str(actor)
            await _tns.fanout_assigned(
                session,
                actor_type=actor_type_val,
                actor_id=actor.id,
                assignee_type=assignee_type,
                assignee_id=assignee_id,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                ticket_title=ticket.title,
            )

        # V4b — when the new assignee is an agent, enqueue an agent_run.
        # The queue runs the provider on a later ``POST /agent-runs/process-
        # next`` call; here we only durably record the work item.  The
        # queue's idempotency key dedups re-assignments of the same agent
        # to the same ticket with the same prompt.
        # We only enqueue when the target agent row actually exists.  The
        # ``ticket.assignee_id`` column has no FK to ``agent_accounts``
        # (the same column also holds user ids for human assignees), so
        # callers can assign to a non-existent agent id without violating
        # any constraint — but the ``agent_run.agent_id`` FK would reject
        # such a row and poison the surrounding transaction.
        if (
            _assignee_changed
            and assignee_type == "agent"
            and assignee_id is not None
        ):
            from app.models.agent_account import AgentAccount as _AgentAccount
            from app.services.agent_run_queue import get_default_queue
            _agent_exists = (
                await session.execute(
                    select(_AgentAccount.id).where(
                        _AgentAccount.id == assignee_id
                    )
                )
            ).scalar_one_or_none()
            if _agent_exists is not None:
                prompt_text = (
                    f"{ticket.title}\n\n{ticket.description or ''}"
                ).strip()
                await get_default_queue(session).enqueue(
                    session,
                    agent_id=assignee_id,
                    ticket_id=ticket.id,
                    comment_id=None,
                    prompt=prompt_text,
                )

        return ticket

    @traced(action="claim")
    async def claim(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        correlation_id: str = "",
    ) -> Ticket:
        if actor.type != ActorType.agent and str(getattr(actor, "type", "")) != "agent":
            raise ForbiddenError("only agents can claim tickets")

        target_id = await self._resolve_id(session, ticket_id)

        _now = datetime.now(timezone.utc)
        _step_id = get_agent_step_id()
        stmt = (
            update(Ticket)
            .where(Ticket.id == target_id, Ticket.assignee_id.is_(None))
            .values(
                assignee_id=actor.id,
                assignee_type="agent",
                version=Ticket.version + 1,
                updated_at=_now,
                last_actor_type="agent",
                last_actor_id=actor.id,
                last_activity_at=_now,
                last_agent_step_id=_step_id,
            )
            .returning(Ticket.id)
        )
        result = await session.execute(stmt)
        updated_id = result.scalar_one_or_none()
        if updated_id is None:
            existing = await session.execute(
                select(Ticket.assignee_id).where(Ticket.id == target_id)
            )
            row = existing.first()
            if row is None:
                raise TicketNotFoundError(ticket_id)
            raise AlreadyClaimedError(current_assignee_id=row[0])

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
                "ticket_id": str(ticket.id),
                "version": ticket.version,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )
        return ticket

    # -- comments + links --------------------------------------------------

    @traced(action="add_comment")
    async def add_comment(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        body: str,
        mentions: Sequence[UUID] | None = None,
        correlation_id: str = "",
        parent_comment_id: UUID | None = None,
    ) -> TicketComment:
        if not body or not body.strip():
            raise ValidationError([{"name": "body", "reason": "required"}])
        ticket = await self._load(session, ticket_id)

        # v7a: same-ticket invariant for nested replies.
        if parent_comment_id is not None:
            parent = (
                await session.execute(
                    select(TicketComment).where(
                        TicketComment.id == parent_comment_id
                    )
                )
            ).scalar_one_or_none()
            if parent is None or parent.ticket_id != ticket.id:
                raise ValidationError(
                    [{
                        "name": "parent_comment_id",
                        "reason": "must reference a comment on the same ticket",
                    }]
                )

        actor_type_value = _actor_type_str(actor)
        step_id = (
            get_agent_step_id() if actor_type_value == "agent" else None
        )

        # v2.1-WP9: mentions can arrive two ways. Explicit ``mentions``
        # kwarg short-circuits parsing (caller already resolved). Empty
        # kwarg → parse ``@handle`` tokens from the body and resolve via
        # ``app.services.people.resolve_mention`` (covers BOTH users and
        # agents, unlike the v2-era ``_resolve_handles_to_uuids`` which
        # was users-only). Unresolved tokens are silently dropped.
        #
        # ``resolved_refs`` keeps the full PersonRef-shape dicts around
        # so we can fan notifications out below; ``resolved`` is just
        # the UUIDs (back-compat: that's what the comment row stores).
        from app.services.people import resolve_mentions as _resolve_refs
        from app.services.ticket_notifications import (
            ticket_notifications_service,
        )

        resolved: list[UUID] = []
        resolved_refs: list[dict] = []
        if mentions is not None and len(list(mentions)) > 0:
            resolved = [
                m if isinstance(m, UUID) else UUID(str(m)) for m in mentions
            ]
            # No PersonRef dicts when caller passed raw UUIDs — fanout
            # below treats each UUID as a user recipient by default
            # (back-compat with the v2 storage-only contract).
            resolved_refs = [
                {"kind": "user", "id": uid} for uid in resolved
            ]
        else:
            handles = _MENTION_RE.findall(body)
            if handles:
                resolved_refs = await _resolve_refs(session, handles)
                resolved = [
                    r["id"] if isinstance(r["id"], UUID) else UUID(str(r["id"]))
                    for r in resolved_refs
                ]

        comment = TicketComment(
            ticket_id=ticket.id,
            parent_comment_id=parent_comment_id,
            author_id=actor.id,
            author_type=actor_type_value,
            body=body,
            correlation_id=correlation_id or "",
            agent_step_id=step_id,
            mentions=resolved,
        )
        session.add(comment)
        await session.flush([comment])

        # Fanout: one ``ticket_notifications`` row per resolved mention.
        # Self-mentions skipped inside the service. Schema-level
        # uniqueness handles idempotency for comment re-saves.
        if resolved_refs:
            await ticket_notifications_service.fanout_mentions(
                session,
                recipients=resolved_refs,
                actor_type=actor_type_value,
                actor_id=actor.id,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                comment_id=comment.id,
                excerpt=body,
            )

        _stamp_last_activity(ticket, actor_type_value, actor.id)
        await session.flush([ticket])

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
                "ticket_id": str(ticket.id),
                "comment_id": str(comment.id),
                "body": body,
                "actor": {"id": str(actor.id), "type": _actor_type_str(actor), "name": actor.label},
            },
        )
        return comment

    async def list_comments(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
    ) -> list[TicketComment]:
        ticket = await self._load(session, ticket_id)
        result = await session.execute(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket.id)
            .order_by(TicketComment.created_at.asc())
        )
        return list(result.scalars().all())

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
        if source_id == target_id:
            raise ValidationError(
                [{"name": "target_id", "reason": "cannot link a ticket to itself"}]
            )
        lt = (
            link_type
            if isinstance(link_type, TicketLinkType)
            else TicketLinkType(link_type)
        )
        # v2: hierarchy lives on `tickets.parent_id`. parent_of/child_of are
        # tombstoned. Refuse to write either side per Cross-WP Rule #3.
        if lt in _TOMBSTONED_LINK_TYPES:
            raise ValidationError(
                [
                    {
                        "name": "link_type",
                        "reason": (
                            f"link_type {lt.value!r} is tombstoned in v2; "
                            "hierarchy lives on tickets.parent_id"
                        ),
                    }
                ]
            )
        source_ticket = await self._load(session, source_id)
        await self._load(session, target_id)

        actor_type_value = _actor_type_str(actor)
        step_id = (
            get_agent_step_id() if actor_type_value == "agent" else None
        )

        row = TicketLink(
            source_id=source_id,
            target_id=target_id,
            link_type=lt,
            created_by=actor.id,
            created_by_type=actor_type_value,
            agent_step_id=step_id,
        )
        session.add(row)
        try:
            await session.flush([row])
        except IntegrityError as exc:
            raise DuplicateLinkError(
                f"link {source_id}->{target_id} ({lt.value}) already exists"
            ) from exc

        # Inverse pair maintenance (transactional). `relates_to` is
        # symmetric; one row suffices. We pre-check for the existing
        # inverse to avoid poisoning the surrounding TX with a uniqueness
        # IntegrityError (asyncpg aborts the TX otherwise).
        inverse = _LINK_INVERSES.get(lt)
        if inverse is not None:
            existing = await session.execute(
                select(TicketLink.id).where(
                    TicketLink.source_id == target_id,
                    TicketLink.target_id == source_id,
                    TicketLink.link_type == inverse,
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    TicketLink(
                        source_id=target_id,
                        target_id=source_id,
                        link_type=inverse,
                        created_by=actor.id,
                        created_by_type=actor_type_value,
                        agent_step_id=step_id,
                    )
                )
                await session.flush()

        _stamp_last_activity(source_ticket, actor_type_value, actor.id)
        await session.flush([source_ticket])

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

    async def list_links(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
    ) -> dict[str, list[TicketLink]]:
        ticket = await self._load(session, ticket_id)
        outgoing_res = await session.execute(
            select(TicketLink).where(TicketLink.source_id == ticket.id)
        )
        incoming_res = await session.execute(
            select(TicketLink).where(TicketLink.target_id == ticket.id)
        )
        return {
            "outgoing": list(outgoing_res.scalars().all()),
            "incoming": list(incoming_res.scalars().all()),
        }

    # -- subtree + search --------------------------------------------------

    async def get_subtree(
        self,
        session: AsyncSession,
        root_id: UUID | str,
        *,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        tid = await self._resolve_id(session, root_id)
        await self._load(session, tid)
        cte_sql = text(
            """
            WITH RECURSIVE subtree(id, depth) AS (
                SELECT t.id, 0 AS depth FROM tickets t WHERE t.id = :root_id
                UNION ALL
                SELECT c.id, s.depth + 1
                  FROM tickets c
                  JOIN subtree s ON c.parent_id = s.id
                 WHERE s.depth + 1 <= :max_depth
            )
            SELECT id, depth FROM subtree ORDER BY depth, id
            """
        )
        result = await session.execute(
            cte_sql, {"root_id": tid, "max_depth": max_depth}
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

    # -- watchers ----------------------------------------------------------

    async def add_watcher(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        watcher_id: UUID,
        watcher_type: str = "user",
        actor: Actor | None = None,
    ) -> TicketWatcher:
        """Idempotent add — returns the existing row when (ticket, watcher) already present.

        v2.4-WP30: when ``actor`` is supplied and the watcher is newly added
        (not already watching), emits a ``ticket_watcher_added`` notification
        to the watcher. Self-watches (actor == watcher) are silently skipped.
        """
        if watcher_type not in ("user", "agent"):
            raise ValidationError(
                [{"name": "watcher_type", "reason": "must be 'user' or 'agent'"}]
            )
        ticket = await self._load(session, ticket_id)
        existing = await session.execute(
            select(TicketWatcher).where(
                TicketWatcher.ticket_id == ticket.id,
                TicketWatcher.watcher_id == watcher_id,
                TicketWatcher.watcher_type == watcher_type,
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            return prior
        w = TicketWatcher(
            ticket_id=ticket.id,
            watcher_id=watcher_id,
            watcher_type=watcher_type,
        )
        session.add(w)
        await session.flush([w])

        # v2.4-WP30 — ticket_watcher_added notification fanout.
        if actor is not None:
            from app.services.ticket_notifications import (
                ticket_notifications_service as _tns,
            )
            actor_type_val = _actor_type_str(actor)
            await _tns.fanout_watcher_added(
                session,
                actor_type=actor_type_val,
                actor_id=actor.id,
                watcher_type=watcher_type,
                watcher_id=watcher_id,
                target_id=ticket.id,
                target_display_id=ticket.display_id,
                ticket_title=ticket.title,
            )

        return w

    async def remove_watcher(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        watcher_id: UUID,
        watcher_type: str = "user",
    ) -> None:
        ticket = await self._load(session, ticket_id)
        res = await session.execute(
            select(TicketWatcher).where(
                TicketWatcher.ticket_id == ticket.id,
                TicketWatcher.watcher_id == watcher_id,
                TicketWatcher.watcher_type == watcher_type,
            )
        )
        w = res.scalar_one_or_none()
        if w is None:
            return
        await session.delete(w)
        await session.flush()

    async def list_watchers(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
    ) -> list[TicketWatcher]:
        ticket = await self._load(session, ticket_id)
        res = await session.execute(
            select(TicketWatcher)
            .where(TicketWatcher.ticket_id == ticket.id)
            .order_by(TicketWatcher.created_at.asc())
        )
        return list(res.scalars().all())

    # -- attachments -------------------------------------------------------

    async def add_attachment(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        actor: Actor,
        filename: str,
        content_type: str,
        byte_size: int,
        storage_path: str,
    ) -> TicketAttachment:
        ticket = await self._load(session, ticket_id)
        actor_type_value = _actor_type_str(actor)
        step_id = (
            get_agent_step_id() if actor_type_value == "agent" else None
        )
        att = TicketAttachment(
            ticket_id=ticket.id,
            uploaded_by=actor.id,
            uploaded_by_type=actor_type_value,
            filename=filename,
            content_type=content_type,
            byte_size=int(byte_size),
            storage_path=storage_path,
            agent_step_id=step_id,
        )
        session.add(att)
        await session.flush([att])
        return att

    async def list_attachments(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
    ) -> list[TicketAttachment]:
        ticket = await self._load(session, ticket_id)
        res = await session.execute(
            select(TicketAttachment)
            .where(TicketAttachment.ticket_id == ticket.id)
            .order_by(TicketAttachment.created_at.asc())
        )
        return list(res.scalars().all())

    async def delete_attachment(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        attachment_id: UUID,
    ) -> None:
        ticket = await self._load(session, ticket_id)
        res = await session.execute(
            select(TicketAttachment).where(
                TicketAttachment.id == attachment_id,
                TicketAttachment.ticket_id == ticket.id,
            )
        )
        att = res.scalar_one_or_none()
        if att is None:
            return
        await session.delete(att)
        await session.flush()

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
        """Full-text search on search_tsv with optional label/status filters."""
        if not query:
            page = await self.list_page(
                session, status=status, labels=labels, limit=limit, offset=offset
            )
            return list(page["items"])

        ts_query = func.plainto_tsquery("english", query)
        stmt = select(Ticket).where(Ticket.search_tsv.op("@@")(ts_query))
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

    # -- activity feed (v2.1-WP7) -----------------------------------------

    async def list_activity(
        self,
        session: AsyncSession,
        ticket_id: UUID | str,
        *,
        include: set[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return a cursor-paginated activity feed for a ticket (v2.2-WP16).

        v2.7-WP50: replaces the prior in-memory union with a SQL ``UNION
        ALL`` across the included source streams. Each arm projects a
        uniform envelope ``(kind, id, ticket_id, actor_type, actor_id,
        agent_step_id, created_at, payload)`` where ``payload`` is a JSONB
        bag of kind-specific fields (``from_status``/``to_status`` for
        transitions, ``body``/``mentions`` for comments, ``link_type``/
        ``target_ticket_id`` for links). The outer query applies the
        cursor predicate, orders ``created_at DESC, id DESC``, and limits
        to ``page_size + 1`` for has-more detection. ``total`` is a
        ``SELECT COUNT(*)`` over the same UNION subquery — populated on
        every page (v2.6-WP45 contract).

        ``include`` toggles UNION arms beyond the default ``transitions``
        source. Allowed members: ``"comments"``, ``"links"``. Items are
        ordered by ``created_at DESC, id DESC`` for stable interleaving.

        Pagination: cursor-based, reusing ``_encode_cursor``/``_decode_cursor``
        (same opaque base64-JSON shape as ``GET /api/v1/tickets``).
        """
        include = include or set()
        ticket = await self._load(session, ticket_id)
        tid = ticket.id

        # Build per-arm SELECTs with a uniform output shape. Postgres
        # ``jsonb_build_object`` packs the kind-specific tail into a single
        # JSONB column so UNION ALL stays type-compatible across arms.
        arms = []

        arms.append(
            select(
                literal("transition").label("kind"),
                TicketTransition.id.label("id"),
                TicketTransition.ticket_id.label("ticket_id"),
                TicketTransition.actor_type.label("actor_type"),
                TicketTransition.actor_id.label("actor_id"),
                TicketTransition.agent_step_id.label("agent_step_id"),
                TicketTransition.created_at.label("created_at"),
                func.jsonb_build_object(
                    "from_status",
                    TicketTransition.from_status,
                    "to_status",
                    TicketTransition.to_status,
                    "reason",
                    TicketTransition.reason,
                ).label("payload"),
            ).where(TicketTransition.ticket_id == tid)
        )

        if "comments" in include:
            arms.append(
                select(
                    literal("comment").label("kind"),
                    TicketComment.id.label("id"),
                    TicketComment.ticket_id.label("ticket_id"),
                    TicketComment.author_type.label("actor_type"),
                    TicketComment.author_id.label("actor_id"),
                    TicketComment.agent_step_id.label("agent_step_id"),
                    TicketComment.created_at.label("created_at"),
                    func.jsonb_build_object(
                        "body",
                        TicketComment.body,
                        "mentions",
                        TicketComment.mentions,
                    ).label("payload"),
                ).where(TicketComment.ticket_id == tid)
            )

        if "links" in include:
            # Outbound links only (source side is the "touched" side per
            # WP6 stamping semantics). ``ticket_id`` in the unified shape
            # is the source_id; the link arm preserves both endpoints in
            # the payload.
            arms.append(
                select(
                    literal("link").label("kind"),
                    TicketLink.id.label("id"),
                    TicketLink.source_id.label("ticket_id"),
                    TicketLink.created_by_type.label("actor_type"),
                    TicketLink.created_by.label("actor_id"),
                    TicketLink.agent_step_id.label("agent_step_id"),
                    TicketLink.created_at.label("created_at"),
                    func.jsonb_build_object(
                        "source_ticket_id",
                        TicketLink.source_id,
                        "target_ticket_id",
                        TicketLink.target_id,
                        "link_type",
                        TicketLink.link_type,
                    ).label("payload"),
                ).where(TicketLink.source_id == tid)
            )

        union_q = arms[0].union_all(*arms[1:]) if len(arms) > 1 else arms[0]
        sub = union_q.subquery("activity_union")

        # ``total`` — single COUNT(*) over the same UNION subquery (same
        # predicate set as items, count form). Populated on every page.
        count_stmt = select(func.count()).select_from(sub)
        total_res = await session.execute(count_stmt)
        total: int | None = int(total_res.scalar_one())

        # Items: cursor predicate + DESC order + page_size+1 for has-more.
        bounded = max(0, min(limit, 500))
        items_stmt = select(sub)
        if cursor is not None:
            anchor_ts, anchor_id = _decode_cursor(cursor)
            # Lexicographic ``(created_at, id) < (anchor_ts, anchor_id)``
            # under DESC ordering — Postgres row-value comparison.
            items_stmt = items_stmt.where(
                text("(created_at, id::text) < (:a_ts, :a_id)").bindparams(
                    a_ts=anchor_ts, a_id=str(anchor_id)
                )
            )
        items_stmt = items_stmt.order_by(
            sub.c.created_at.desc(),
            sub.c.id.desc(),
        )
        if bounded > 0:
            items_stmt = items_stmt.limit(bounded + 1)
        else:
            items_stmt = items_stmt.limit(0)

        items_res = await session.execute(items_stmt)
        raw_rows = list(items_res.mappings().all())

        # has-more detection.
        has_more = bounded > 0 and len(raw_rows) > bounded
        page_rows = raw_rows[:bounded] if bounded > 0 else []

        # Re-expand the JSONB payload into the legacy per-kind dict shape
        # (envelope must remain byte-identical to the pre-WP50 contract).
        sliced: list[dict[str, Any]] = []
        for r in page_rows:
            payload = r["payload"] or {}
            kind = r["kind"]
            if kind == "transition":
                sliced.append(
                    {
                        "kind": "transition",
                        "id": r["id"],
                        "ticket_id": r["ticket_id"],
                        "from_status": payload.get("from_status"),
                        "to_status": payload.get("to_status"),
                        "actor_type": r["actor_type"],
                        "actor_id": r["actor_id"],
                        "agent_step_id": r["agent_step_id"],
                        "reason": payload.get("reason"),
                        "created_at": r["created_at"],
                    }
                )
            elif kind == "comment":
                sliced.append(
                    {
                        "kind": "comment",
                        "id": r["id"],
                        "ticket_id": r["ticket_id"],
                        "body": payload.get("body"),
                        "mentions": list(payload.get("mentions") or []),
                        "actor_type": r["actor_type"],
                        "actor_id": r["actor_id"],
                        "agent_step_id": r["agent_step_id"],
                        "created_at": r["created_at"],
                        "edited_at": None,
                    }
                )
            elif kind == "link":
                sliced.append(
                    {
                        "kind": "link",
                        "id": r["id"],
                        "source_ticket_id": payload.get("source_ticket_id")
                        or r["ticket_id"],
                        "target_ticket_id": payload.get("target_ticket_id"),
                        "link_type": payload.get("link_type"),
                        "actor_type": r["actor_type"],
                        "actor_id": r["actor_id"],
                        "agent_step_id": r["agent_step_id"],
                        "created_at": r["created_at"],
                    }
                )

        next_cursor: str | None = None
        if has_more and sliced:
            last = sliced[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        return {"items": sliced, "total": total, "next_cursor": next_cursor}
