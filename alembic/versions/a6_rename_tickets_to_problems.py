"""Step 1: rename tickets table back to problems.

Revision ID: a6_rename_tickets_to_problems
Revises: a5_agent_kanban
Create Date: 2026-05-16

Migration a1_agent_kanban renamed ``problems`` -> ``tickets`` to repurpose the
table for the new Kanban entity. That was the wrong call: the legacy bulletin
domain still owns this row shape, and the Kanban work-tracker needs a fresh
table later (Step 2). This migration partially reverts a1 by renaming the
physical table back to ``problems`` (and ripple-renaming related FK columns,
indexes, constraints, and the seq sequence) WITHOUT removing the Kanban-era
columns. Both the ``Problem`` and ``Ticket`` ORM classes continue to map this
single ``problems`` table.

Surface changes:
- Rename table ``tickets`` -> ``problems``.
- Rename FK column ``ticket_id`` -> ``problem_id`` in ``ticket_comments`` and
  ``ticket_transitions`` (these point at the renamed table).
- Rename related indexes/constraints from ``*tickets*`` to ``*problems*``.
- Rename Postgres sequence ``tickets_seq_number_seq`` -> ``problems_seq_number_seq``.
- ``ticket_links.source_id`` / ``target_id`` keep their names; only the FK
  target reference changes (renamed implicitly by ``rename_table``).
- Polymorphic ``attachments.parent_id`` and ``audit_log.entity_id`` are
  untouched (they are not FKs to this table).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a6_rename_tickets_to_problems"
down_revision: Union[str, None] = "a5_agent_kanban"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename the table itself. PG cascades the FK references to the new
    #    name automatically; we only need to rename objects whose names embed
    #    the old table name.
    op.rename_table("tickets", "problems")

    # 2. Rename FK columns ticket_id -> problem_id in dependent kanban tables.
    op.alter_column(
        "ticket_comments", "ticket_id", new_column_name="problem_id"
    )
    op.alter_column(
        "ticket_transitions", "ticket_id", new_column_name="problem_id"
    )

    # 3. Rename indexes/constraints from tickets-* to problems-*.
    op.execute("ALTER INDEX IF EXISTS ix_tickets_search_vector RENAME TO ix_problems_search_vector")
    op.execute("ALTER INDEX IF EXISTS ix_tickets_seq_number RENAME TO ix_problems_seq_number")
    op.execute("ALTER INDEX IF EXISTS gin_tickets_labels RENAME TO gin_problems_labels")
    op.execute("ALTER INDEX IF EXISTS gin_tickets_search_tsv RENAME TO gin_problems_search_tsv")
    op.execute("ALTER INDEX IF EXISTS gin_tickets_custom_fields RENAME TO gin_problems_custom_fields")
    op.execute("ALTER INDEX IF EXISTS ix_tickets_status_assignee RENAME TO ix_problems_status_assignee")
    op.execute("ALTER INDEX IF EXISTS ix_tickets_parent_id RENAME TO ix_problems_parent_id")
    op.execute("ALTER INDEX IF EXISTS ix_tickets_updated_at RENAME TO ix_problems_updated_at")
    # Primary key index auto-named tickets_pkey -> problems_pkey.
    op.execute("ALTER INDEX IF EXISTS tickets_pkey RENAME TO problems_pkey")

    # Rename CHECK / FK constraints from ck_tickets_* / fk_tickets_* to
    # ck_problems_* / fk_problems_*. ALTER TABLE ... RENAME CONSTRAINT is safe
    # because the table has been renamed by step 1.
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_tickets_assignee_pair TO ck_problems_assignee_pair")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_tickets_assignee_type TO ck_problems_assignee_type")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_tickets_reporter_type TO ck_problems_reporter_type")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_tickets_custom_fields_object TO ck_problems_custom_fields_object")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_tickets_hierarchy_no_self TO ck_problems_hierarchy_no_self")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT fk_tickets_parent_id TO fk_problems_parent_id")

    # Rename ix_ticket_comments_ticket_created -> ix_ticket_comments_problem_created
    # (the column it indexes was just renamed).
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_comments_ticket_created "
        "RENAME TO ix_ticket_comments_problem_created"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_transitions_ticket_created "
        "RENAME TO ix_ticket_transitions_problem_created"
    )

    # 4. Rename the seq_number sequence.
    op.execute("ALTER SEQUENCE IF EXISTS tickets_seq_number_seq RENAME TO problems_seq_number_seq")


def downgrade() -> None:
    op.execute("ALTER SEQUENCE IF EXISTS problems_seq_number_seq RENAME TO tickets_seq_number_seq")

    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_transitions_problem_created "
        "RENAME TO ix_ticket_transitions_ticket_created"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_comments_problem_created "
        "RENAME TO ix_ticket_comments_ticket_created"
    )

    op.execute("ALTER TABLE problems RENAME CONSTRAINT fk_problems_parent_id TO fk_tickets_parent_id")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_problems_hierarchy_no_self TO ck_tickets_hierarchy_no_self")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_problems_custom_fields_object TO ck_tickets_custom_fields_object")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_problems_reporter_type TO ck_tickets_reporter_type")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_problems_assignee_type TO ck_tickets_assignee_type")
    op.execute("ALTER TABLE problems RENAME CONSTRAINT ck_problems_assignee_pair TO ck_tickets_assignee_pair")

    op.execute("ALTER INDEX IF EXISTS problems_pkey RENAME TO tickets_pkey")
    op.execute("ALTER INDEX IF EXISTS ix_problems_updated_at RENAME TO ix_tickets_updated_at")
    op.execute("ALTER INDEX IF EXISTS ix_problems_parent_id RENAME TO ix_tickets_parent_id")
    op.execute("ALTER INDEX IF EXISTS ix_problems_status_assignee RENAME TO ix_tickets_status_assignee")
    op.execute("ALTER INDEX IF EXISTS gin_problems_custom_fields RENAME TO gin_tickets_custom_fields")
    op.execute("ALTER INDEX IF EXISTS gin_problems_search_tsv RENAME TO gin_tickets_search_tsv")
    op.execute("ALTER INDEX IF EXISTS gin_problems_labels RENAME TO gin_tickets_labels")
    op.execute("ALTER INDEX IF EXISTS ix_problems_seq_number RENAME TO ix_tickets_seq_number")
    op.execute("ALTER INDEX IF EXISTS ix_problems_search_vector RENAME TO ix_tickets_search_vector")

    op.alter_column(
        "ticket_transitions", "problem_id", new_column_name="ticket_id"
    )
    op.alter_column(
        "ticket_comments", "problem_id", new_column_name="ticket_id"
    )

    op.rename_table("problems", "tickets")
