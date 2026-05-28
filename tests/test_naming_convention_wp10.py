"""v2.11-WP10 (Bucket C4) — SQLAlchemy ``naming_convention`` regression.

Background
----------
v2.10-WP06 uncovered a production migration bug where
``op.create_foreign_key(None, ...)`` deferred the constraint name to
postgres' default (``problems_domain_id_fkey``), making the matching
``op.drop_constraint(None, ...)`` on downgrade unrunnable
(``CompileError: Can't emit DROP CONSTRAINT for constraint ... it has no
name``).

WP10 closes the upstream hole by pinning a deterministic
``naming_convention`` on the project's ``MetaData``. From now on any
constraint declared without an explicit ``name=`` gets a stable name
(``fk_<table>_<col>_<reftable>``, ``uq_<table>_<col>``, etc.) — both at
ORM ``create_all`` time and through alembic autogenerate.

This test is the static guard that ``Base.metadata`` ships with the
agreed-on convention and that the convention actually fires when an
unnamed constraint is declared.
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql  # noqa: F401 — ensures dialect imports

from app.database import NAMING_CONVENTION, Base


def test_base_metadata_has_naming_convention():
    """``Base.metadata.naming_convention`` exposes the expected keys.

    SQLAlchemy stores the convention on the ``MetaData`` object so the
    DDL compiler can substitute it whenever a constraint is rendered
    without an explicit name. Asserting equality on the dict catches
    drift in either direction (someone deleting a key, or someone
    silently changing the templates).
    """
    # v2.13-WP02 (Bucket A1): ``ck`` resurrected. Model files declare
    # bare short names (``name="positive"``) and the convention renders
    # ``ck_<table>_positive``. Alembic migration files that carry the
    # historical FULL ``ck_<table>_<short>`` literals are wrapped with
    # ``sqlalchemy.sql.elements.conv(...)`` to short-circuit the
    # substitution. See ``tests/test_ck_naming_convention_wp02_v213.py``
    # for the per-model emission guard.
    expected = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
    }
    assert dict(Base.metadata.naming_convention) == expected
    # The module-level constant must match too — both are imported
    # callers (tests, alembic env, future code).
    assert NAMING_CONVENTION == expected


def test_unnamed_unique_constraint_gets_uq_prefix():
    """An unnamed ``UniqueConstraint`` on a table bound to a metadata
    with the convention resolves to ``uq_<table>_<column>``.

    This is the smoke check that the convention is actually wired into
    DDL compilation. We attach to a fresh ``MetaData`` configured with
    the same convention (so we don't pollute ``Base.metadata`` with a
    throwaway table) — both `MetaData` objects share the convention so
    the resolved name proves the templates are valid.
    """
    md = MetaData(naming_convention=NAMING_CONVENTION)
    t = Table(
        "widgets",
        md,
        Column("id", Integer, primary_key=True),
        Column("sku", Integer),
        UniqueConstraint("sku"),  # no explicit name=
    )
    # Resolve the first non-PK unique constraint and verify its compiled
    # name. SQLAlchemy resolves the templated name lazily when the
    # constraint is asked for its ``.name`` after being bound.
    uniques = [c for c in t.constraints if isinstance(c, UniqueConstraint)]
    assert len(uniques) == 1
    assert str(uniques[0].name) == "uq_widgets_sku"


def test_unnamed_foreign_key_gets_fk_prefix():
    """An inline ``ForeignKey`` on an unnamed column resolves to
    ``fk_<table>_<col>_<reftable>``.

    Mirrors the production case the v2.10-WP06 ``None`` bug would have
    triggered: a fresh ``op.create_foreign_key(None, 'problems',
    'domains', ['domain_id'], ['id'])`` now picks up
    ``fk_problems_domain_id_domains`` automatically.
    """
    md = MetaData(naming_convention=NAMING_CONVENTION)
    parent = Table(
        "domains",
        md,
        Column("id", Integer, primary_key=True),
    )
    child = Table(
        "problems",
        md,
        Column("id", Integer, primary_key=True),
        Column("domain_id", Integer, ForeignKey("domains.id")),
    )
    # The FK lives on the ``domain_id`` column. Its compiled constraint
    # name should follow the ``fk_<table>_<col>_<reftable>`` template.
    fk_constraint = list(child.c.domain_id.foreign_keys)[0].constraint
    assert str(fk_constraint.name) == "fk_problems_domain_id_domains"
    # Sanity-check the parent ref wired correctly.
    assert parent.name == "domains"
