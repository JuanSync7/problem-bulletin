"""MCP tool adapters (Task A16 / R4).

Each adapter:
    1. Authenticates via the supplied :class:`Actor` (obtained by the server
       from a Bearer api_key header).
    2. Resolves a service-layer method on :class:`TicketService`.
    3. Catches domain exceptions and returns a JSON-RPC error dict via
       :func:`app.mcp_server.errors.map_exception_to_jsonrpc`.

Adapters are pure async functions that take an :class:`AsyncSession`, an
:class:`Actor`, and arguments. They return either a success ``dict`` or an
error envelope ``{"error": {...}}``.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import TicketLinkType, TicketPriority, TicketStatus, TicketType
from app.mcp_server.errors import map_exception_to_jsonrpc
from app.services.context import Actor
from app.services.tickets import TicketService


def _resolve(id_or_key: str) -> UUID | str:
    try:
        return UUID(id_or_key)
    except (ValueError, AttributeError, TypeError):
        return id_or_key


async def _safely(coro, *, correlation_id: str) -> dict[str, Any]:
    try:
        result = await coro
        return result
    except Exception as exc:  # noqa: BLE001 - we translate uniformly
        return map_exception_to_jsonrpc(exc, correlation_id=correlation_id)


async def create_ticket(
    db: AsyncSession,
    actor: Actor,
    *,
    title: str,
    description: Optional[str] = None,
    ticket_type: str = "task",
    priority: str = "medium",
    parent_id: Optional[str] = None,
    labels: Optional[list[str]] = None,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        ticket = await svc.create(
            db,
            actor=actor,
            title=title,
            description=description,
            ticket_type=TicketType(ticket_type),
            priority=TicketPriority(priority),
            parent_id=UUID(parent_id) if parent_id else None,
            labels=labels or [],
            correlation_id=correlation_id,
        )
        return {
            "ticket_key": ticket.key,
            "id": str(ticket.id),
            "version": ticket.version,
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


async def get_ticket(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        ticket = await svc.get(db, _resolve(id_or_key))
        return {"ticket": ticket.to_dict(), "correlation_id": correlation_id}

    return await _safely(_do(), correlation_id=correlation_id)


async def update_status(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    to_status: str,
    reason: Optional[str] = None,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        ticket = await svc.transition(
            db,
            _resolve(id_or_key),
            actor=actor,
            target_status=TicketStatus(to_status),
            reason=reason,
            correlation_id=correlation_id,
        )
        return {
            "ticket_key": ticket.key,
            "status": ticket.status.value,
            "version": ticket.version,
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


async def transition(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    to_status: str,
    reason: Optional[str] = None,
    correlation_id: str = "",
) -> dict[str, Any]:
    return await update_status(
        db,
        actor,
        id_or_key=id_or_key,
        to_status=to_status,
        reason=reason,
        correlation_id=correlation_id,
    )


async def list_my_tickets(
    db: AsyncSession,
    actor: Actor,
    *,
    status: Optional[list[str]] = None,
    limit: int = 50,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        rows = await svc.list(
            db,
            assignee_id=actor.id,
            status=status,
            limit=limit,
        )
        return {
            "items": [t.to_dict() for t in rows],
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


async def assign(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    assignee_id: str,
    assignee_type: str = "agent",
    expected_version: int,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        ticket = await svc.assign(
            db,
            _resolve(id_or_key),
            actor=actor,
            assignee_id=UUID(assignee_id),
            assignee_type=assignee_type,
            expected_version=expected_version,
            correlation_id=correlation_id,
        )
        return {
            "ticket_key": ticket.key,
            "assignee_id": str(ticket.assignee_id),
            "assignee_type": ticket.assignee_type,
            "version": ticket.version,
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


async def claim(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        ticket = await svc.claim(
            db, _resolve(id_or_key), actor=actor, correlation_id=correlation_id
        )
        return {
            "ticket_key": ticket.key,
            "assignee_id": str(ticket.assignee_id),
            "version": ticket.version,
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


async def add_comment(
    db: AsyncSession,
    actor: Actor,
    *,
    id_or_key: str,
    body: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        comment = await svc.add_comment(
            db,
            _resolve(id_or_key),
            actor=actor,
            body=body,
            correlation_id=correlation_id,
        )
        return {"comment_id": str(comment.id), "correlation_id": correlation_id}

    return await _safely(_do(), correlation_id=correlation_id)


async def link_tickets(
    db: AsyncSession,
    actor: Actor,
    *,
    source: str,
    target: str,
    link_type: str,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        src = await svc.get(db, _resolve(source))
        tgt = await svc.get(db, _resolve(target))
        link = await svc.link(
            db,
            actor=actor,
            source_id=src.id,
            target_id=tgt.id,
            link_type=TicketLinkType(link_type),
            correlation_id=correlation_id,
        )
        return {"link_id": str(link.id), "correlation_id": correlation_id}

    return await _safely(_do(), correlation_id=correlation_id)


async def search_tickets(
    db: AsyncSession,
    actor: Actor,
    *,
    query: Optional[str] = None,
    limit: int = 50,
    correlation_id: str = "",
) -> dict[str, Any]:
    svc = TicketService()

    async def _do():
        rows = await svc.search(db, query=query, limit=limit)
        return {
            "items": [t.to_dict() for t in rows],
            "correlation_id": correlation_id,
        }

    return await _safely(_do(), correlation_id=correlation_id)


# Public registry consumed by the MCP server runtime + tests.
TOOLS: dict[str, dict[str, Any]] = {
    "create_ticket": {
        "fn": create_ticket,
        "description": "Create a new ticket. Returns ticket_key + id + version.",
        "schema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "ticket_type": {"type": "string", "enum": [e.value for e in TicketType]},
                "priority": {"type": "string", "enum": [e.value for e in TicketPriority]},
                "parent_id": {"type": ["string", "null"]},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "get_ticket": {
        "fn": get_ticket,
        "description": "Retrieve a ticket by UUID or TKT-N key.",
        "schema": {
            "type": "object",
            "required": ["id_or_key"],
            "properties": {"id_or_key": {"type": "string"}},
        },
    },
    "update_status": {
        "fn": update_status,
        "description": "Transition a ticket to the given status.",
        "schema": {
            "type": "object",
            "required": ["id_or_key", "to_status"],
            "properties": {
                "id_or_key": {"type": "string"},
                "to_status": {"type": "string", "enum": [e.value for e in TicketStatus]},
                "reason": {"type": ["string", "null"]},
            },
        },
    },
    "transition": {
        "fn": transition,
        "description": "Alias of update_status (FR-compatible).",
        "schema": {
            "type": "object",
            "required": ["id_or_key", "to_status"],
            "properties": {
                "id_or_key": {"type": "string"},
                "to_status": {"type": "string", "enum": [e.value for e in TicketStatus]},
                "reason": {"type": ["string", "null"]},
            },
        },
    },
    "list_my_tickets": {
        "fn": list_my_tickets,
        "description": "List tickets assigned to the calling agent.",
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
    "assign": {
        "fn": assign,
        "description": "Assign a ticket to a user/agent (OCC-protected).",
        "schema": {
            "type": "object",
            "required": ["id_or_key", "assignee_id", "expected_version"],
            "properties": {
                "id_or_key": {"type": "string"},
                "assignee_id": {"type": "string"},
                "assignee_type": {"type": "string", "enum": ["user", "agent"]},
                "expected_version": {"type": "integer"},
            },
        },
    },
    "claim": {
        "fn": claim,
        "description": "Atomic unassigned-only claim (agent-only).",
        "schema": {
            "type": "object",
            "required": ["id_or_key"],
            "properties": {"id_or_key": {"type": "string"}},
        },
    },
    "add_comment": {
        "fn": add_comment,
        "description": "Append a comment to a ticket.",
        "schema": {
            "type": "object",
            "required": ["id_or_key", "body"],
            "properties": {
                "id_or_key": {"type": "string"},
                "body": {"type": "string", "minLength": 1},
            },
        },
    },
    "link_tickets": {
        "fn": link_tickets,
        "description": "Create a directional ticket link.",
        "schema": {
            "type": "object",
            "required": ["source", "target", "link_type"],
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "link_type": {
                    "type": "string",
                    "enum": [e.value for e in TicketLinkType],
                },
            },
        },
    },
    "search_tickets": {
        "fn": search_tickets,
        "description": "Full-text search across tickets.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
}
