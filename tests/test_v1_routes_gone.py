"""
v2.10-WP01 tripwire: assert that legacy v1 HTTP surface is no longer reachable.

Background
----------
Originally the v1 sunset assumed v1 routes would return 404. In practice this
codebase serves a SPA catch-all from "/", so unknown paths *under non-API roots*
return 200 with index.html. For verbs/sub-paths that don't exist under the
existing API routers, FastAPI returns 405 (method not allowed) when the path
matches a registered route with a different method, and 404 only when no
matching route at all exists.

This file pins the contract that these legacy v1 shapes/verbs are gone:

* GET  /api/problems/feed             — old "flat global feed" sub-route, replaced
                                        by the paginated /api/feed and /api/v1/tickets.
* POST /api/problems/{id}/vote        — v1 vote verb, replaced by /upstar.
* POST /api/solutions/{id}/vote       — v1 vote verb, replaced by /upvote.
* POST /api/problems/{id}/comment     — v1 singular comment endpoint, replaced
                                        by plural /comments.
* POST /api/auth/login                — v1 password login, replaced by magic-link
                                        flow under /api/auth/magic-link/*.
* POST /api/problems/bulk             — v1 bulk-create surface that never landed
                                        in v2.

A 404 OR a 405 is acceptable here: both signal "this URL+verb combo is not
served by any v1 handler". The previous implicit tripwire was 313 failing
tests; this file is the explicit replacement.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


GONE_SIGNALS = {404, 405}


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Module-scoped TestClient against the real (non-test-doubled) app."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def _fake_uuid() -> str:
    return str(uuid.uuid4())


def test_v1_problems_feed_subroute_is_gone(client: TestClient) -> None:
    """GET /api/problems/feed must not be a real handler."""
    resp = client.get("/api/problems/feed")
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 /api/problems/feed should be gone, got {resp.status_code}"
    )


def test_v1_problem_vote_verb_is_gone(client: TestClient) -> None:
    """v1 used /vote; v2 uses /upstar. /vote must not be served."""
    resp = client.post(f"/api/problems/{_fake_uuid()}/vote")
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 /problems/{{id}}/vote should be gone, got {resp.status_code}"
    )


def test_v1_solution_vote_verb_is_gone(client: TestClient) -> None:
    """v1 used /vote; v2 uses /upvote. /vote must not be served."""
    resp = client.post(f"/api/solutions/{_fake_uuid()}/vote")
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 /solutions/{{id}}/vote should be gone, got {resp.status_code}"
    )


def test_v1_singular_problem_comment_is_gone(client: TestClient) -> None:
    """v1 had POST /problems/{id}/comment (singular); v2 uses /comments."""
    resp = client.post(f"/api/problems/{_fake_uuid()}/comment")
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 singular /problems/{{id}}/comment should be gone, got {resp.status_code}"
    )


def test_v1_password_login_endpoint_is_gone(client: TestClient) -> None:
    """v1 had password login; v2 uses magic links exclusively."""
    resp = client.post("/api/auth/login", json={"email": "x@y.z", "password": "hunter2"})
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 password /auth/login should be gone, got {resp.status_code}"
    )


def test_v1_problem_bulk_create_is_gone(client: TestClient) -> None:
    """v1 envisioned /problems/bulk; v2 never shipped it."""
    resp = client.post("/api/problems/bulk", json={})
    assert resp.status_code in GONE_SIGNALS, (
        f"v1 /problems/bulk should be gone, got {resp.status_code}"
    )
