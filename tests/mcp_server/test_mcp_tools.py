"""Direct-handler tests for the MCP tool adapters (Task R4).

We call the adapter functions on TOOLS[name]["fn"] directly with the test
session + Actor, avoiding the SSE transport (which would require running an
event-loop server). Coverage exercises happy paths and the JSON-RPC error
mapping (not_found, conflict, already_claimed, link_exists,
invalid_transition).
"""
from __future__ import annotations

import uuid

import pytest

from app.enums import ActorType
from app.mcp_server.errors import map_exception_to_jsonrpc
from app.mcp_server.tools import TOOLS
from app.exceptions import (
    AlreadyClaimedError,
    OptimisticConcurrencyError,
    TicketNotFoundError,
    ValidationError,
)
from app.services.context import Actor


def _agent() -> Actor:
    return Actor(
        id=uuid.uuid4(),
        type=ActorType.agent,
        label="bot",
        scopes=("tickets:write",),
    )


# ---------------------------------------------------------------------------
# error mapper (pure-function tests)
# ---------------------------------------------------------------------------

def test_error_mapper_not_found():
    res = map_exception_to_jsonrpc(TicketNotFoundError("nope"), correlation_id="abc")
    assert res["error"]["code"] == -32003
    assert res["error"]["data"]["correlation_id"] == "abc"


def test_error_mapper_occ_includes_current_version():
    res = map_exception_to_jsonrpc(
        OptimisticConcurrencyError(current_version=7, current={"id": "x"}),
    )
    assert res["error"]["code"] == -32004
    assert res["error"]["data"]["current_version"] == 7


def test_error_mapper_already_claimed():
    aid = uuid.uuid4()
    res = map_exception_to_jsonrpc(AlreadyClaimedError(current_assignee_id=aid))
    assert res["error"]["code"] == -32010
    assert res["error"]["data"]["current_assignee_id"] == str(aid)


def test_error_mapper_validation():
    res = map_exception_to_jsonrpc(
        ValidationError([{"name": "title", "reason": "required"}])
    )
    assert res["error"]["code"] == -32602
    assert res["error"]["data"]["fields"] == [{"name": "title", "reason": "required"}]


def test_error_mapper_unknown_becomes_internal():
    res = map_exception_to_jsonrpc(RuntimeError("boom"))
    assert res["error"]["code"] == -32603


# ---------------------------------------------------------------------------
# adapter integration tests (live db)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_registry_has_all_ten():
    expected = {
        "create_ticket", "get_ticket", "update_status", "transition",
        "list_my_tickets", "assign", "claim", "add_comment",
        "link_tickets", "search_tickets",
    }
    assert expected.issubset(set(TOOLS.keys()))
    for spec in TOOLS.values():
        assert callable(spec["fn"])
        assert "description" in spec and "schema" in spec


@pytest.mark.asyncio
async def test_create_ticket_returns_key_and_id(db):
    actor = _agent()
    res = await TOOLS["create_ticket"]["fn"](
        db, actor, title="from mcp", labels=["a"], correlation_id="cor1"
    )
    assert "ticket_key" in res
    assert "id" in res
    assert res["version"] == 1
    assert res["correlation_id"] == "cor1"


@pytest.mark.asyncio
async def test_get_ticket_happy(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](
        db, actor, title="g", correlation_id=""
    )
    res = await TOOLS["get_ticket"]["fn"](
        db, actor, id_or_key=created["id"], correlation_id=""
    )
    assert res["ticket"]["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_ticket_not_found_returns_jsonrpc_error(db):
    actor = _agent()
    res = await TOOLS["get_ticket"]["fn"](
        db, actor, id_or_key=str(uuid.uuid4()), correlation_id=""
    )
    assert "error" in res
    assert res["error"]["code"] == -32003


@pytest.mark.asyncio
async def test_update_status_transition(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor, title="t", correlation_id="")
    res = await TOOLS["update_status"]["fn"](
        db, actor, id_or_key=created["id"], to_status="in_progress",
        reason="going", correlation_id="",
    )
    assert res["status"] == "in_progress"
    assert res["version"] == 2


@pytest.mark.asyncio
async def test_transition_invalid_returns_error(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor, title="x", correlation_id="")
    res = await TOOLS["transition"]["fn"](
        db, actor, id_or_key=created["id"], to_status="done", correlation_id=""
    )
    assert res["error"]["code"] == -32012


@pytest.mark.asyncio
async def test_claim_and_already_claimed(db):
    actor1 = _agent()
    actor2 = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor1, title="c", correlation_id="")
    ok = await TOOLS["claim"]["fn"](db, actor1, id_or_key=created["id"], correlation_id="")
    assert ok["assignee_id"] == str(actor1.id)
    again = await TOOLS["claim"]["fn"](db, actor2, id_or_key=created["id"], correlation_id="")
    assert again["error"]["code"] == -32010


@pytest.mark.asyncio
async def test_assign_with_version(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor, title="a", correlation_id="")
    target = uuid.uuid4()
    res = await TOOLS["assign"]["fn"](
        db, actor,
        id_or_key=created["id"],
        assignee_id=str(target),
        assignee_type="agent",
        expected_version=1,
        correlation_id="",
    )
    assert res["assignee_id"] == str(target)
    assert res["version"] == 2


@pytest.mark.asyncio
async def test_list_my_tickets_filters_by_actor(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor, title="mine", correlation_id="")
    await TOOLS["claim"]["fn"](db, actor, id_or_key=created["id"], correlation_id="")
    res = await TOOLS["list_my_tickets"]["fn"](db, actor, correlation_id="")
    titles = [t["title"] for t in res["items"]]
    assert "mine" in titles


@pytest.mark.asyncio
async def test_add_comment(db):
    actor = _agent()
    created = await TOOLS["create_ticket"]["fn"](db, actor, title="cm", correlation_id="")
    res = await TOOLS["add_comment"]["fn"](
        db, actor, id_or_key=created["id"], body="hello", correlation_id=""
    )
    assert "comment_id" in res


@pytest.mark.asyncio
async def test_link_tickets_and_duplicate(db):
    actor = _agent()
    a = await TOOLS["create_ticket"]["fn"](db, actor, title="A", correlation_id="")
    b = await TOOLS["create_ticket"]["fn"](db, actor, title="B", correlation_id="")
    ok = await TOOLS["link_tickets"]["fn"](
        db, actor, source=a["id"], target=b["id"], link_type="relates", correlation_id=""
    )
    assert "link_id" in ok
    dup = await TOOLS["link_tickets"]["fn"](
        db, actor, source=a["id"], target=b["id"], link_type="relates", correlation_id=""
    )
    assert dup["error"]["code"] == -32011


@pytest.mark.asyncio
async def test_search_tickets(db):
    actor = _agent()
    await TOOLS["create_ticket"]["fn"](db, actor, title="bananarama", correlation_id="")
    res = await TOOLS["search_tickets"]["fn"](db, actor, query="bananarama", correlation_id="")
    assert any("bananarama" in t["title"] for t in res["items"])


@pytest.mark.asyncio
async def test_create_ticket_validation_blank_title(db):
    actor = _agent()
    res = await TOOLS["create_ticket"]["fn"](db, actor, title="", correlation_id="")
    assert res["error"]["code"] == -32602
