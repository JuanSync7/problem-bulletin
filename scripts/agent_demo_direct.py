"""In-process MCP demo (G3 fallback).

Runs the same scenario as ``agent_demo.py`` but calls the MCP tool
adapters directly (no SSE transport, no uvicorn). Use this in CI or any
context where spinning up the network stack is brittle.

Scenario
--------
1. Create an Epic "Build login page".
2. Create 3 Story subtasks (parent_id=epic).
3. Claim the first Story.
4. Transition it todo -> in_progress -> in_review -> done.
5. Add a progress comment.
6. Link Story #1 to Story #2 (link_type=related).
7. list_my_tickets.
8. search_tickets("login").

Each step's result (or error envelope) is printed with its correlation_id.

Requirements
------------
- DATABASE_URL must point at a running Postgres with the agent-kanban
  migrations applied.
- An agent account is created on the fly (named ``demo-direct-<rand>``)
  so we have an Actor with agent scopes.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys
import uuid
from typing import Any

from app.database import async_session_factory
from app.enums import ActorType
from app.events import discard_session_events, flush_session_events
from app.mcp_server.tools import TOOLS
from app.services.agent_accounts import AgentAccountService
from app.services.context import Actor


async def _bootstrap_actor() -> Actor:
    """Create a throwaway agent account and return its Actor."""
    svc = AgentAccountService()
    name = f"demo-direct-{secrets.token_hex(4)}"
    async with async_session_factory() as session:
        account, plaintext = await svc.create_account(
            session,
            name=name,
            scopes=["tickets:read", "tickets:write"],
            description="agent_demo_direct.py throwaway",
        )
        await session.commit()
    print(f"[bootstrap] created agent account {name} (id={account.id})")
    return Actor(
        id=account.id,
        type=ActorType.agent,
        label=account.name,
        scopes=tuple(account.scopes or ()),
    )


async def _call(tool_name: str, *, actor: Actor, **kwargs: Any) -> dict[str, Any]:
    """Invoke an MCP tool exactly like the server would, including TX boundary."""
    spec = TOOLS[tool_name]
    correlation_id = uuid.uuid4().hex
    async with async_session_factory() as session:
        try:
            result = await spec["fn"](
                session, actor, correlation_id=correlation_id, **kwargs
            )
            if isinstance(result, dict) and "error" in result:
                await session.rollback()
                discard_session_events(session)
            else:
                await session.commit()
                flush_session_events(session)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            discard_session_events(session)
            result = {"error": {"message": str(exc), "type": type(exc).__name__,
                                  "correlation_id": correlation_id}}
    print(f"\n>> {tool_name}  corr={correlation_id}")
    print(json.dumps(result, indent=2, default=str))
    return result


async def _main() -> int:
    actor = await _bootstrap_actor()

    # Step 1: Epic
    epic = await _call(
        "create_ticket", actor=actor,
        title="Build login page",
        description="OAuth + email/password sign-in for the kanban demo.",
        ticket_type="epic",
        priority="high",
        labels=["auth", "demo"],
    )
    epic_id = epic.get("id")
    if not epic_id:
        print("Aborting: epic creation failed", file=sys.stderr)
        return 1

    # Step 2: 3 Story subtasks
    stories = []
    for title in [
        "Wire OAuth provider",
        "Add login form UI",
        "Persist sessions",
    ]:
        s = await _call(
            "create_ticket", actor=actor,
            title=title,
            description=f"Subtask of login epic: {title}",
            ticket_type="story",
            priority="medium",
            parent_id=epic_id,
            labels=["auth"],
        )
        stories.append(s)

    first_id = stories[0]["id"]
    second_id = stories[1]["id"]

    # Step 3: claim first story
    await _call("claim", actor=actor, id_or_key=first_id)

    # Step 4: transitions
    await _call("update_status", actor=actor, id_or_key=first_id,
                to_status="in_progress", reason="starting work")
    await _call("update_status", actor=actor, id_or_key=first_id,
                to_status="in_review", reason="ready for review")
    await _call("update_status", actor=actor, id_or_key=first_id,
                to_status="done", reason="merged")

    # Step 5: comment
    await _call("add_comment", actor=actor, id_or_key=first_id,
                body="Progress: OAuth wired against the demo provider.")

    # Step 6: link first->second
    await _call("link_tickets", actor=actor,
                source=first_id, target=second_id, link_type="relates")

    # Step 7: list my tickets
    await _call("list_my_tickets", actor=actor, limit=20)

    # Step 8: search
    await _call("search_tickets", actor=actor, query="login", limit=20)

    print("\n[demo] done.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_main()))
