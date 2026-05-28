"""v2.11-WP11 (C8) — Safe route registration that won't be eaten by the SPA catch-all.

Background
----------
v2.10-WP01 and v2.10-WP07 each found cases where tests appended a
custom route to ``app`` AFTER ``create_app()`` ran. ``create_app()``
registers a catch-all ``@app.get("/{full_path:path}")`` SPA handler
when ``frontend/dist`` exists. Any route registered later is shadowed —
FastAPI matches the catch-all first because it was added earlier.

This helper inserts the route at position 0 of ``app.router.routes``,
guaranteeing it wins against the catch-all (and against every other
route, but that's acceptable since tests own the wiring).

Why position 0
--------------
FastAPI/Starlette matches routes in list order. The catch-all is
appended last by ``create_app()``, so prepending at index 0 is the
smallest, most explicit way to win priority without restructuring the
production wiring. This intentionally diverges from a sub-router /
mount approach (option ``(a)`` in the v2.11 brief) which would change
production routing — keeping the helper test-side only.

Usage
-----
.. code-block:: python

    from tests.helpers.test_routes import register_test_route

    async def my_handler():
        return {"ok": True}

    register_test_route(app, "/test-only", my_handler, methods=["GET"])

The SPA catch-all behaviour for non-test paths is unaffected.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from fastapi import FastAPI


def register_test_route(
    app: FastAPI,
    path: str,
    endpoint: Callable[..., Any],
    *,
    methods: Iterable[str] = ("GET",),
    name: str | None = None,
) -> None:
    """Register ``endpoint`` at ``path`` so it wins against the SPA catch-all.

    Inserts the resulting route at ``app.router.routes[0:0]`` (i.e.
    position 0) so it matches before any pre-existing route, including
    a catch-all appended by ``create_app()``.

    Parameters
    ----------
    app:
        The FastAPI application instance.
    path:
        URL path for the route, e.g. ``"/__test__/ping"``.
    endpoint:
        Sync or async callable used as the route handler.
    methods:
        HTTP methods to register. Defaults to ``("GET",)``.
    name:
        Optional route name (defaults to ``endpoint.__name__``).
    """
    # Use add_api_route to construct the proper APIRoute (with FastAPI's
    # dependency-injection wiring), then move it to the front.
    app.add_api_route(
        path,
        endpoint,
        methods=list(methods),
        name=name or getattr(endpoint, "__name__", "test_route"),
    )
    # The route we just appended is the last one. Pop it and prepend.
    new_route = app.router.routes.pop()
    app.router.routes.insert(0, new_route)
