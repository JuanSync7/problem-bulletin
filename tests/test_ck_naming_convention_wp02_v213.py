"""v2.13-WP02 (Bucket A1) — ck naming_convention resurrection.

Background
----------
v2.11-WP10 pinned 4 of 5 keys (``ix``, ``uq``, ``fk``, ``pk``) on
``Base.metadata.naming_convention`` but deferred ``ck`` because every
pre-WP10 ``CheckConstraint(name=...)`` in the repo passed the FULL
already-prefixed name (``name="ck_<table>_<short>"``), and the
idiomatic template ``"ck_%(table_name)s_%(constraint_name)s"`` would
double-wrap those at DDL compile time
(``CONSTRAINT ck_<table>_ck_<table>_<short>``).

v2.12-WP08 ported every model-side ``CheckConstraint(name=...)`` to
the short form (``name="<short>"``), and started wrapping alembic
migration name literals with ``sqlalchemy.sql.elements.conv(...)`` to
short-circuit the convention substitution. v2.12-WP08 was
rate-limited mid-flight. v2.13-WP02 closes the remaining 44 alembic
sites + flips the ``ck`` key live in ``app/database.py``.

This test is the static + dynamic guard that:

1. ``Base.metadata.naming_convention["ck"]`` equals the idiomatic
   ``"ck_%(table_name)s_%(constraint_name)s"`` template.
2. For every model class with a ``CheckConstraint`` in
   ``__table_args__``, the compiled ``CREATE TABLE`` DDL emits
   ``CONSTRAINT ck_<table>_<short> CHECK ...`` — NOT
   ``ck_<table>_ck_<table>_<short>``.
3. A synthetic-bad self-test confirms that an already-prefixed
   ``name="ck_<t>_<s>"`` (not wrapped with ``conv()``) WOULD double-wrap
   if anyone re-introduced the pattern in a model file.
"""
from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table
from sqlalchemy.schema import CreateTable

# Import every model so they bind to Base.metadata and become walkable.
import app.models  # noqa: F401 — registers all mappers
from app.database import NAMING_CONVENTION, Base


EXPECTED_CK_TEMPLATE = "ck_%(table_name)s_%(constraint_name)s"


def test_ck_key_present_in_naming_convention():
    """``Base.metadata.naming_convention["ck"]`` resolves to the
    idiomatic SQLAlchemy template.

    With models porting to bare short names (``name="positive"`` not
    ``name="ck_table_positive"``), the convention will render
    ``ck_<table>_positive`` automatically — matching the historical
    on-disk full names.
    """
    assert NAMING_CONVENTION.get("ck") == EXPECTED_CK_TEMPLATE
    assert Base.metadata.naming_convention.get("ck") == EXPECTED_CK_TEMPLATE


def _models_with_check_constraints():
    """Yield ``(model_class, [check_constraint, ...])`` pairs for every
    SQLAlchemy mapper that owns at least one ``CheckConstraint`` in its
    ``__table__``.
    """
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not hasattr(cls, "__table__"):
            continue
        cks = [c for c in cls.__table__.constraints if isinstance(c, CheckConstraint)]
        if cks:
            yield cls, cks


def _model_ck_cases():
    cases = []
    for cls, cks in _models_with_check_constraints():
        for ck in cks:
            cases.append((cls.__name__, cls.__table__.name, ck))
    return cases


@pytest.mark.parametrize(
    "model_name,table_name,ck",
    _model_ck_cases(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_model_check_constraint_emits_single_ck_prefix(model_name, table_name, ck):
    """For each model-declared ``CheckConstraint``, the compiled
    constraint name is ``ck_<table>_<short>`` — exactly one ``ck_``
    prefix.

    This catches double-wrap (``ck_<t>_ck_<t>_<s>``) and unprefixed
    (``<s>``) drift in a single assertion. The compiled DDL is the
    authoritative source: SQLAlchemy renders constraint names lazily
    at compile time, so a static string match on ``ck.name`` would not
    catch every drift mode.
    """
    ddl = str(CreateTable(ck.table).compile())
    # Resolve the templated name (this is what the DDL compiler emits).
    resolved = str(ck.name)
    # Single ``ck_<table>_`` prefix, exactly one occurrence.
    assert resolved.startswith(f"ck_{table_name}_"), (
        f"{model_name}.{resolved} does not start with ck_{table_name}_"
    )
    assert not resolved.startswith(f"ck_{table_name}_ck_"), (
        f"{model_name}.{resolved} double-wraps the ck prefix — "
        "model file probably passes name=\"ck_<table>_<short>\" "
        "instead of bare name=\"<short>\""
    )
    # Same constraint name must show up in the rendered CREATE TABLE.
    assert resolved in ddl, (
        f"{resolved} not found in CREATE TABLE DDL for {table_name}:\n{ddl}"
    )


def test_synthetic_already_prefixed_double_wraps():
    """Self-test: confirm that the lint catches the double-wrap mode.

    A standalone ``MetaData`` with the convention set, plus a
    ``CheckConstraint(name="ck_widgets_positive")`` (unprefixed via
    ``conv()``) MUST resolve to the double-wrapped form
    ``ck_widgets_ck_widgets_positive``. If this assertion ever fails,
    SQLAlchemy's substitution semantics have changed and the other
    tests in this file would silently pass even with a broken port.
    """
    md = MetaData(naming_convention={"ck": EXPECTED_CK_TEMPLATE})
    t = Table(
        "widgets",
        md,
        Column("id", Integer, primary_key=True),
        CheckConstraint("id > 0", name="ck_widgets_positive"),
    )
    cks = [c for c in t.constraints if isinstance(c, CheckConstraint)]
    assert len(cks) == 1
    assert str(cks[0].name) == "ck_widgets_ck_widgets_positive", (
        "SQLAlchemy convention substitution no longer double-wraps "
        "already-prefixed names — review the WP02 strategy"
    )


def test_synthetic_bare_short_name_single_wraps():
    """Self-test: bare short name renders to ``ck_<table>_<short>``.

    This is the SUCCESS path the model ports follow.
    """
    md = MetaData(naming_convention={"ck": EXPECTED_CK_TEMPLATE})
    t = Table(
        "widgets",
        md,
        Column("id", Integer, primary_key=True),
        CheckConstraint("id > 0", name="positive"),
    )
    cks = [c for c in t.constraints if isinstance(c, CheckConstraint)]
    assert len(cks) == 1
    assert str(cks[0].name) == "ck_widgets_positive"
