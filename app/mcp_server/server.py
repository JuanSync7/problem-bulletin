"""MCP server (HTTP-SSE) exposing 10 ticket tools (Task A16 / R4).

The server is built on top of the official ``mcp`` Python SDK. We register a
``Server`` instance with ``list_tools`` + ``call_tool`` handlers that fan out
to the adapters defined in :mod:`app.mcp_server.tools`.

Authentication: every SSE connection must carry an
``Authorization: Bearer <api_key>`` header. The api_key is resolved to an
:class:`Actor` via :class:`AgentAccountService.authenticate`. The Actor is
stashed in a per-connection contextvar so tool calls can read it.

This module ships a :func:`build_mcp_app` factory that returns a Starlette
ASGI app suitable for mounting at ``/mcp`` from the main FastAPI app.
"""
from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from typing import Any, Optional

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from app.database import async_session_factory
from app.enums import ActorType
from app.exceptions import AuthError
from app.mcp_server.errors import map_exception_to_jsonrpc
from app.mcp_server.tools import TOOLS
from app.services.agent_accounts import AgentAccountService
from app.services.context import Actor, set_actor

_current_actor: ContextVar[Optional[Actor]] = ContextVar("mcp_current_actor", default=None)


async def _authenticate_request(request: Request) -> Actor:
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        raise AuthError("missing bearer")
    token = header[len("Bearer "):].strip()
    if not token:
        raise AuthError("missing bearer")
    async with async_session_factory() as session:
        svc = AgentAccountService()
        actor = await svc.authenticate(session, token)
        await session.commit()
    return actor


def _build_mcp_server() -> Server:
    server: Server = Server("agent-kanban")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=name,
                description=spec["description"],
                inputSchema=spec["schema"],
            )
            for name, spec in TOOLS.items()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None) -> list[mcp_types.TextContent]:
        spec = TOOLS.get(name)
        correlation_id = uuid.uuid4().hex
        if spec is None:
            payload = {"error": {"code": -32601, "message": "method_not_found",
                                  "data": {"correlation_id": correlation_id, "tool": name}}}
            return [mcp_types.TextContent(type="text", text=json.dumps(payload))]

        actor = _current_actor.get()
        if actor is None:
            payload = map_exception_to_jsonrpc(
                AuthError("missing actor"), correlation_id=correlation_id
            )
            return [mcp_types.TextContent(type="text", text=json.dumps(payload))]

        async with async_session_factory() as session:
            try:
                set_actor(actor)
                result = await spec["fn"](
                    session, actor,
                    correlation_id=correlation_id,
                    **(arguments or {}),
                )
                from app.events import flush_session_events, discard_session_events
                if isinstance(result, dict) and "error" in result:
                    await session.rollback()
                    discard_session_events(session)
                else:
                    await session.commit()
                    flush_session_events(session)
            except Exception as exc:  # noqa: BLE001 - uniform translation
                await session.rollback()
                from app.events import discard_session_events
                discard_session_events(session)
                result = map_exception_to_jsonrpc(exc, correlation_id=correlation_id)
        return [mcp_types.TextContent(type="text", text=json.dumps(result, default=str))]

    return server


def build_mcp_app() -> Starlette:
    """Return a Starlette ASGI app exposing ``/sse`` (HTTP-SSE transport)."""
    server = _build_mcp_server()
    transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        try:
            actor = await _authenticate_request(request)
        except AuthError:
            return JSONResponse(
                {"error": {"code": -32001, "message": "unauthorized"}},
                status_code=401,
            )
        token = _current_actor.set(actor)
        try:
            async with transport.connect_sse(
                request.scope, request.receive, request._send
            ) as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        finally:
            _current_actor.reset(token)
        return Response(status_code=204)

    async def handle_messages(request: Request):
        return await transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=handle_messages),
        ]
    )


# Re-export the tool registry so tests can call adapters directly without
# spinning up the SSE transport.
__all__ = ["build_mcp_app", "TOOLS"]
