"""MCP-driven end-to-end demo (G3 primary).

Connects a Python MCP client to the running server's SSE transport at
``http://localhost:28080/mcp/sse`` and walks an Epic + 3 Stories scenario,
then claims, transitions, comments, links, lists and searches.

Setup
-----
1. Bring up Postgres + Jaeger::

       docker compose up -d postgres jaeger

2. Apply migrations::

       alembic upgrade head

3. Create an agent account and copy the printed api_key::

       python scripts/create_agent_account.py --name demo-agent \\
           --scope tickets:read --scope tickets:write
       export PB_DEMO_AGENT_KEY=<api_key>

4. Start the API::

       uvicorn app.main:app --reload

5. Run this script::

       python scripts/agent_demo.py

6. Open Jaeger at http://localhost:16686 to see the spans, and the
   kanban board at http://localhost:28173/board (or :28080/board in
   single-server prod mode) to watch the tickets light up.

Notes
-----
* If the SSE transport is unavailable (e.g. CI), use
  ``scripts/agent_demo_direct.py`` — same scenario, no network.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Any

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
except Exception as exc:  # pragma: no cover
    print(
        "MCP SDK not available. Install `mcp` or use scripts/agent_demo_direct.py.\n"
        f"Underlying error: {exc}",
        file=sys.stderr,
    )
    sys.exit(2)


MCP_URL = os.getenv("PB_DEMO_MCP_URL", "http://localhost:28080/mcp/sse")


def _api_key() -> str:
    k = os.getenv("PB_DEMO_AGENT_KEY")
    if not k:
        print(
            "PB_DEMO_AGENT_KEY is not set. Create one via:\n"
            "  python scripts/create_agent_account.py --name demo-agent "
            "--scope tickets:read --scope tickets:write",
            file=sys.stderr,
        )
        sys.exit(1)
    return k


def _extract(result) -> dict[str, Any]:
    """Pull the JSON dict out of an MCP TextContent reply."""
    if not result or not result.content:
        return {}
    text = result.content[0].text if hasattr(result.content[0], "text") else ""
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


async def _call(session: ClientSession, tool: str, **args: Any) -> dict[str, Any]:
    result = await session.call_tool(tool, args)
    payload = _extract(result)
    corr = payload.get("correlation_id") or payload.get("error", {}).get("data", {}).get("correlation_id")
    print(f"\n>> {tool}  corr={corr}")
    print(json.dumps(payload, indent=2, default=str))
    return payload


async def _main() -> int:
    headers = {"Authorization": f"Bearer {_api_key()}"}
    print(f"[connect] {MCP_URL}")
    async with sse_client(MCP_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"[connect] {len(tools.tools)} tools advertised")

            epic = await _call(
                session, "create_ticket",
                title="Build login page",
                description="OAuth + email/password sign-in for the kanban demo.",
                ticket_type="epic", priority="high",
                labels=["auth", "demo"],
            )
            epic_id = epic.get("id")
            if not epic_id:
                return 1

            stories = []
            for title in [
                "Wire OAuth provider",
                "Add login form UI",
                "Persist sessions",
            ]:
                s = await _call(
                    session, "create_ticket",
                    title=title,
                    ticket_type="story", priority="medium",
                    parent_id=epic_id,
                    labels=["auth"],
                )
                stories.append(s)

            first_id = stories[0]["id"]
            second_id = stories[1]["id"]

            await _call(session, "claim", id_or_key=first_id)
            await _call(session, "update_status", id_or_key=first_id,
                        to_status="in_progress", reason="starting work")
            await _call(session, "update_status", id_or_key=first_id,
                        to_status="in_review", reason="ready for review")
            await _call(session, "update_status", id_or_key=first_id,
                        to_status="done", reason="merged")
            await _call(session, "add_comment", id_or_key=first_id,
                        body="Progress: OAuth wired against the demo provider.")
            await _call(session, "link_tickets",
                        source=first_id, target=second_id, link_type="relates")
            await _call(session, "list_my_tickets", limit=20)
            await _call(session, "search_tickets", query="login", limit=20)

    print("\n[demo] done.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_main()))
