"""Common Pydantic schemas (v2.1-WP10).

Defines the generic ``Page[T]`` envelope used across paginated list
endpoints. Pydantic v2 supports generic models via ``BaseModel`` with a
``TypeVar``; no separate ``GenericModel`` import is needed.

Wire shape::

    {
        "items":       [...],
        "next_cursor": "<opaque base64 string>" | null,
        "total":       <int> | null,
    }

``next_cursor=None`` indicates the final page. ``total`` is OPTIONAL —
endpoints set it only when computing it is cheap (e.g. for a Kanban view
already scoped by ``project_id``); otherwise they return ``null`` and the
client treats the count as unknown.

The cursor is intentionally opaque. v2.1-WP10 uses base64(JSON) encoding
of ``(created_at_iso, id_uuid)`` for keyset pagination over
``ORDER BY created_at DESC, id DESC``. See ``app.services.tickets``
helpers ``_encode_cursor`` / ``_decode_cursor`` for the implementation.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Generic paginated envelope. See module docstring."""

    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


# v2.1-WP11: ticket-specific extension that surfaces per-status counts for
# WIP-limit display on the Kanban board. Kept as a subclass (rather than
# widening Page[T]) so the generic envelope stays clean — only the tickets
# endpoint needs ``column_counts``.
class TicketsPage(Page[dict]):
    """``Page[TicketRead]`` plus a ``column_counts`` aggregate.

    ``column_counts`` is a mapping of ``TicketStatus.value`` -> int. It is
    populated only when the request scopes by ``project_id`` (same cost
    trade-off as ``total``): a single ``GROUP BY status`` query is cheap on
    a project-scoped WHERE and would scan the entire ``tickets`` table on
    an org-wide listing. All seven workflow statuses are always present
    (even with count 0) so the UI never sees a missing key.
    """

    column_counts: dict[str, int] | None = None
