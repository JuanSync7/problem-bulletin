"""v2.11-WP09 (C3b) — Test-app factory helper.

Background
----------
Tests that build a ``FastAPI()`` instance directly skip the production
wiring done by ``app.main.create_app()`` — exception handlers,
middleware (correlation id, security headers, logging, agent-step),
domain-specific exception handlers from
``app.routes.tickets.EXCEPTION_HANDLERS``, etc. v2.10-WP02 and
v2.10-WP07 each shipped a silent-pass bug class where a test asserted
on a 4xx envelope that production raises but a bare-FastAPI test app
never wired up — the test got a generic 500 from Starlette and either
passed by accident or asserted on the wrong shape.

This helper gives route-tests a single canonical entry-point that
*delegates to ``create_app()``* and accepts a small set of test-time
overrides (most commonly ``dependency_overrides``).

Usage
-----
.. code-block:: python

    from tests.helpers.app_factory import build_test_app

    def test_my_route():
        app = build_test_app(
            dependency_overrides={get_db: _fake_db}
        )
        with TestClient(app) as client:
            ...

The companion lint in ``tests/test_create_app_factory_lint_wp09.py``
keeps new tests from regressing back to bare ``FastAPI()``.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from fastapi import FastAPI


def build_test_app(
    *,
    dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
) -> FastAPI:
    """Return a fully-wired ``FastAPI`` app via ``app.main.create_app()``.

    Parameters
    ----------
    dependency_overrides:
        Optional mapping merged into ``app.dependency_overrides`` after
        creation. Mirrors how FastAPI itself spells overrides — the
        helper does NOT replace, it merges, so callers can rely on
        whatever production already overrides (currently none, but
        forward-compatible).

    Returns
    -------
    FastAPI
        The application instance returned by ``create_app()``, with
        every middleware, exception handler, and router that production
        boots — see ``app.main.create_app`` for the canonical list.

    Notes
    -----
    - The lifespan is *not* run by ``TestClient`` unless the test uses
      it as a context manager (``with TestClient(app) as client:``).
      Tests that don't need background tasks can skip the ``with``.
    - This helper never patches env vars itself; rely on
      ``tests/conftest.py`` for the ambient test environment.
    """
    from app.main import create_app

    app = create_app()
    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)
    return app
