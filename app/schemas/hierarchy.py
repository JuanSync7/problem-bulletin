"""B1 — Pydantic schemas for project hierarchy endpoint.

``HierarchyRow`` wraps a ``TicketRead`` with depth + parent_id + ordinal
metadata produced by the WITH RECURSIVE CTE.
``ProjectHierarchyResponse`` is the envelope returned by
``GET /api/v1/projects/{project_id}/hierarchy``.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.schemas.tickets import TicketRead


class HierarchyRow(BaseModel):
    """One node in the project hierarchy tree.

    Fields
    ------
    ticket   : full TicketRead wire shape.
    depth    : 0-based depth from the project root (parent_id IS NULL).
    parent_id: UUID of the parent ticket, or null for root-level tickets.
    ordinal  : seq_number from the ticket — used for stable ordering within
               a depth level (ascending).
    """

    ticket: TicketRead
    depth: int
    parent_id: UUID | None
    ordinal: int


class ProjectHierarchyResponse(BaseModel):
    """Response envelope for ``GET /api/v1/projects/{project_id}/hierarchy``."""

    items: list[HierarchyRow]
