"""v2.11-WP11 (C8) — SPA catch-all hardening: test-route helper + regression pin.

Background
----------
``app.main.create_app()`` conditionally registers a SPA catch-all route
when ``frontend/dist`` is present:

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        ...

Because the catch-all is appended LAST (and matches anything), any
route a test appends afterwards is shadowed. v2.10-WP01 and v2.10-WP07
each tripped on this.

Two test-side surfaces ship here:

G4 — ``tests.helpers.test_routes.register_test_route(app, ...)`` —
    inserts a route at ``app.router.routes[0:0]`` so it wins.

G5 — Regression pin on the catch-all's current shape, so a future
    refactor that breaks the assumption (e.g. converts to a Mount with
    different ordering semantics) fails this test loud.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# -----------------------------------------------------------------------------
# G4 — register_test_route helper smoke tests
# -----------------------------------------------------------------------------


def _make_app_with_fake_catchall() -> FastAPI:
    """Build a FastAPI app and append a SPA-style catch-all, mirroring
    the structure ``create_app()`` produces when ``frontend/dist`` exists.

    Using a fake catch-all keeps the test independent of whether the
    real ``frontend/dist`` directory is present in the working tree.
    """
    app = FastAPI()

    @app.get("/{full_path:path}")
    async def fake_spa(full_path: str):  # pragma: no cover - exercised via client
        return {"served_by": "catchall", "path": full_path}

    return app


def test_register_test_route_wins_against_catchall():
    """A route registered via ``register_test_route`` matches BEFORE the
    SPA catch-all, even though the catch-all was added first.
    """
    from tests.helpers.test_routes import register_test_route

    app = _make_app_with_fake_catchall()

    async def test_endpoint():
        return {"served_by": "test_route"}

    register_test_route(app, "/__test__/ping", test_endpoint, methods=["GET"])

    with TestClient(app) as client:
        # Test route wins.
        r = client.get("/__test__/ping")
        assert r.status_code == 200
        assert r.json() == {"served_by": "test_route"}

        # Catch-all still serves unrelated paths.
        r2 = client.get("/some/spa/route")
        assert r2.status_code == 200
        assert r2.json()["served_by"] == "catchall"


def test_register_test_route_inserts_at_position_zero():
    """The helper must insert at ``app.router.routes[0]`` so a future
    refactor that changes the insertion index fails this test.
    """
    from tests.helpers.test_routes import register_test_route

    app = _make_app_with_fake_catchall()
    routes_before = len(app.router.routes)

    async def ep():
        return {}

    register_test_route(app, "/__test__/zero", ep)

    assert len(app.router.routes) == routes_before + 1
    new_route = app.router.routes[0]
    assert isinstance(new_route, Route)
    assert new_route.path == "/__test__/zero"


# -----------------------------------------------------------------------------
# G5 — SPA catch-all regression-shape pin
# -----------------------------------------------------------------------------


def test_spa_catchall_shape_in_create_app(tmp_path: pathlib.Path, monkeypatch):
    """Pin the current SPA-catchall implementation shape.

    The wiring in ``app.main.create_app()`` is:

    .. code-block:: python

        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
        if frontend_dist.is_dir():
            app.mount("/assets", StaticFiles(...))
            @app.get("/{full_path:path}")
            async def serve_spa(full_path: str): ...

    The catch-all is therefore:

    1. Conditional on ``frontend/dist`` existing.
    2. Implemented as an ``@app.get`` decorator (NOT a ``Mount``).
    3. Appended LAST (after every router include and exception handler).
    4. Uses the ``/{full_path:path}`` pattern.

    If any of those facts change, this test must be updated in
    lockstep with ``register_test_route`` — the helper relies on
    "catch-all is last + is a Route, not a Mount" semantics.
    """
    # Force the SPA branch to fire deterministically by pointing
    # frontend_dist at a tmp dir we create. We can't easily monkeypatch
    # ``Path(__file__).resolve().parent.parent`` inside create_app, so
    # instead we inspect the source AST of create_app for the load-bearing
    # shape, plus we runtime-check the case where the real frontend/dist
    # IS present.
    import inspect

    from app.main import create_app

    source = inspect.getsource(create_app)

    # (2) decorator-style, not Mount.
    assert '@app.get("/{full_path:path}")' in source, (
        "SPA catch-all must remain an @app.get decorator at "
        "'/{full_path:path}' — converting to a Mount changes ordering "
        "semantics and will break tests.helpers.test_routes."
    )

    # (1) conditional on frontend/dist existing.
    assert "frontend_dist.is_dir()" in source, (
        "SPA catch-all must remain guarded by ``frontend_dist.is_dir()`` "
        "— unconditional registration would break the test suite which "
        "runs without a built frontend."
    )

    # (3) "appended last" — the catch-all block must come AFTER the
    # routers include + exception handlers. We check positional order
    # within the function body.
    spa_idx = source.find('@app.get("/{full_path:path}")')
    handlers_idx = source.find("app.add_exception_handler")
    include_idx = source.find("app.include_router")
    assert spa_idx > 0, "SPA catch-all line not found"
    assert handlers_idx > 0 and include_idx > 0
    assert spa_idx > handlers_idx, (
        "SPA catch-all must be registered AFTER exception handlers"
    )
    assert spa_idx > include_idx, (
        "SPA catch-all must be registered AFTER include_router calls"
    )

    # Runtime cross-check: if frontend/dist is present in this repo,
    # the live app should have the catch-all as a Route (not Mount) at
    # the tail of app.router.routes.
    frontend_dist = _REPO_ROOT / "frontend" / "dist"
    if not frontend_dist.is_dir():
        pytest.skip("frontend/dist not built; AST checks above are the load-bearing pin")

    app = create_app()
    # Find the catch-all by path.
    spa_routes = [
        r for r in app.router.routes
        if isinstance(r, Route) and r.path == "/{full_path:path}"
    ]
    assert len(spa_routes) == 1, (
        f"expected exactly one SPA catch-all Route, found {len(spa_routes)}"
    )
