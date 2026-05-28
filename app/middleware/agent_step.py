"""AgentStepMiddleware — plumb ``X-Agent-Step-Id`` into the service layer.

Per Ticketing v2 spec §6 (Agent Attribution Model). Every audit-row writer
in `app.services.tickets` reads `app.services.context.get_agent_step_id()`
to stamp `agent_step_id` on `ticket_transitions`, `ticket_comments`,
`ticket_links`, `ticket_attachments`, and `tickets.created_agent_step_id`.

The middleware is intentionally tiny: read the header, set the contextvar
for the request scope, reset on exit. The CHECK constraints on each table
defend against the case where a user-actor request carries the header by
accident — service layer is responsible for never writing the step id
when actor is a user.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.services.context import (
    reset_agent_step_id,
    set_agent_step_id,
)


HEADER_NAME = "X-Agent-Step-Id"


class AgentStepMiddleware(BaseHTTPMiddleware):
    """Bind ``X-Agent-Step-Id`` header to the agent_step_id contextvar."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get(HEADER_NAME)
        step_id = raw.strip() if raw else None
        token = set_agent_step_id(step_id or None)
        try:
            response = await call_next(request)
        finally:
            reset_agent_step_id(token)
        return response
