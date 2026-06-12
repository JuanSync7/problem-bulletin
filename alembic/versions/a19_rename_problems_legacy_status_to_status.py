"""v2.11-WP15: rename problems.legacy_status back to problems.status.

Revision ID: a19_problems_status_rename
Revises: a18_project_coalesce_seconds
Create Date: 2026-05-22

Background
----------
Migration ``a1_agent_kanban_rename_problems_to_tickets`` renamed the
``problems.status`` column to ``problems.legacy_status`` to make room for a
new enum-typed ``status`` column on the (then-being-created) tickets table.
The ORM mapping in ``app/models/problem.py`` retained the Python attribute
``Problem.status`` but bound it to the renamed DB column via the explicit
column override ``Column("legacy_status", ...)``.

The asymmetry between Python attribute (``status``) and DB column
(``legacy_status``) has been a persistent footgun for raw-SQL call sites
(v2.10-WP04b fixed one, v2.11-WP02 swept the rest and pinned a regression
lint). Bucket E2 of the v2.11 plan closes the asymmetry by renaming the
DB column back to ``status``.

By the time this migration runs, the work-tracker ``tickets`` table is a
*separate* physical table (split off in ``a8_finalize_ticket_split``), so
there is no longer any collision between ``problems.status`` (string) and
``tickets.status`` (enum). The original reason for the legacy_status hack
is gone — this migration removes the hack.

Scope of changes
----------------
- Rename column ``problems.legacy_status`` → ``problems.status``.
- The column type (TEXT/VARCHAR), nullability, and server_default are
  unchanged — only the name moves.
- No constraints reference ``legacy_status`` by name (verified via
  alembic migration history grep).
- No indexes reference ``legacy_status`` (the
  ``ix_problems_status_assignee`` index was dropped in
  ``a8_finalize_ticket_split`` and recreated against the new
  ``tickets.status`` enum column — it has no live binding to
  ``problems.legacy_status``).
- No generated columns or triggers reference ``legacy_status``
  (``problems.search_tsv`` is derived from ``title`` + ``description``
  only — verified in ``a4_agent_kanban_search_indexes``).

Reversibility
-------------
Downgrade renames the column back to ``legacy_status``. Roundtrip is
exercised by ``tests/migrations/test_migration_roundtrip.py::
test_each_agent_kanban_revision_is_reversible`` which walks the entire
chain down to base and back up to head.
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "a19_problems_status_rename"
down_revision = "a18_project_coalesce_seconds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "problems",
        "legacy_status",
        new_column_name="status",
    )


def downgrade() -> None:
    op.alter_column(
        "problems",
        "status",
        new_column_name="legacy_status",
    )
