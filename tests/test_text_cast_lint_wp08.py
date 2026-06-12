"""v2.11-WP08 (C2) — ``text("...:param::cast")`` PostgreSQL bind-cast lint.

Background
----------
In SQLAlchemy ``text("WHERE x = :param::int")``, the ``:param`` is
consumed by SQLAlchemy's bind-parameter parser first, leaving a stray
``::int`` cast operator with no left-hand side. At execute time this
raises a syntax error (or, depending on dialect, mis-binds entirely).

Correct alternatives:

- ``text("WHERE x = CAST(:param AS int)")`` — cast lives outside the
  bind syntax.
- Move the cast into Python: bind ``int(value)`` and write
  ``text("WHERE x = :param")``.

Scope
-----
- Scans ``app/**/*.py`` (production code only — test files calling
  ``text(...)`` are rare and not the target).
- Targets calls to ``text(...)`` and ``*.text(...)`` (covers
  ``from sqlalchemy import text`` and ``sa.text(...)`` styles).
- Inspects ONLY the first positional arg when it's a ``Constant(str)``
  or a ``JoinedStr`` with literal segments. Comments and docstrings
  are inherently excluded — the AST surface is ``Call.args[0]``, so a
  comment or module-level docstring can't reach this code path.
- Regex: ``:[a-zA-Z_][a-zA-Z0-9_]*::[a-zA-Z]`` — a colon-prefixed
  bind name immediately followed by ``::`` and an alpha cast type.

Lessons-pin
-----------
The colon-cast trap is one of those SQLAlchemy footguns that "looks
like normal PG" and works fine in isolation but breaks the moment
SQLAlchemy is in the middle. Once-and-done lint.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from tests.helpers.source_lint import (
    iter_calls,
    iter_source_files,
    parse_module,
)


# Matches a SQLAlchemy bind name (``:foo``) followed immediately by
# the PostgreSQL cast operator and an alpha type. The leading-colon
# anchor is what distinguishes this from a legitimate naked
# ``column::int`` cast in the same query (which is fine — only the
# *bind*-name form trips SQLAlchemy's parser).
_BAD = re.compile(r":[a-zA-Z_][a-zA-Z0-9_]*::[a-zA-Z]")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP_DIR = _REPO_ROOT / "app"


def _iter_app_py_files() -> list[pathlib.Path]:
    return list(iter_source_files(_APP_DIR))


def _string_literal_segments(arg: ast.expr) -> list[tuple[int, str]]:
    """Return ``[(lineno, literal_value), ...]`` for the literal parts of
    a ``text(...)`` first argument. Handles plain ``Constant(str)`` and
    ``JoinedStr`` (f-string) literal segments. Returns ``[]`` for
    non-string args (variable references, concatenations of unknown
    pieces) — those are out of static scope.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [(arg.lineno, arg.value)]
    if isinstance(arg, ast.JoinedStr):
        out: list[tuple[int, str]] = []
        for v in arg.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append((v.lineno, v.value))
        return out
    return []


def _scan(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, offending_substring), ...]`` for each
    ``:bind::cast`` hit in a ``text(...)`` call in ``path``.
    """
    hits: list[tuple[int, str]] = []
    tree = parse_module(path)
    if tree is None:
        return hits

    # dotted_name="text" matches text(...) and sa.text(...) / sqlalchemy.text(...).
    for node in iter_calls(tree, dotted_name="text"):
        if not node.args:
            continue
        for lineno, literal in _string_literal_segments(node.args[0]):
            for match in _BAD.finditer(literal):
                hits.append((lineno, match.group(0)))
    return hits


def test_no_bind_cast_in_text_calls_in_app():
    """No ``text("... :param::cast ...")`` in production code.

    The ``:name::type`` pattern is a SQLAlchemy footgun: ``:name`` is
    consumed by the bind-parameter parser, leaving a stray ``::type``.
    Use ``CAST(:name AS type)`` or move the cast into Python.

    Exclusions:

    - Non-string args (variables, concatenations) — out of static
      scope.
    - Comments and docstrings — never reach ``text(...)`` args via the
      AST surface, so naturally excluded.
    - Naked ``column::int`` (no leading-colon bind) — that's a fine
      PostgreSQL cast; the regex anchors on the ``:bind::`` form
      specifically.
    """
    all_hits: list[tuple[pathlib.Path, int, str]] = []
    for path in _iter_app_py_files():
        for lineno, snippet in _scan(path):
            all_hits.append((path, lineno, snippet))

    if all_hits:
        lines = [
            f"  {p.relative_to(_REPO_ROOT)}:{lineno}: {snippet!r}"
            for p, lineno, snippet in all_hits
        ]
        pytest.fail(
            "SQLAlchemy ``text()`` bind-cast trap detected — ``:name::type`` "
            "doesn't work (the ``:name`` is eaten by the bind parser). Use "
            "``CAST(:name AS type)`` or move the cast into Python:\n"
            + "\n".join(lines)
        )


def test_text_cast_lint_detects_synthetic_bad(tmp_path: pathlib.Path):
    """Self-test: the regex actually catches a synthetic bad cast.

    Cases:

    1. ``text("... :pid::int ...")`` — must flag.
    2. ``text("... CAST(:pid AS int) ...")`` — correct form, must not flag.
    3. ``text("... col::int ...")`` (naked column cast, no bind name) —
       must not flag; that's a legitimate PG cast.
    4. ``text("... :pid::int ...")`` inside an f-string literal segment —
       must flag.
    """
    bad = tmp_path / "bad.py"
    bad.write_text(
        'from sqlalchemy import text\n'
        'q = text("SELECT * FROM t WHERE id = :pid::int")\n'
    )
    assert _scan(bad), "scanner should detect synthetic :pid::int bind-cast hit"

    good = tmp_path / "good.py"
    good.write_text(
        'from sqlalchemy import text\n'
        'q = text("SELECT * FROM t WHERE id = CAST(:pid AS int)")\n'
    )
    assert not _scan(good), (
        "scanner must not flag the correct CAST(:pid AS int) form"
    )

    naked = tmp_path / "naked.py"
    naked.write_text(
        'from sqlalchemy import text\n'
        'q = text("SELECT col::int FROM t")\n'
    )
    assert not _scan(naked), (
        "scanner must not flag a naked ``col::int`` cast (no bind name)"
    )

    fstring = tmp_path / "fstring.py"
    fstring.write_text(
        'from sqlalchemy import text\n'
        'tbl = "t"\n'
        'q = text(f"SELECT * FROM {tbl} WHERE id = :pid::int")\n'
    )
    assert _scan(fstring), (
        "scanner should detect :pid::int inside an f-string literal segment"
    )
