"""v2.13-WP02: ck naming_convention live as of this revision.

Revision ID: a20_ck_convention_alignment
Revises: a19_problems_status_rename
Create Date: 2026-05-25

Marker migration that documents the boundary at which the
``ck`` key was resurrected in ``Base.metadata.naming_convention``.

Background
----------
v2.11-WP10 pinned ``ix``/``uq``/``fk``/``pk`` keys on the project's
``MetaData``. The ``ck`` key was deferred because every pre-WP10
``CheckConstraint(name=...)`` in the repo passed the FULL already-
prefixed name (``name="ck_<table>_<short>"``), which would double-
wrap to ``ck_<table>_ck_<table>_<short>`` under the idiomatic template
``"ck_%(table_name)s_%(constraint_name)s"``.

v2.12-WP08 ported every model-side ``CheckConstraint`` to a bare
short name (``name="<short>"``) and started wrapping alembic
migration name literals with ``sqlalchemy.sql.elements.conv(...)`` to
short-circuit the convention substitution. v2.12-WP08 was rate-
limited mid-flight.

v2.13-WP02 finishes the alembic sweep (44 sites across a3, a7, a8,
a9, a11) and flips the ``ck`` key live in ``app/database.py``.

Net effect on production postgres
---------------------------------
**Zero.** The convention output for a model-declared
``CheckConstraint(name="<short>")`` is ``ck_<table>_<short>`` — the
exact same string that alembic emits for the historical full-name
literals (preserved verbatim via the ``conv()`` wrapper). No
``ALTER TABLE RENAME CONSTRAINT`` is required.

This file therefore contains no DDL in either direction; it exists
solely as a queryable marker on the alembic timeline. A future
``grep alembic/versions/ -l ck_convention_alignment`` will identify
the exact revision at which the convention went live.

If anyone subsequently introduces a model-side
``CheckConstraint(name="ck_<table>_<short>")`` (the legacy pattern),
the pytest guard ``tests/test_ck_naming_convention_wp02_v213.py`` will
catch the double-wrap before merge.
"""
from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic. Note: alembic_version.version_num
# is VARCHAR(32), so the literal MUST be <=32 chars. ``a20_ck_alignment``
# is 17 chars — safe.
revision: str = "a20_ck_alignment"
down_revision: Union[str, None] = "a19_problems_status_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op. ck convention is a python-side / SQLAlchemy-side change
    only; on-disk constraint names are unchanged.

    See module docstring for the alignment proof.
    """


def downgrade() -> None:
    """No-op. Mirrors ``upgrade``."""
