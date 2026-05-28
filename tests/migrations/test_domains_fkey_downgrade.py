"""Regression: domains FK downgrade in ``7f57993c9b09``.

Bucket (c) production bug discovered by WP06 roundtrip audit. The
auto-generated downgrade called ``op.drop_constraint(None, 'problems',
type_='foreignkey')`` — alembic cannot emit ``DROP CONSTRAINT`` without a
name and raises ``CompileError: Can't emit DROP CONSTRAINT for constraint
ForeignKeyConstraint ... it has no name``. The upgrade similarly created
the FK with ``None`` so we also need to give it a stable explicit name on
the way up.

This test is intentionally a *static* sanity check on the migration source
(not a live DB cycle) so it runs in every environment, not just where
postgres is reachable. The full upgrade→downgrade→upgrade live cycle is
covered by ``test_migration_roundtrip.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "alembic"
    / "versions"
    / "7f57993c9b09_add_domains_table_and_domain_id_to_.py"
)


def _find_calls(func_name: str) -> list[ast.Call]:
    """Return all ``op.<func_name>(...)`` calls inside the migration module."""
    tree = ast.parse(MIGRATION.read_text())
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == func_name
        ):
            calls.append(node)
    return calls


def test_drop_constraint_has_explicit_name():
    """Downgrade must pass a non-None constraint name to drop_constraint.

    Without it, alembic raises CompileError when emitting DROP CONSTRAINT
    for an unnamed FK. Was previously ``op.drop_constraint(None, ...)``.
    """
    calls = _find_calls("drop_constraint")
    # Zero calls is fine — the WP06 fix uses raw ALTER TABLE ... DROP
    # CONSTRAINT IF EXISTS so existing pre-rename databases also downgrade.
    for call in calls:
        first_arg = call.args[0]
        assert not (
            isinstance(first_arg, ast.Constant) and first_arg.value is None
        ), (
            f"op.drop_constraint at line {call.lineno} passes None as the "
            f"constraint name — alembic cannot emit DROP CONSTRAINT without "
            f"a name. Give the FK an explicit name in both upgrade and "
            f"downgrade."
        )


def test_create_foreign_key_has_explicit_name():
    """Upgrade must name the FK so downgrade can drop it by name."""
    calls = _find_calls("create_foreign_key")
    assert calls, "expected at least one op.create_foreign_key call"
    for call in calls:
        first_arg = call.args[0]
        assert not (
            isinstance(first_arg, ast.Constant) and first_arg.value is None
        ), (
            f"op.create_foreign_key at line {call.lineno} passes None as "
            f"the constraint name. Without a stable name, downgrade cannot "
            f"reliably drop it across environments."
        )
