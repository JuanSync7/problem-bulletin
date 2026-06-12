"""v2.11-WP15 — inverted regression lint for the ``legacy_status`` rename.

Background
----------
Migration ``a1_agent_kanban`` renamed ``problems.status`` → ``problems.legacy_status``
to make room for a then-new enum-typed ``status`` column on the (then-being-created)
tickets table. The ORM kept the Python attribute ``Problem.status`` mapped to the
renamed DB column. The Python/DB asymmetry was a persistent footgun for raw-SQL
call sites (v2.10-WP04b fixed one, v2.11-WP02 swept the rest).

In v2.11-WP15 (Bucket E2) the column was renamed *back* to ``problems.status`` in
``a19_problems_status_rename``. Python attribute and DB column
now share the same name — the footgun is closed.

This file used to flag any raw-SQL ``p.status`` / ``problems.status`` reference
as drift. After WP15 those references are CORRECT and the previous lint would
fire on every legitimate query. The lint is **inverted**: it now flags any
raw-SQL ``legacy_status`` reference in production code under ``app/``, because
the column no longer exists by that name and any such reference would either
crash at execute time or be a misleading copy-paste from old code.

Scope
-----
- Scans ``app/**/*.py`` (production code only).
- Skips ``alembic/versions/*`` — historical migrations legitimately reference
  the pre-rename name. Alembic does not live under ``app/`` in this repo, so
  the path filter is defensive.
- Walks every string literal (plain + f-string segments) via ``ast`` so we
  do not depend on comment placement.

Self-test
---------
``test_audit_lint_detects_synthetic_drift`` verifies the scanner catches a
synthetic ``legacy_status`` reintroduction and ignores legitimate
``p.status`` / ``problems.status`` queries. Without a self-test a future
refactor could neuter the lint by tweaking the regex into a no-op.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.helpers.source_lint import (
    iter_source_files,
    iter_string_literals,
    parse_module,
)


# Any literal occurrence of the bare word ``legacy_status`` is forbidden in
# ``app/``. We do not need to anchor on ``p.`` / ``problems.`` — the only
# place ``legacy_status`` could appear in production code is in raw SQL or a
# stale comment, and either way it is wrong post-WP15.
_BAD = re.compile(r"\blegacy_status\b")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP_DIR = _REPO_ROOT / "app"


def _iter_app_py_files() -> list[pathlib.Path]:
    # alembic does not live under app/ in this repo (defensive filter only).
    return [
        p for p in iter_source_files(_APP_DIR)
        if "alembic" not in p.parts and "versions" not in p.parts
    ]


def _scan(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return [(lineno, snippet)] for every legacy_status hit in ``path``."""
    tree = parse_module(path)
    if tree is None:
        return []
    hits: list[tuple[int, str]] = []
    for node, value in iter_string_literals(tree):
        for match in _BAD.finditer(value):
            hits.append((node.lineno, value[: match.end() + 20]))
    return hits


def test_no_legacy_status_in_app():
    """Production code under ``app/`` contains no ``legacy_status`` references.

    The DB column was renamed back to ``status`` in
    ``a19_problems_status_rename`` (v2.11-WP15). The only
    place ``legacy_status`` may legitimately appear is in alembic migration
    history (where it documents the transient name). Any hit under ``app/``
    is a stale comment or a copy-paste of pre-WP15 raw SQL.

    If this test fails, replace the ``legacy_status`` reference with ``status``.
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
            "Stale ``legacy_status`` reference detected — the DB column was "
            "renamed back to ``status`` in v2.11-WP15 "
            "(a19_problems_status_rename). Replace with "
            "``status``:\n" + "\n".join(lines)
        )


def test_audit_lint_detects_synthetic_drift(tmp_path: pathlib.Path):
    """Self-test: the audit regex catches a synthetic ``legacy_status``
    reintroduction and ignores the legitimate post-WP15 ``status`` spelling.
    """
    drifted = tmp_path / "drifted.py"
    drifted.write_text(
        'from sqlalchemy import text\n'
        'q = text("SELECT id FROM problems p WHERE p.legacy_status = :s")\n'
    )
    assert _scan(drifted), (
        "scanner should detect synthetic ``legacy_status`` reintroduction"
    )

    clean = tmp_path / "clean.py"
    clean.write_text(
        'from sqlalchemy import text\n'
        'q = text("SELECT id FROM problems p WHERE p.status = :s")\n'
    )
    assert not _scan(clean), (
        "scanner must not flag the post-WP15 ``p.status`` spelling"
    )
