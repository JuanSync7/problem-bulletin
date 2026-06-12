"""AuditService — append-only journal writer (Task S1 / A9).

Every state-changing service operation MUST call :meth:`AuditService.record`
inside its own SQLAlchemy transaction. The audit table has ``REVOKE UPDATE,
DELETE`` applied at the schema level so there is no rollback path for an
audit row separate from its mutation — the two must commit together.

The service does NOT open its own session and NEVER commits. The caller's
session is used directly so that a single transaction covers both the
business write and the audit insert (NFR-181 atomicity).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log_event import AuditLogEvent
from app.services.context import Actor


class AuditService:
    """Append-only audit journal.

    Stateless; safe to instantiate per request or use as a singleton.
    """

    async def record(
        self,
        session: AsyncSession,
        *,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: Actor,
        diff: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> AuditLogEvent:
        """Insert one ``audit_log`` row using the caller's session.

        Parameters
        ----------
        session : AsyncSession
            Caller-owned session. NEVER replaced; we ``add`` + ``flush`` so the
            row participates in the same transaction as the mutation.
        entity_type : str
            One of ``'ticket'``, ``'ticket_comment'``, ``'ticket_link'``,
            ``'agent_account'`` (free-form on purpose; route layer enforces
            the closed set).
        entity_id : UUID
            Target row's UUID.
        action : str
            Verb (e.g. ``'create'``, ``'update'``, ``'transition'``,
            ``'claim'``, ``'assign'``, ``'comment'``, ``'link'``).
        actor : Actor
            Authenticated principal.
        diff : dict, optional
            Free-form ``{"before": ..., "after": ...}`` payload. Defaults to
            ``{}``.
        correlation_id : str
            OTel trace_id (or any caller-provided correlation token). Empty
            string is allowed and used when no trace context exists.

        Returns
        -------
        AuditLogEvent
            The persisted row (post-flush so ``id`` and ``created_at`` are set).
        """
        if not entity_type:
            raise ValueError("entity_type is required")
        if not action:
            raise ValueError("action is required")

        row = AuditLogEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor.id,
            actor_type=actor.type.value if hasattr(actor.type, "value") else str(actor.type),
            diff=dict(diff or {}),
            correlation_id=correlation_id or "",
        )
        session.add(row)
        await session.flush([row])
        return row
