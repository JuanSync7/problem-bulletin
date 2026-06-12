"""V3a: GET /api/v1/me/inbox aggregates the four "My Space" tabs.

Seeds:
- alice: 2 tickets assigned, 1 mention (ticket_notifications kind=ticket_mention),
  1 done agent_run whose agent.created_by == alice.
- bob: 1 ticket assigned. (Not the caller; bob's data must NOT leak into
  alice's inbox.)

Assertions:
- counts.assigned_tickets == 2
- counts.assigned_problems matches seed (0 because Problem has no
  assignee_id; service falls back to "authored by me" which is 0 here).
- counts.mentions == 1
- counts.my_agent_runs == 1
- ids in each page match the seeded ids.

Decision note: Problem has no ``assignee_id`` column. The service treats
``assigned_problems`` as problems the user authored (semantic fallback).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.middleware.bearer_auth import get_actor as _get_actor
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app
from tests.helpers.seed_agent_account import seed_agent_account, seed_user


pytestmark = pytest.mark.asyncio


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _build_app(db_session, *, actor: Actor):
    async def _override_db():
        yield db_session

    overrides: dict = {get_db: _override_db, _get_actor: lambda: actor}
    return build_test_app(dependency_overrides=overrides)


async def _seed_project(db) -> tuple[uuid.UUID, str]:
    proj_id = uuid.uuid4()
    proj_key = f"V3A{uuid.uuid4().hex[:3].upper()}"
    await db.execute(
        text("INSERT INTO projects (id, key, name) VALUES (:id, :k, :n)"),
        {"id": proj_id, "k": proj_key, "n": "V3a me inbox"},
    )
    return proj_id, proj_key


async def _seed_ticket(
    db,
    *,
    project_id: uuid.UUID,
    project_key: str,
    reporter_id: uuid.UUID,
    assignee_id: uuid.UUID | None = None,
    assignee_type: str | None = None,
    title: str = "Seed ticket",
) -> uuid.UUID:
    tid = uuid.uuid4()
    seq = abs(hash(tid)) % 99_000 + 1000
    await db.execute(
        text(
            "INSERT INTO tickets "
            "(id, seq_number, display_id, title, description, project_id, "
            " reporter_id, reporter_type, type, status, priority, version, "
            " assignee_id, assignee_type, "
            " labels, fix_versions, custom_fields) "
            "VALUES (:id, :seq, :did, :t, :desc, :p, :r, 'user', 'task', "
            "        'todo', 'medium', 1, :ai, :at, '{}', '{}', '{}')"
        ),
        {
            "id": tid,
            "seq": seq,
            "did": f"{project_key}-{seq}",
            "t": title,
            "desc": "body",
            "p": project_id,
            "r": reporter_id,
            "ai": assignee_id,
            "at": assignee_type,
        },
    )
    return tid


@pytest_asyncio.fixture
async def fixture(db):
    alice_id = await seed_user(
        db,
        email=f"alice-{uuid.uuid4().hex[:6]}@x.test",
        display_name="Alice",
    )
    bob_id = await seed_user(
        db,
        email=f"bob-{uuid.uuid4().hex[:6]}@x.test",
        display_name="Bob",
    )

    proj_id, proj_key = await _seed_project(db)

    # Two tickets assigned to alice.
    t1 = await _seed_ticket(
        db,
        project_id=proj_id,
        project_key=proj_key,
        reporter_id=bob_id,
        assignee_id=alice_id,
        assignee_type="user",
        title="alice ticket A",
    )
    t2 = await _seed_ticket(
        db,
        project_id=proj_id,
        project_key=proj_key,
        reporter_id=bob_id,
        assignee_id=alice_id,
        assignee_type="user",
        title="alice ticket B",
    )

    # One ticket assigned to bob — must NOT appear for alice.
    _bob_ticket = await _seed_ticket(
        db,
        project_id=proj_id,
        project_key=proj_key,
        reporter_id=alice_id,
        assignee_id=bob_id,
        assignee_type="user",
        title="bob ticket",
    )

    # One mention notification addressed to alice.
    notif_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO ticket_notifications "
            "(id, kind, recipient_type, recipient_id, actor_type, actor_id, "
            " target_type, target_id, target_display_id, excerpt, is_read) "
            "VALUES (:id, 'ticket_mention', 'user', :rid, 'user', :aid, "
            "        'ticket', :tid, :did, 'hello @alice', false)"
        ),
        {
            "id": notif_id,
            "rid": alice_id,
            "aid": bob_id,
            "tid": t1,
            "did": f"{proj_key}-001",
        },
    )

    # One agent owned by alice + one done agent_run on that agent.
    agent_id = await seed_agent_account(
        db,
        name=f"alice-coder-{uuid.uuid4().hex[:6]}",
        handle=f"alice_coder_{uuid.uuid4().hex[:6]}",
        created_by=alice_id,
    )
    run_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_run "
            "(id, agent_id, ticket_id, status, prompt, idempotency_key, "
            " response_body, started_at, finished_at) "
            "VALUES (:id, :a, :t, 'done', 'do thing', :k, "
            "        'ok', now(), now())"
        ),
        {
            "id": run_id,
            "a": agent_id,
            "t": t1,
            "k": f"k-{run_id.hex[:16]}",
        },
    )

    # An agent_run on an agent NOT owned by alice — must NOT leak.
    other_agent = await seed_agent_account(
        db,
        name=f"other-{uuid.uuid4().hex[:6]}",
        handle=f"other_{uuid.uuid4().hex[:6]}",
        created_by=bob_id,
    )
    other_run = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO agent_run "
            "(id, agent_id, ticket_id, status, prompt, idempotency_key) "
            "VALUES (:id, :a, :t, 'done', 'x', :k)"
        ),
        {
            "id": other_run,
            "a": other_agent,
            "t": t2,
            "k": f"k-{other_run.hex[:16]}",
        },
    )

    await db.flush()

    actor = Actor(id=alice_id, type=ActorType.user, label="alice", scopes=())
    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "ticket_ids": {t1, t2},
        "notif_id": notif_id,
        "run_id": run_id,
        "agent_id": agent_id,
        "actor": actor,
    }


async def test_me_inbox_returns_correct_counts_and_ids(db, fixture):
    actor = fixture["actor"]
    app = _build_app(db, actor=actor)
    async with _client(app) as c:
        resp = await c.get("/api/v1/me/inbox")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    counts = body["counts"]
    assert counts["assigned_tickets"] == 2
    # Problem has no assignee_id; service falls back to "authored by me".
    # Alice did not author any problems in this fixture.
    assert counts["assigned_problems"] == 0
    assert counts["mentions"] == 1
    assert counts["my_agent_runs"] == 1

    # ids check
    assigned_ids = {it["id"] for it in body["assigned_tickets"]["items"]}
    assert assigned_ids == {str(t) for t in fixture["ticket_ids"]}

    mention_ids = {it["id"] for it in body["mentions"]["items"]}
    assert mention_ids == {str(fixture["notif_id"])}

    run_ids = {it["id"] for it in body["my_agent_runs"]["items"]}
    assert run_ids == {str(fixture["run_id"])}
