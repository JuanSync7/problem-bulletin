"""v2.1-WP7 — Integration tests for ``GET /api/v1/tickets/{id}/transitions``.

Covers the transitions-only default, the ``?include=comments,links``
merged-feed expansion, invalid-include validation, offset pagination and
auth-handler parity with the rest of the tickets router.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import get_db
from app.enums import ActorType
from app.services.context import Actor
from tests.helpers.app_factory import build_test_app


def _build_app(db_session, *, actor: Actor):
    async def _override_db():
        yield db_session

    from app.middleware.bearer_auth import get_actor as _ga
    return build_test_app(
        dependency_overrides={get_db: _override_db, _ga: lambda: actor}
    )


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def user_in_db(db):
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": uid, "e": f"u-{uid}@x.test"},
    )
    await db.flush()
    return Actor(id=uid, type=ActorType.user, label="u", scopes=())


@pytest.mark.asyncio
async def test_empty_include_returns_transitions_only_desc(db, user_in_db):
    """Default response: only kind='transition' rows, newest first."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "in_progress"},
        )
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "in_review"},
        )
        await c.post(
            f"/api/v1/tickets/{t['id']}/comments", json={"body": "hi"}
        )
        resp = await c.get(f"/api/v1/tickets/{t['id']}/transitions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {item["kind"] for item in body["items"]} == {"transition"}
    # 1 implicit create transition + 2 explicit transitions = 3.
    assert body["total"] == 3
    # All explicit-transition target statuses are present (ordering inside
    # a single test transaction may collapse because ``now()`` is constant
    # within a Postgres TX — sort then ties on id (UUID).
    statuses = {item["to_status"] for item in body["items"]}
    assert {"todo", "in_progress", "in_review"} <= statuses
    # DESC by (created_at, id): ensure non-increasing.
    timestamps = [item["created_at"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)
    # Uniform fields present:
    for item in body["items"]:
        assert item["actor_type"] == "user"
        assert "agent_step_id" in item


@pytest.mark.asyncio
async def test_include_comments_union_sorted_desc(db, user_in_db):
    """include=comments yields transition+comment rows, desc by created_at."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "in_progress"},
        )
        await c.post(
            f"/api/v1/tickets/{t['id']}/comments", json={"body": "hello"}
        )
        resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?include=comments"
        )
    body = resp.json()
    kinds = [item["kind"] for item in body["items"]]
    assert "transition" in kinds
    assert "comment" in kinds
    # Strictly non-increasing created_at.
    timestamps = [item["created_at"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_include_comments_and_links_three_way_union(db, user_in_db):
    """include=comments,links produces a three-arm merged feed."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        a = (await c.post("/api/v1/tickets", json={"title": "A"})).json()
        b = (await c.post("/api/v1/tickets", json={"title": "B"})).json()
        await c.post(
            f"/api/v1/tickets/{a['id']}/transition",
            json={"to_status": "in_progress"},
        )
        await c.post(
            f"/api/v1/tickets/{a['id']}/comments", json={"body": "merged"}
        )
        await c.post(
            f"/api/v1/tickets/{a['id']}/links",
            json={"target_id": b["id"], "link_type": "blocks"},
        )
        resp = await c.get(
            f"/api/v1/tickets/{a['id']}/transitions?include=comments,links"
        )
    assert resp.status_code == 200
    body = resp.json()
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"transition", "comment", "link"}
    link_item = next(i for i in body["items"] if i["kind"] == "link")
    assert link_item["source_ticket_id"] == a["id"]
    assert link_item["target_ticket_id"] == b["id"]
    assert link_item["link_type"] == "blocks"


@pytest.mark.asyncio
async def test_invalid_include_value_400(db, user_in_db):
    """Unknown include value rejected with 400 validation envelope."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?include=nope"
        )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation"


@pytest.mark.asyncio
async def test_cursor_pagination_no_overlap(db, user_in_db):
    """Cursor-based pagination: second page uses next_cursor, no overlap."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "x"})).json()
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "in_progress"},
        )
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "in_review"},
        )
        await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "done"},
        )
        first_resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?limit=2"
        )
        first = first_resp.json()
        assert first_resp.status_code == 200, first_resp.text
        # 1 implicit create + 3 explicit transitions = 4 rows total (first page).
        assert first["total"] == 4
        assert len(first["items"]) == 2
        assert first["next_cursor"] is not None

        second_resp = await c.get(
            f"/api/v1/tickets/{t['id']}/transitions?limit=2&cursor={first['next_cursor']}"
        )
        second = second_resp.json()
        assert second_resp.status_code == 200
        assert len(second["items"]) == 2
        # v2.6-WP45: total is populated on every page (same predicate).
        assert second["total"] == 4
        # No overlap between pages.
        ids_p1 = {i["id"] for i in first["items"]}
        ids_p2 = {i["id"] for i in second["items"]}
        assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_transition_to_cancelled_emits_ticket_cancelled_notification(db, user_in_db):
    """v2.6-WP40: transitioning to ``cancelled`` writes a ``ticket_cancelled`` row.

    The actor (user_in_db) is also the reporter so they're excluded from
    fanout; we add a second user as assignee and assert they get the row.
    """
    from sqlalchemy import select as _select

    from app.models.ticket_notification import TicketNotification

    # Set up an assignee distinct from the actor/reporter.
    assignee_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'a')"),
        {"id": assignee_id, "e": f"a-{assignee_id}@x.test"},
    )
    await db.flush()

    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        t = (await c.post("/api/v1/tickets", json={"title": "to-cancel"})).json()
        # Assign so we have a non-actor recipient.
        await c.post(
            f"/api/v1/tickets/{t['id']}/assign",
            json={
                "assignee_id": str(assignee_id),
                "assignee_type": "user",
                "expected_version": t["version"],
            },
        )
        resp = await c.post(
            f"/api/v1/tickets/{t['id']}/transition",
            json={"to_status": "cancelled"},
        )
    assert resp.status_code in (200, 201), resp.text

    rows = list(
        (
            await db.execute(
                _select(TicketNotification).where(
                    TicketNotification.kind == "ticket_cancelled",
                    TicketNotification.target_id == uuid.UUID(t["id"]),
                )
            )
        ).scalars().all()
    )
    assert rows, "expected at least one ticket_cancelled notification"
    recipient_ids = {r.recipient_id for r in rows}
    assert assignee_id in recipient_ids, "assignee should be notified of cancellation"
    # Excerpt should match "<from> → cancelled".
    excerpts = {r.excerpt for r in rows if r.recipient_id == assignee_id}
    assert any(e and e.endswith("→ cancelled") for e in excerpts), excerpts


@pytest.mark.asyncio
async def test_unknown_ticket_returns_404(db, user_in_db):
    """Same not-found behaviour as GET /tickets/{id}."""
    app = _build_app(db, actor=user_in_db)
    async with _client(app) as c:
        resp = await c.get(
            f"/api/v1/tickets/{uuid.uuid4()}/transitions"
        )
    assert resp.status_code == 404
