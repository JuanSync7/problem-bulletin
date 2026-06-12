"""v2.11-WP11 (C5) — Plain-dict ``headers=`` in mock construction lint.

Background
----------
``starlette.datastructures.Headers`` is case-insensitive; plain ``dict``
is case-sensitive. A test stubbing ``request.headers = {"Authorization":
...}`` silently passes when the handler reads ``.get("authorization")``
only by coincidence of casing — production receives the case-insensitive
``Headers`` type, so the test diverges from production behaviour.

This lint scans ``tests/**/*.py`` for the bug pattern:

- ``MagicMock(headers={...dict-literal...})`` (or ``Mock(...)``).
- Assignment ``<x>.headers = {...dict-literal...}`` where ``<x>`` is
  *probably* a mock (the AST scanner can't always tell, so the lint
  takes the conservative view: any ``.headers = {dict-literal}``
  assignment in a test file is suspect).

Fix: use ``tests.helpers.requests.build_mock_request(headers={...})``
which wraps in ``Headers(...)``. A tiny allow-list documents any
intentional exceptions.

Pairs with the helper at ``tests/helpers/requests.py``.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.helpers.source_lint import iter_source_files, parse_module


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"


# -----------------------------------------------------------------------------
# Allow-list of intentional plain-dict ``headers=`` sites.
# Each entry: ``"<relative-path>:<line>": "<one-line justification>"``.
# Prefer migrating to ``build_mock_request`` over adding entries here.
# -----------------------------------------------------------------------------
_ALLOWLIST: dict[str, str] = {
    # (empty at WP11 land — the one historical hit was migrated)
}


def _scan(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return ``(lineno, snippet)`` pairs for offending sites in ``path``.

    Two patterns are flagged:

    1. ``MagicMock(headers={...})`` / ``Mock(headers={...})`` — call with a
       ``headers=`` kwarg whose value is a ``Dict`` literal (regardless of
       whether the dict is empty).
    2. ``<expr>.headers = {...}`` — any attribute-assignment whose RHS is
       a ``Dict`` literal and whose attribute is exactly ``headers``.
    """
    hits: list[tuple[int, str]] = []
    tree = parse_module(path)
    if tree is None:
        return hits

    for node in ast.walk(tree):
        # Pattern 1: MagicMock(headers={...}) / Mock(headers={...})
        if isinstance(node, ast.Call):
            func = node.func
            func_name: str | None = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            if func_name in {"MagicMock", "Mock", "AsyncMock", "NonCallableMock"}:
                for kw in node.keywords:
                    if kw.arg == "headers" and isinstance(kw.value, ast.Dict):
                        hits.append((node.lineno, f"{func_name}(headers={{...}})"))

        # Pattern 2: <x>.headers = {...}
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Dict):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "headers":
                    hits.append((node.lineno, f"<x>.headers = {{...}}"))
                    break

    return hits


def _iter_test_py_files() -> list[pathlib.Path]:
    return list(iter_source_files(_TESTS_DIR))


def test_no_plain_dict_headers_in_mock_construction():
    """Every ``headers=<dict-literal>`` in mock construction OR every
    ``.headers = <dict-literal>`` assignment in ``tests/**`` is either
    migrated to ``build_mock_request(headers=...)`` (which wraps in
    ``Headers``) or allow-listed with a one-line justification.

    Failure means a new test introduced a case-sensitivity divergence
    from production.
    """
    offenders: list[tuple[pathlib.Path, int, str]] = []

    for path in _iter_test_py_files():
        if path.name == pathlib.Path(__file__).name:
            continue
        if path.name == "requests.py" and path.parent.name == "helpers":
            continue
        rel = str(path.relative_to(_REPO_ROOT))
        for ln, snippet in _scan(path):
            key = f"{rel}:{ln}"
            if key in _ALLOWLIST:
                continue
            offenders.append((path, ln, snippet))

    if offenders:
        body = "\n".join(
            f"  {p.relative_to(_REPO_ROOT)}:{ln}: {snip} — "
            "use tests.helpers.requests.build_mock_request(headers={...}) "
            "(wraps in starlette.datastructures.Headers, case-insensitive)"
            for p, ln, snip in offenders
        )
        pytest.fail(
            "Plain-dict ``headers=`` in mock construction or "
            "``.headers = {...}`` assignment found in test files — "
            "plain ``dict`` is case-sensitive but production receives "
            "``starlette.datastructures.Headers`` (case-insensitive), "
            "so the test diverges from production behaviour:\n" + body
        )


def test_mock_headers_lint_detects_synthetic_bad(tmp_path: pathlib.Path):
    """Self-test: the scanner flags the synthetic bad patterns and does
    NOT flag the good patterns. Keeps a future refactor from neutering
    the lint.
    """
    bad_call = tmp_path / "bad_call.py"
    bad_call.write_text(
        "from unittest.mock import MagicMock\n"
        "def test_x():\n"
        "    r = MagicMock(headers={'Authorization': 'Bearer x'})\n"
    )
    bad_call_hits = _scan(bad_call)
    assert bad_call_hits, "scanner must flag MagicMock(headers={...})"
    assert "MagicMock(headers={...})" in bad_call_hits[0][1]

    bad_assign = tmp_path / "bad_assign.py"
    bad_assign.write_text(
        "from unittest.mock import MagicMock\n"
        "def test_x():\n"
        "    r = MagicMock()\n"
        "    r.headers = {'Authorization': 'Bearer x'}\n"
    )
    assert _scan(bad_assign), "scanner must flag <x>.headers = {...}"

    good_helper = tmp_path / "good_helper.py"
    good_helper.write_text(
        "from tests.helpers.requests import build_mock_request\n"
        "def test_x():\n"
        "    r = build_mock_request(headers={'Authorization': 'Bearer x'})\n"
    )
    assert not _scan(good_helper), (
        "scanner must not flag build_mock_request(headers=...)"
    )

    good_real_headers = tmp_path / "good_real_headers.py"
    good_real_headers.write_text(
        "from unittest.mock import MagicMock\n"
        "from starlette.datastructures import Headers\n"
        "def test_x():\n"
        "    r = MagicMock()\n"
        "    r.headers = Headers({'Authorization': 'Bearer x'})\n"
    )
    assert not _scan(good_real_headers), (
        "scanner must not flag .headers = Headers(...) — only plain-dict literals"
    )


def test_build_mock_request_headers_case_insensitive():
    """Smoke test: ``build_mock_request(headers={...})`` yields a
    ``.headers`` attribute that supports case-insensitive ``.get``
    just like production ``starlette.datastructures.Headers``.
    """
    from starlette.datastructures import Headers

    from tests.helpers.requests import build_mock_request

    req = build_mock_request(headers={"Authorization": "Bearer xyz"})
    assert isinstance(req.headers, Headers)
    # Capital and lowercase both work.
    assert req.headers.get("authorization") == "Bearer xyz"
    assert req.headers.get("Authorization") == "Bearer xyz"
    assert req.headers.get("AUTHORIZATION") == "Bearer xyz"


def test_build_mock_request_cookies_and_extra():
    """Smoke test: cookies dict round-trips, extra kwargs land as attrs."""
    from tests.helpers.requests import build_mock_request

    req = build_mock_request(
        headers={},
        cookies={"access_token": "abc"},
        url="http://test/",
    )
    assert req.cookies["access_token"] == "abc"
    assert req.url == "http://test/"
