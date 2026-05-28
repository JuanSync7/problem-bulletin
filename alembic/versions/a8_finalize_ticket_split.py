"""Step 3: finalize ticket split — delete legacy Ticket overlay, rename work_items -> tickets.

Revision ID: a8_finalize_ticket_split
Revises: a7_create_work_items
Create Date: 2026-05-16

Two-phase cleanup:

A) Demolish the legacy ``Ticket`` overlay on the ``problems`` table:
   - Drop legacy ticket-domain tables ``ticket_comments``, ``ticket_links``,
     ``ticket_transitions`` (the pre-Step-2 Kanban tables that were FK'd to
     ``problems``).
   - Drop the kanban-era columns that migration ``a1_agent_kanban`` grafted onto
     ``problems`` (``status``/``ticket_type``/``priority``/``parent_id``/
     ``reporter_id``/``reporter_type``/``assignee_id``/``assignee_type``/
     ``story_points``/``due_date``/``labels``/``custom_fields``/``version``/
     ``closed_at``/``key``/``search_tsv``). The ``Problem`` model never used any
     of these — its ``status`` attribute is mapped to the ``legacy_status``
     column which we KEEP.
   - Drop the indexes, check constraints, and FK that referenced those columns.
   - Drop the orphan sequence ``problems_seq_number_seq`` (renamed from
     ``tickets_seq_number_seq`` in Step 1; never used by the Problem code).
   - Drop the legacy enums ``ticket_priority`` and ``ticket_link_type``. The
     enums ``ticket_status`` and ``ticket_type`` are kept because the Step 2
     ``work_items`` table reuses both.

B) Rename ``work_items`` -> ``tickets`` and ripple-rename every related table,
   column, index, constraint, sequence, and enum:
   - Rename the enums ``work_item_priority`` -> ``ticket_priority`` and
     ``work_item_link_type`` -> ``ticket_link_type`` (the slots are now free
     thanks to phase A).
   - Rename the table ``work_items`` -> ``tickets``. The seq sequence and
     ``display_id`` generated-column expression both have to be re-bound to the
     new names. We rebuild the generated column with the new prefix ``'TKT-'``.
   - Rename ``work_item_comments`` -> ``ticket_comments``, column
     ``work_item_id`` -> ``ticket_id``. Same shape for ``work_item_transitions``
     and ``work_item_links``.

The downgrade reverses every step here, but it is LOSSY: the Step 2 work-item
rows survive a downgrade (renamed back to work_items), but legacy Ticket rows
that were dropped from ``problems`` are gone forever. That is an explicit
design choice: the legacy Ticket overlay was synthetic, never carried real
production data in the bulletin domain.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv  # v2.13-WP02: short-circuit ck convention
from sqlalchemy.dialects import postgresql


revision: str = "a8_finalize_ticket_split"
down_revision: Union[str, None] = "a7_create_work_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Values copied from a1_agent_kanban + a7 so the downgrade can recreate enums.
LEGACY_TICKET_PRIORITY = ("lowest", "low", "medium", "high", "highest")
LEGACY_TICKET_LINK_TYPE = ("blocks", "relates", "duplicates")

WORK_ITEM_PRIORITY = ("low", "medium", "high", "urgent")
WORK_ITEM_LINK_TYPE = (
    "blocks",
    "is_blocked_by",
    "duplicates",
    "is_duplicate_of",
    "relates_to",
    "parent_of",
    "child_of",
)


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # Phase A: demolish legacy Ticket overlay
    # ------------------------------------------------------------------

    # A.1 Drop legacy ticket-domain tables (pre-Step-2 Kanban tables FK'd to
    # problems). The Step 2 work-item tables are still named work_item_* at
    # this point — they'll be renamed in phase B.
    op.execute("DROP INDEX IF EXISTS ix_ticket_links_target")
    op.execute("DROP INDEX IF EXISTS ix_ticket_links_source")
    op.execute("DROP TABLE IF EXISTS ticket_links")

    op.execute("DROP INDEX IF EXISTS ix_ticket_transitions_problem_created")
    op.execute("DROP INDEX IF EXISTS ix_ticket_transitions_ticket_created")
    op.execute("DROP TABLE IF EXISTS ticket_transitions")

    op.execute("DROP INDEX IF EXISTS ix_ticket_comments_problem_created")
    op.execute("DROP INDEX IF EXISTS ix_ticket_comments_ticket_created")
    op.execute("DROP TABLE IF EXISTS ticket_comments")

    # A.2 Drop indexes on problems that exist solely for the legacy overlay.
    op.execute("DROP INDEX IF EXISTS gin_problems_labels")
    op.execute("DROP INDEX IF EXISTS gin_problems_search_tsv")
    op.execute("DROP INDEX IF EXISTS gin_problems_custom_fields")
    op.execute("DROP INDEX IF EXISTS ix_problems_status_assignee")
    op.execute("DROP INDEX IF EXISTS ix_problems_parent_id")
    op.execute("DROP INDEX IF EXISTS ix_problems_updated_at")

    # A.3 Drop check constraints + FK that reference legacy columns.
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS ck_problems_assignee_pair")
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS ck_problems_assignee_type")
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS ck_problems_reporter_type")
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS ck_problems_custom_fields_object")
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS ck_problems_hierarchy_no_self")
    op.execute("ALTER TABLE problems DROP CONSTRAINT IF EXISTS fk_problems_parent_id")

    # A.4 Drop legacy columns.
    for col in (
        "search_tsv",
        "key",
        "deleted_at",
        "closed_at",
        "version",
        "custom_fields",
        "labels",
        "due_date",
        "story_points",
        "parent_id",
        "assignee_type",
        "assignee_id",
        "reporter_type",
        "reporter_id",
        "status",
        "priority",
        "ticket_type",
    ):
        op.execute(f"ALTER TABLE problems DROP COLUMN IF EXISTS {col}")

    # A.5 Drop orphan sequence (Step 1 renamed tickets_seq_number_seq ->
    # problems_seq_number_seq; the Problem model never used it).
    op.execute("DROP SEQUENCE IF EXISTS problems_seq_number_seq")

    # A.6 Drop legacy-only enums. ticket_status and ticket_type are reused by
    # work_items so they stay.
    postgresql.ENUM(name="ticket_priority").drop(bind, checkfirst=True)
    postgresql.ENUM(name="ticket_link_type").drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # Phase B: rename work_items -> tickets (and dependents)
    # ------------------------------------------------------------------

    # B.1 Rename enums into the now-free slots.
    op.execute("ALTER TYPE work_item_priority RENAME TO ticket_priority")
    op.execute("ALTER TYPE work_item_link_type RENAME TO ticket_link_type")

    # B.2 Rename child tables FIRST so the FK parent rename in B.3 doesn't
    # leave dangling object names. PG cascades the FK definition itself.
    op.execute("ALTER TABLE work_item_comments RENAME TO ticket_comments")
    op.execute(
        "ALTER TABLE ticket_comments RENAME COLUMN work_item_id TO ticket_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_item_comments_work_item_created "
        "RENAME TO ix_ticket_comments_ticket_created"
    )
    op.execute(
        "ALTER TABLE ticket_comments RENAME CONSTRAINT "
        "ck_work_item_comments_author_type TO ck_ticket_comments_author_type"
    )
    op.execute(
        "ALTER INDEX IF EXISTS work_item_comments_pkey RENAME TO ticket_comments_pkey"
    )

    op.execute("ALTER TABLE work_item_transitions RENAME TO ticket_transitions")
    op.execute(
        "ALTER TABLE ticket_transitions RENAME COLUMN work_item_id TO ticket_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_item_transitions_work_item_created "
        "RENAME TO ix_ticket_transitions_ticket_created"
    )
    op.execute(
        "ALTER TABLE ticket_transitions RENAME CONSTRAINT "
        "ck_work_item_transitions_actor_type TO ck_ticket_transitions_actor_type"
    )
    op.execute(
        "ALTER INDEX IF EXISTS work_item_transitions_pkey RENAME TO ticket_transitions_pkey"
    )

    op.execute("ALTER TABLE work_item_links RENAME TO ticket_links")
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_item_links_source RENAME TO ix_ticket_links_source"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_item_links_target RENAME TO ix_ticket_links_target"
    )
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT uq_work_item_links TO uq_ticket_links"
    )
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT "
        "ck_work_item_links_no_self TO ck_ticket_links_no_self"
    )
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT "
        "ck_work_item_links_created_by_type TO ck_ticket_links_created_by_type"
    )
    op.execute(
        "ALTER INDEX IF EXISTS work_item_links_pkey RENAME TO ticket_links_pkey"
    )

    # B.3 Rename the main work_items table -> tickets and rebuild the
    # display_id generated column with the 'TKT-' prefix. search_tsv is
    # table-name-independent so we leave it intact.
    op.execute("ALTER TABLE work_items DROP COLUMN IF EXISTS display_id")

    op.execute("ALTER TABLE work_items RENAME TO tickets")
    op.execute("ALTER SEQUENCE work_items_seq_number_seq RENAME TO tickets_seq_number_seq")
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN seq_number SET DEFAULT "
        "nextval('tickets_seq_number_seq')"
    )

    op.execute(
        "ALTER TABLE tickets ADD COLUMN display_id TEXT "
        "GENERATED ALWAYS AS ('TKT-' || seq_number::text) STORED NOT NULL"
    )

    # B.4 Rename indexes/constraints from work_items_* / ix_work_items_* /
    # gin_work_items_*.
    op.execute("ALTER INDEX IF EXISTS work_items_pkey RENAME TO tickets_pkey")
    op.execute(
        "ALTER INDEX IF EXISTS uq_work_items_seq_number RENAME TO uq_tickets_seq_number"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_items_status_assignee "
        "RENAME TO ix_tickets_status_assignee"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_items_parent_id RENAME TO ix_tickets_parent_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_work_items_updated_at RENAME TO ix_tickets_updated_at"
    )
    op.execute("ALTER INDEX IF EXISTS gin_work_items_labels RENAME TO gin_tickets_labels")
    op.execute(
        "ALTER INDEX IF EXISTS gin_work_items_search_tsv RENAME TO gin_tickets_search_tsv"
    )
    op.execute(
        "ALTER INDEX IF EXISTS gin_work_items_custom_fields "
        "RENAME TO gin_tickets_custom_fields"
    )

    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_work_items_assignee_pair "
        "TO ck_tickets_assignee_pair"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_work_items_assignee_type "
        "TO ck_tickets_assignee_type"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_work_items_reporter_type "
        "TO ck_tickets_reporter_type"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_work_items_custom_fields_object "
        "TO ck_tickets_custom_fields_object"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_work_items_hierarchy_no_self "
        "TO ck_tickets_hierarchy_no_self"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT fk_work_items_parent_id "
        "TO fk_tickets_parent_id"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT fk_work_items_reporter_id "
        "TO fk_tickets_reporter_id"
    )


def downgrade() -> None:
    """Reverse a8. LOSSY: legacy Ticket rows dropped from ``problems`` are gone.

    We recreate the legacy-overlay schema scaffolding so the chain still walks
    backward, but rows added to ``problems`` after a8 has been applied lack
    the legacy ticket fields (their defaults will apply).
    """
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # Phase B reverse: tickets -> work_items
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT fk_tickets_reporter_id "
        "TO fk_work_items_reporter_id"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT fk_tickets_parent_id "
        "TO fk_work_items_parent_id"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_tickets_hierarchy_no_self "
        "TO ck_work_items_hierarchy_no_self"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_tickets_custom_fields_object "
        "TO ck_work_items_custom_fields_object"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_tickets_reporter_type "
        "TO ck_work_items_reporter_type"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_tickets_assignee_type "
        "TO ck_work_items_assignee_type"
    )
    op.execute(
        "ALTER TABLE tickets RENAME CONSTRAINT ck_tickets_assignee_pair "
        "TO ck_work_items_assignee_pair"
    )

    op.execute(
        "ALTER INDEX IF EXISTS gin_tickets_custom_fields "
        "RENAME TO gin_work_items_custom_fields"
    )
    op.execute(
        "ALTER INDEX IF EXISTS gin_tickets_search_tsv RENAME TO gin_work_items_search_tsv"
    )
    op.execute("ALTER INDEX IF EXISTS gin_tickets_labels RENAME TO gin_work_items_labels")
    op.execute(
        "ALTER INDEX IF EXISTS ix_tickets_updated_at RENAME TO ix_work_items_updated_at"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_tickets_parent_id RENAME TO ix_work_items_parent_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_tickets_status_assignee "
        "RENAME TO ix_work_items_status_assignee"
    )
    op.execute(
        "ALTER INDEX IF EXISTS uq_tickets_seq_number RENAME TO uq_work_items_seq_number"
    )
    op.execute("ALTER INDEX IF EXISTS tickets_pkey RENAME TO work_items_pkey")

    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS display_id")

    op.execute("ALTER SEQUENCE tickets_seq_number_seq RENAME TO work_items_seq_number_seq")
    op.execute("ALTER TABLE tickets RENAME TO work_items")
    op.execute(
        "ALTER TABLE work_items ALTER COLUMN seq_number SET DEFAULT "
        "nextval('work_items_seq_number_seq')"
    )
    op.execute(
        "ALTER TABLE work_items ADD COLUMN display_id TEXT "
        "GENERATED ALWAYS AS ('WI-' || seq_number::text) STORED NOT NULL"
    )

    # Child tables
    op.execute("ALTER INDEX IF EXISTS ticket_links_pkey RENAME TO work_item_links_pkey")
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT "
        "ck_ticket_links_created_by_type TO ck_work_item_links_created_by_type"
    )
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT "
        "ck_ticket_links_no_self TO ck_work_item_links_no_self"
    )
    op.execute(
        "ALTER TABLE ticket_links RENAME CONSTRAINT uq_ticket_links TO uq_work_item_links"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_links_target RENAME TO ix_work_item_links_target"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_links_source RENAME TO ix_work_item_links_source"
    )
    op.execute("ALTER TABLE ticket_links RENAME TO work_item_links")

    op.execute(
        "ALTER INDEX IF EXISTS ticket_transitions_pkey RENAME TO work_item_transitions_pkey"
    )
    op.execute(
        "ALTER TABLE ticket_transitions RENAME CONSTRAINT "
        "ck_ticket_transitions_actor_type TO ck_work_item_transitions_actor_type"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_transitions_ticket_created "
        "RENAME TO ix_work_item_transitions_work_item_created"
    )
    op.execute("ALTER TABLE ticket_transitions RENAME COLUMN ticket_id TO work_item_id")
    op.execute("ALTER TABLE ticket_transitions RENAME TO work_item_transitions")

    op.execute(
        "ALTER INDEX IF EXISTS ticket_comments_pkey RENAME TO work_item_comments_pkey"
    )
    op.execute(
        "ALTER TABLE ticket_comments RENAME CONSTRAINT "
        "ck_ticket_comments_author_type TO ck_work_item_comments_author_type"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ticket_comments_ticket_created "
        "RENAME TO ix_work_item_comments_work_item_created"
    )
    op.execute("ALTER TABLE ticket_comments RENAME COLUMN ticket_id TO work_item_id")
    op.execute("ALTER TABLE ticket_comments RENAME TO work_item_comments")

    op.execute("ALTER TYPE ticket_link_type RENAME TO work_item_link_type")
    op.execute("ALTER TYPE ticket_priority RENAME TO work_item_priority")

    # ------------------------------------------------------------------
    # Phase A reverse: recreate legacy enums + columns + sequence + tables
    # ------------------------------------------------------------------
    postgresql.ENUM(*LEGACY_TICKET_PRIORITY, name="ticket_priority").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*LEGACY_TICKET_LINK_TYPE, name="ticket_link_type").create(
        bind, checkfirst=True
    )

    # Re-add columns on problems (mirrors a1).
    op.add_column(
        "problems",
        sa.Column(
            "ticket_type",
            postgresql.ENUM(name="ticket_type", create_type=False),
            nullable=False,
            server_default="task",
        ),
    )
    op.add_column(
        "problems",
        sa.Column(
            "priority",
            postgresql.ENUM(name="ticket_priority", create_type=False),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "problems",
        sa.Column(
            "status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=False,
            server_default="todo",
        ),
    )
    op.add_column(
        "problems", sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("problems", sa.Column("reporter_type", sa.Text(), nullable=True))
    op.add_column(
        "problems", sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("problems", sa.Column("assignee_type", sa.Text(), nullable=True))
    op.add_column(
        "problems", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_problems_parent_id",
        "problems",
        "problems",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("problems", sa.Column("story_points", sa.Integer(), nullable=True))
    op.add_column("problems", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "problems",
        sa.Column(
            "labels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "problems",
        sa.Column(
            "custom_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "problems",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "problems",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "problems",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("problems", sa.Column("key", sa.Text(), nullable=True))

    op.create_check_constraint(
        conv("ck_problems_assignee_pair"),
        "problems",
        "(assignee_id IS NULL AND assignee_type IS NULL) OR "
        "(assignee_id IS NOT NULL AND assignee_type IS NOT NULL)",
    )
    op.create_check_constraint(
        conv("ck_problems_assignee_type"),
        "problems",
        "assignee_type IS NULL OR assignee_type IN ('user','agent')",
    )
    op.create_check_constraint(
        conv("ck_problems_reporter_type"),
        "problems",
        "reporter_type IS NULL OR reporter_type IN ('user','agent')",
    )
    op.create_check_constraint(
        conv("ck_problems_custom_fields_object"),
        "problems",
        "jsonb_typeof(custom_fields) = 'object'",
    )
    op.create_check_constraint(
        conv("ck_problems_hierarchy_no_self"),
        "problems",
        "parent_id IS NULL OR parent_id <> id",
    )

    op.execute(
        "ALTER TABLE problems ADD COLUMN search_tsv tsvector "
        "GENERATED ALWAYS AS ("
        "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
        "setweight(to_tsvector('english', coalesce(description, '')), 'B')"
        ") STORED"
    )
    op.create_index(
        "gin_problems_labels", "problems", ["labels"], postgresql_using="gin"
    )
    op.create_index(
        "gin_problems_search_tsv",
        "problems",
        ["search_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "gin_problems_custom_fields",
        "problems",
        ["custom_fields"],
        postgresql_using="gin",
        postgresql_ops={"custom_fields": "jsonb_path_ops"},
    )
    op.create_index(
        "ix_problems_status_assignee",
        "problems",
        ["status", "assignee_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_problems_parent_id",
        "problems",
        ["parent_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_problems_updated_at", "problems", [sa.text("updated_at DESC")]
    )

    op.execute("CREATE SEQUENCE IF NOT EXISTS problems_seq_number_seq")

    # Recreate legacy ticket-domain tables (FK'd to problems) — empty.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_comments (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            problem_id     UUID        NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
            author_id      UUID        NOT NULL,
            author_type    TEXT        NOT NULL CHECK (author_type IN ('user','agent')),
            body           TEXT        NOT NULL,
            correlation_id TEXT        NOT NULL DEFAULT '',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_comments_problem_created "
        "ON ticket_comments(problem_id, created_at ASC)"
    )

    op.create_table(
        "ticket_transitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "problem_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("problems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            postgresql.ENUM(name="ticket_status", create_type=False),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user','agent')",
            name=conv("ck_ticket_transitions_actor_type"),
        ),
    )
    op.create_index(
        "ix_ticket_transitions_problem_created",
        "ticket_transitions",
        ["problem_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "ticket_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("problems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("problems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "link_type",
            postgresql.ENUM(name="ticket_link_type", create_type=False),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_by_type",
            sa.Text(),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "source_id", "target_id", "link_type", name="uq_ticket_links"
        ),
        sa.CheckConstraint("source_id <> target_id", name=conv("ck_ticket_links_no_self")),
        sa.CheckConstraint(
            "created_by_type IN ('user','agent')",
            name=conv("ck_ticket_links_created_by_type"),
        ),
    )
    op.create_index("ix_ticket_links_source", "ticket_links", ["source_id"])
    op.create_index("ix_ticket_links_target", "ticket_links", ["target_id"])
