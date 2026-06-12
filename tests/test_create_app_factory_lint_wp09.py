"""v2.11-WP09 (C3a) — ``FastAPI()`` constructor lint.

Background
----------
Tests that build a ``FastAPI()`` instance directly (instead of calling
``app.main.create_app()`` or the ``tests.helpers.app_factory.build_test_app``
helper) skip production wiring — middleware, exception handlers, the
domain-specific ``EXCEPTION_HANDLERS`` registered by
``app.routes.tickets``, etc. Each of v2.10-WP02 / WP05 / WP07 fixed a
silent-pass bug where a test on a bare ``FastAPI()`` app got the wrong
status code (commonly 500 from a missing handler) and either passed
for the wrong reason or asserted on the wrong envelope shape.

Scope
-----
- Scans ``tests/**/*.py``.
- Targets calls whose ``func`` is the bare name ``FastAPI`` — i.e.
  ``FastAPI(...)``. (``FastAPI`` as an attribute, e.g. ``fastapi.FastAPI(...)``,
  is intentionally NOT flagged today — none exists, and the import
  alias is the realistic surface.)
- An explicit allow-list below documents every by-design bare-FastAPI
  site. As of v2.12-WP07 this is a CLOSED set: every legacy route test
  that previously appeared here has been migrated to
  ``tests.helpers.app_factory.build_test_app``. The remaining entries
  are factory/middleware/SPA-catch-all isolation tests where booting
  via ``create_app()`` would defeat the test's purpose. New entries
  require a paired justification — if you find yourself appending to
  this list to make CI green, instead use
  ``tests.helpers.app_factory.build_test_app``.

The lint deliberately fails LOUD with ``file:line`` so reviewers can
see exactly which test needs migration / allow-list entry.

Lessons-pin
-----------
This is the v2.11-WP09 regression-lint surface. Pairs with the helper
at ``tests/helpers/app_factory.py``; together they enforce that route
tests boot the real production wiring or explicitly document why they
are an exception.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.helpers.source_lint import (
    iter_calls,
    iter_source_files,
    parse_module,
)


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"


# -----------------------------------------------------------------------------
# Allow-list of files containing intentional bare ``FastAPI()`` constructors.
#
# CLOSED SET — by-design exceptions only. The v2.11-WP09 legacy migration
# backlog was fully closed in v2.12-WP04..WP07 (cluster sweep); the seven
# entries below are NOT a TODO list. Each one tests a property of the
# application factory itself, a single middleware in isolation, or a
# helper that would couple to real frontend assets if it booted via
# ``create_app()``. Adding a new entry should be exceptional and paired
# with a one-line justification explaining why ``build_test_app()`` can
# not satisfy the test's needs.
#
# Rule for adding NEW entries: don't. Use ``build_test_app()`` from
# ``tests/helpers/app_factory.py`` instead.
# -----------------------------------------------------------------------------
_ALLOWLIST: dict[str, str] = {
    # Tests for create_app itself — must build bare apps to compare against.
    "tests/test_main.py": "exercises app.main internals, must not recurse via create_app()",
    "tests/test_v2_11_wp05_boot_hardening.py": "boot-hardening regression test, asserts on bare-app behaviour",
    # Middleware isolation: deliberately build a minimal app with just the
    # middleware under test — using create_app() would pull in unrelated
    # middleware and obscure what's being asserted.
    "tests/middleware/test_bearer_auth.py": "middleware-only isolation; create_app would muddy assertions",
    "tests/middleware/test_correlation.py": "middleware-only isolation; tests CorrelationIdMiddleware in vacuo",
    "tests/middleware/test_security.py": "middleware-only isolation; tests SecurityHeadersMiddleware in vacuo",
    "tests/observability/test_otel_init.py": "tests setup_otel against a fresh app each scenario",
    "tests/test_spa_catchall_hardening_wp11.py": "WP11 (C8): builds a tiny app with a fake SPA catch-all to exercise register_test_route helper in isolation; create_app() would couple the test to real frontend/dist presence",
}


def _iter_test_py_files() -> list[pathlib.Path]:
    return list(iter_source_files(_TESTS_DIR))


def _scan(path: pathlib.Path) -> list[int]:
    """Return list of line numbers where ``FastAPI(...)`` is called.

    Matches ``Call(func=Name(id='FastAPI'))`` — i.e. the import-aliased
    form ``from fastapi import FastAPI`` followed by ``FastAPI(...)``.
    Does NOT match attribute access (``fastapi.FastAPI(...)``) — none
    currently exists in-tree, and a future ``fastapi.FastAPI`` site can
    be added to this matcher when needed.
    """
    tree = parse_module(path)
    if tree is None:
        return []
    # iter_calls(dotted_name="FastAPI") matches both Name and Attribute tails.
    # Preserve the original Name-only filter to keep semantics identical: a
    # future ``fastapi.FastAPI(...)`` site is intentionally NOT flagged today.
    return [
        node.lineno
        for node in iter_calls(tree, dotted_name="FastAPI")
        if isinstance(node.func, ast.Name)
    ]


def test_no_bare_fastapi_constructor_outside_allowlist():
    """Every ``FastAPI(...)`` call in ``tests/**`` lives in a file that
    is on the explicit allow-list.

    Failure means a new test built a bare ``FastAPI()`` app — that test
    will silently skip exception handlers and middleware wired by
    ``create_app()``. Use ``tests.helpers.app_factory.build_test_app``
    instead, or add the file to ``_ALLOWLIST`` above with a one-line
    justification (and a follow-up plan).
    """
    offenders: list[tuple[pathlib.Path, int]] = []
    stale_allowlist: list[str] = []

    for path in _iter_test_py_files():
        # Don't scan this lint file or the helper itself.
        if path.name == pathlib.Path(__file__).name:
            continue
        if path.name == "app_factory.py" and path.parent.name == "helpers":
            continue
        rel = str(path.relative_to(_REPO_ROOT))
        lines = _scan(path)
        if not lines:
            if rel in _ALLOWLIST:
                stale_allowlist.append(rel)
            continue
        if rel in _ALLOWLIST:
            continue
        for ln in lines:
            offenders.append((path, ln))

    msgs: list[str] = []
    if offenders:
        body = "\n".join(
            f"  {p.relative_to(_REPO_ROOT)}:{ln}: bare FastAPI() — "
            "use tests.helpers.app_factory.build_test_app(...) "
            "or add to _ALLOWLIST with a justification"
            for p, ln in offenders
        )
        msgs.append(
            "Bare ``FastAPI()`` constructor in test files — these apps "
            "skip middleware and exception handlers wired by "
            "``app.main.create_app()`` and risk silent-pass bugs:\n"
            + body
        )
    if stale_allowlist:
        body = "\n".join(f"  {rel}" for rel in stale_allowlist)
        msgs.append(
            "Stale ``_ALLOWLIST`` entries (file no longer contains a bare "
            "FastAPI() — please remove from the allow-list):\n" + body
        )
    if msgs:
        pytest.fail("\n\n".join(msgs))


def test_create_app_factory_lint_detects_synthetic_bad(tmp_path: pathlib.Path):
    """Self-test: the scanner actually flags a synthetic bare-FastAPI
    site, so a future refactor of the scanner can't silently neuter
    the lint.

    Three cases:

    1. A file calling ``FastAPI()`` directly — must be flagged.
    2. A file calling only ``create_app()`` — must NOT be flagged.
    3. A file calling ``build_test_app()`` (the helper) — must NOT be
       flagged.
    """
    bad = tmp_path / "bad_test.py"
    bad.write_text(
        "from fastapi import FastAPI\n"
        "def test_x():\n"
        "    app = FastAPI()\n"
        "    return app\n"
    )
    assert _scan(bad), "scanner should detect synthetic bare FastAPI() call"

    good_factory = tmp_path / "good_factory_test.py"
    good_factory.write_text(
        "from app.main import create_app\n"
        "def test_x():\n"
        "    app = create_app()\n"
        "    return app\n"
    )
    assert not _scan(good_factory), (
        "scanner must not flag ``create_app()``; got hits"
    )

    good_helper = tmp_path / "good_helper_test.py"
    good_helper.write_text(
        "from tests.helpers.app_factory import build_test_app\n"
        "def test_x():\n"
        "    app = build_test_app()\n"
        "    return app\n"
    )
    assert not _scan(good_helper), (
        "scanner must not flag ``build_test_app()``; got hits"
    )


def test_build_test_app_helper_wires_exception_handlers():
    """Smoke test: ``build_test_app()`` returns an app whose exception
    handlers include the central ``AppError`` map AND the per-route
    handlers registered from ``app.routes.tickets.EXCEPTION_HANDLERS``.

    This is the load-bearing assertion — the whole point of the helper
    is that route-tests built on it inherit production's exception
    wiring. If this assertion ever flips false, every test using
    ``build_test_app()`` is silently degraded; fail loudly.
    """
    from app.exceptions import AppError
    from app.main import _EXCEPTION_STATUS_MAP
    from app.routes.tickets import EXCEPTION_HANDLERS as _TICKET_EXC_HANDLERS

    from tests.helpers.app_factory import build_test_app

    app = build_test_app()
    handlers = app.exception_handlers

    # Central AppError handler must be wired.
    assert AppError in handlers, (
        "build_test_app() must wire the central AppError handler from create_app()"
    )

    # Every exception type in the central map must be reachable from the
    # AppError handler (they're subclasses) — sanity-check the map exists
    # and is non-empty, so a future refactor can't accidentally empty it.
    assert _EXCEPTION_STATUS_MAP, "central exception status map must not be empty"

    # Every per-route ticket handler must be registered on the app.
    for exc_cls in _TICKET_EXC_HANDLERS:
        assert exc_cls in handlers, (
            f"build_test_app() must wire ticket handler for {exc_cls.__name__}"
        )


def test_build_test_app_supports_dependency_overrides():
    """The helper's ``dependency_overrides`` kwarg merges into
    ``app.dependency_overrides`` so callers can swap DB sessions, auth,
    etc. without touching the app afterwards.
    """
    from tests.helpers.app_factory import build_test_app

    def _sentinel_dep():  # pragma: no cover - placeholder
        return None

    def _sentinel_override():  # pragma: no cover - placeholder
        return "overridden"

    app = build_test_app(dependency_overrides={_sentinel_dep: _sentinel_override})
    assert app.dependency_overrides.get(_sentinel_dep) is _sentinel_override
