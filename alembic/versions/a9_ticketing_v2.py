"""Ticketing v2 — projects, sprints, components, watchers, attachments + ticket extensions.

Revision ID: a9_ticketing_v2
Revises: a8_finalize_ticket_split
Create Date: 2026-05-17

WP2 of the Ticketing v2 initiative. See docs/specs/ticketing-v2.md and
docs/adr/0001-ticketing-v2.md for the design.

Phases (all in this single migration — none of the new enum values are used
as a default in the same transaction, so we don't need to split on
``ALTER TYPE ADD VALUE`` semantics):

  A. Create new enums (``project_role``, ``sprint_state``) and new tables
     (``projects``, ``sprints``, ``components``, ``project_members``,
     ``ticket_watchers``, ``ticket_attachments``).
  B. Extend ``tickets``: drop the GENERATED ALWAYS ``display_id`` column,
     re-add as plain TEXT (nullable for backfill), then add
     ``project_id``, ``sprint_id``, ``component_id``, ``epic_id``,
     ``fix_versions``, ``resolution``, ``resolved_at``,
     ``created_agent_step_id``.
  C. Widen enums: ``ticket_type`` += workpackage; ``ticket_status`` +=
     backlog; ``ticket_link_type`` += clones, is_cloned_by. parent_of /
     child_of are TOMBSTONED (kept in the enum, refused by service layer).
  D. Add ``agent_step_id TEXT NULL`` + CHECK to audit-producing tables
     (``ticket_comments``, ``ticket_transitions``, ``ticket_links``,
     ``audit_log``). ``ticket_comments`` also gets ``mentions UUID[]``.
  E. Backfill: create Default project (key=DEF), create per-project
     SEQUENCE ``seq_def`` starting at max(seq_number)+1, set
     ``project_id = DEF`` on every existing ticket, set
     ``display_id = 'DEF-' || seq_number``, recursively backfill
     ``epic_id``. Then ALTER project_id / display_id to NOT NULL,
     add UNIQUE on display_id, add (project_id, seq_number) unique.
  F. Trigger ``trg_tickets_parent_same_project`` enforcing
     ``parent.project_id = NEW.project_id`` on INSERT/UPDATE. The
     parent-child type-rule trigger is deferred to WP3 service layer
     (see lessons-learned).

Downgrade is LOSSY: backfilled project_id, sprint_id, epic_id, etc. are
dropped. The Default project row is removed. display_id is re-added as a
plain TEXT column (we do NOT recreate the GENERATED ALWAYS expression —
WP2 documented this in the docstring; the old computed expression is
unrecoverable once the column has been replaced).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv  # v2.13-WP02: short-circuit ck convention
from sqlalchemy.dialects import postgresql


revision: str = "a9_ticketing_v2"
down_revision: Union[str, None] = "a8_finalize_ticket_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_PROJECT_KEY = "DEF"
DEFAULT_PROJECT_NAME = "Default"
DEFAULT_PROJECT_SEQUENCE = "seq_def"  # lowercased key — see lessons-learned

NEW_TICKET_TYPES = ("workpackage",)
NEW_TICKET_STATUSES = ("backlog",)
NEW_TICKET_LINK_TYPES = ("clones", "is_cloned_by")


def _add_enum_value(enum_name: str, value: str) -> None:
    """Idempotent ALTER TYPE ... ADD VALUE."""
    op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # Phase C (first) — widen existing enums. PG requires ALTER TYPE
    # ADD VALUE outside the transaction that uses the new value as a
    # default. We do not use any of them as defaults in this migration,
    # so a single transaction is fine, but we run the ADDs early so any
    # later default expression that does name them would still work.
    # ------------------------------------------------------------------
    for v in NEW_TICKET_TYPES:
        _add_enum_value("ticket_type", v)
    for v in NEW_TICKET_STATUSES:
        _add_enum_value("ticket_status", v)
    for v in NEW_TICKET_LINK_TYPES:
        _add_enum_value("ticket_link_type", v)

    # ------------------------------------------------------------------
    # Phase A — new enums + new tables
    # ------------------------------------------------------------------
    project_role = postgresql.ENUM(
        "lead", "member", "viewer", name="project_role"
    )
    project_role.create(bind, checkfirst=True)

    sprint_state = postgresql.ENUM(
        "planned", "active", "closed", name="sprint_state"
    )
    sprint_state.create(bind, checkfirst=True)

    # projects ----------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_type", sa.Text(), nullable=True),
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "wip_limits",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint("key", name="uq_projects_key"),
        sa.CheckConstraint(
            "key ~ '^[A-Z][A-Z0-9]{1,9}$'",
            name=conv("ck_projects_key_format"),
        ),
        sa.CheckConstraint(
            "lead_type IS NULL OR lead_type IN ('user','agent')",
            name=conv("ck_projects_lead_type"),
        ),
        sa.CheckConstraint(
            "(lead_id IS NULL AND lead_type IS NULL) OR "
            "(lead_id IS NOT NULL AND lead_type IS NOT NULL)",
            name=conv("ck_projects_lead_pair"),
        ),
    )
    op.create_index(
        "ix_projects_archived",
        "projects",
        ["archived"],
        postgresql_where=sa.text("archived = false"),
    )

    # sprints -----------------------------------------------------------
    op.create_table(
        "sprints",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_sprints_project_id",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(name="sprint_state", create_type=False),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
            name=conv("ck_sprints_date_order"),
        ),
    )
    op.create_index("ix_sprints_project_id", "sprints", ["project_id"])
    op.create_index(
        "uq_sprints_active_per_project",
        "sprints",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # components --------------------------------------------------------
    op.create_table(
        "components",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_components_project_id",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_type", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_components_project_name"
        ),
        sa.CheckConstraint(
            "lead_type IS NULL OR lead_type IN ('user','agent')",
            name=conv("ck_components_lead_type"),
        ),
    )

    # project_members ---------------------------------------------------
    op.create_table(
        "project_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="CASCADE",
                name="fk_project_members_project_id",
            ),
            nullable=False,
        ),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_type", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="project_role", create_type=False),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "member_id",
            "member_type",
            name="uq_project_members",
        ),
        sa.CheckConstraint(
            "member_type IN ('user','agent')",
            name=conv("ck_project_members_member_type"),
        ),
    )

    # ticket_watchers ---------------------------------------------------
    op.create_table(
        "ticket_watchers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tickets.id",
                ondelete="CASCADE",
                name="fk_ticket_watchers_ticket_id",
            ),
            nullable=False,
        ),
        sa.Column("watcher_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("watcher_type", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "ticket_id",
            "watcher_id",
            "watcher_type",
            name="uq_ticket_watchers",
        ),
        sa.CheckConstraint(
            "watcher_type IN ('user','agent')",
            name=conv("ck_ticket_watchers_watcher_type"),
        ),
    )
    op.create_index(
        "ix_ticket_watchers_watcher",
        "ticket_watchers",
        ["watcher_id", "watcher_type"],
    )

    # ticket_attachments -----------------------------------------------
    op.create_table(
        "ticket_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tickets.id",
                ondelete="CASCADE",
                name="fk_ticket_attachments_ticket_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("uploaded_by_type", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("agent_step_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "uploaded_by_type IN ('user','agent')",
            name=conv("ck_ticket_attachments_uploaded_by_type"),
        ),
        sa.CheckConstraint(
            "uploaded_by_type = 'agent' OR agent_step_id IS NULL",
            name=conv("ck_ticket_attachments_agent_step_id"),
        ),
    )
    op.create_index(
        "ix_ticket_attachments_ticket_id",
        "ticket_attachments",
        ["ticket_id"],
    )

    # ------------------------------------------------------------------
    # Phase B — extend ``tickets``
    # ------------------------------------------------------------------
    # Drop the GENERATED ALWAYS display_id and re-add as plain TEXT,
    # nullable for now; we backfill in Phase E and then set NOT NULL.
    op.execute("ALTER TABLE tickets DROP COLUMN display_id")
    op.add_column(
        "tickets", sa.Column("display_id", sa.Text(), nullable=True)
    )

    op.add_column(
        "tickets",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("sprint_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "component_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("epic_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column(
            "fix_versions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "tickets", sa.Column("resolution", sa.Text(), nullable=True)
    )
    op.add_column(
        "tickets",
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "tickets",
        sa.Column("created_agent_step_id", sa.Text(), nullable=True),
    )
    # The agent_step_id on ``tickets`` itself is a *create-only* audit
    # column — actor identity at create time. The CHECK gates against
    # reporter_type (the create-side actor).
    op.create_check_constraint(
        conv("ck_tickets_created_agent_step_id"),
        "tickets",
        "reporter_type = 'agent' OR created_agent_step_id IS NULL",
    )

    # FKs (RESTRICT on project, SET NULL on the rest per Cross-WP Rule 7)
    op.create_foreign_key(
        "fk_tickets_project_id",
        "tickets",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_tickets_sprint_id",
        "tickets",
        "sprints",
        ["sprint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tickets_component_id",
        "tickets",
        "components",
        ["component_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tickets_epic_id",
        "tickets",
        "tickets",
        ["epic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_tickets_project_id", "tickets", ["project_id"])
    op.create_index(
        "ix_tickets_sprint_id",
        "tickets",
        ["sprint_id"],
        postgresql_where=sa.text("sprint_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tickets_epic_id",
        "tickets",
        ["epic_id"],
        postgresql_where=sa.text("epic_id IS NOT NULL"),
    )
    op.create_index(
        "ix_tickets_component_id", "tickets", ["component_id"]
    )
    op.create_index(
        "gin_tickets_fix_versions",
        "tickets",
        ["fix_versions"],
        postgresql_using="gin",
    )

    # subtask MUST have a parent (DB-level enforceable subset of the
    # parenting matrix; full parent-type rule is service+trigger).
    op.create_check_constraint(
        conv("ck_tickets_subtask_has_parent"),
        "tickets",
        "type <> 'subtask' OR parent_id IS NOT NULL",
    )

    # ------------------------------------------------------------------
    # Phase D — add ``agent_step_id`` + CHECK to audit-producing tables
    # ------------------------------------------------------------------
    # ticket_comments
    op.add_column(
        "ticket_comments",
        sa.Column("agent_step_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        conv("ck_ticket_comments_agent_step_id"),
        "ticket_comments",
        "author_type = 'agent' OR agent_step_id IS NULL",
    )
    # mentions: array of UUIDs (no FK — soft references).
    op.add_column(
        "ticket_comments",
        sa.Column(
            "mentions",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )

    # ticket_transitions
    op.add_column(
        "ticket_transitions",
        sa.Column("agent_step_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        conv("ck_ticket_transitions_agent_step_id"),
        "ticket_transitions",
        "actor_type = 'agent' OR agent_step_id IS NULL",
    )

    # ticket_links
    op.add_column(
        "ticket_links",
        sa.Column("agent_step_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        conv("ck_ticket_links_agent_step_id"),
        "ticket_links",
        "created_by_type = 'agent' OR agent_step_id IS NULL",
    )

    # audit_log (the agent-kanban append-only event table)
    op.add_column(
        "audit_log",
        sa.Column("agent_step_id", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        conv("ck_audit_log_agent_step_id"),
        "audit_log",
        "actor_type = 'agent' OR agent_step_id IS NULL",
    )

    # ------------------------------------------------------------------
    # Phase E — backfill
    # ------------------------------------------------------------------
    # 1. Create Default project (deterministic UUID for ergonomics).
    op.execute(
        f"""
        INSERT INTO projects (id, key, name, description, archived, wip_limits, version)
        VALUES (
            gen_random_uuid(),
            '{DEFAULT_PROJECT_KEY}',
            '{DEFAULT_PROJECT_NAME}',
            'Auto-created in a9_ticketing_v2 for pre-v2 tickets.',
            false,
            '{{}}'::jsonb,
            1
        )
        """
    )

    # 2. Create the per-project sequence at max(seq_number)+1. If the
    # tickets table is empty, start at 1.
    op.execute(
        f"""
        DO $$
        DECLARE
            max_seq INTEGER;
        BEGIN
            SELECT COALESCE(MAX(seq_number), 0) INTO max_seq FROM tickets;
            EXECUTE format(
                'CREATE SEQUENCE IF NOT EXISTS {DEFAULT_PROJECT_SEQUENCE} START WITH %s',
                GREATEST(max_seq + 1, 1)
            );
        END$$;
        """
    )

    # 3. Backfill project_id and display_id on every existing ticket.
    op.execute(
        f"""
        UPDATE tickets
        SET project_id = (SELECT id FROM projects WHERE key = '{DEFAULT_PROJECT_KEY}'),
            display_id = '{DEFAULT_PROJECT_KEY}-' || seq_number::text
        WHERE project_id IS NULL
        """
    )

    # 4. Recursive backfill of epic_id: walk parent_id chain until we hit
    # a row with type='epic'. Sets NULL when no ancestor epic exists.
    op.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT id, parent_id, type, id AS start_id
              FROM tickets
             WHERE parent_id IS NOT NULL
            UNION ALL
            SELECT t.id, t.parent_id, t.type, c.start_id
              FROM tickets t
              JOIN chain c ON t.id = c.parent_id
        ),
        found AS (
            SELECT start_id, MIN(id::text) AS epic_id_text
              FROM chain
             WHERE type = 'epic'
             GROUP BY start_id
        )
        UPDATE tickets t
           SET epic_id = f.epic_id_text::uuid
          FROM found f
         WHERE t.id = f.start_id
        """
    )

    # 5. Lock down: project_id + display_id NOT NULL, display_id UNIQUE,
    # (project_id, seq_number) UNIQUE (replaces global seq_number unique).
    op.alter_column("tickets", "project_id", nullable=False)
    op.alter_column("tickets", "display_id", nullable=False)
    op.create_unique_constraint(
        "uq_tickets_display_id", "tickets", ["display_id"]
    )
    op.create_unique_constraint(
        "uq_tickets_project_seq",
        "tickets",
        ["project_id", "seq_number"],
    )

    # ------------------------------------------------------------------
    # Phase F — trigger enforcing parent.project_id = NEW.project_id
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_tickets_same_project_fn()
        RETURNS trigger AS $$
        DECLARE
            parent_project UUID;
        BEGIN
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT project_id INTO parent_project FROM tickets WHERE id = NEW.parent_id;
            IF parent_project IS NULL THEN
                RETURN NEW;  -- parent row missing; FK will fail separately
            END IF;
            IF parent_project <> NEW.project_id THEN
                RAISE EXCEPTION 'ck_tickets_parent_same_project: parent.project_id (%) <> child.project_id (%)',
                    parent_project, NEW.project_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tickets_same_project
        BEFORE INSERT OR UPDATE OF parent_id, project_id
        ON tickets
        FOR EACH ROW
        EXECUTE FUNCTION trg_tickets_same_project_fn();
        """
    )

    # NOTE: the parent-child *type* rule (parenting matrix §3) is not
    # enforced at the DB level here. It is left to WP3's service layer.
    # See lessons-learned for the rationale.


def downgrade() -> None:
    """Reverse a9. Lossy on the v2 columns/rows."""
    bind = op.get_bind()

    # Phase F reverse
    op.execute("DROP TRIGGER IF EXISTS trg_tickets_same_project ON tickets")
    op.execute("DROP FUNCTION IF EXISTS trg_tickets_same_project_fn()")

    # Phase E reverse — drop the v2 uniqueness; let display_id go back
    # to nullable so we can swap it for the plain text column shape.
    op.drop_constraint(
        "uq_tickets_project_seq", "tickets", type_="unique"
    )
    op.drop_constraint(
        "uq_tickets_display_id", "tickets", type_="unique"
    )

    # Phase D reverse
    op.drop_constraint(
        conv("ck_audit_log_agent_step_id"), "audit_log", type_="check"
    )
    op.drop_column("audit_log", "agent_step_id")

    op.drop_constraint(
        conv("ck_ticket_links_agent_step_id"), "ticket_links", type_="check"
    )
    op.drop_column("ticket_links", "agent_step_id")

    op.drop_constraint(
        conv("ck_ticket_transitions_agent_step_id"),
        "ticket_transitions",
        type_="check",
    )
    op.drop_column("ticket_transitions", "agent_step_id")

    op.drop_column("ticket_comments", "mentions")
    op.drop_constraint(
        conv("ck_ticket_comments_agent_step_id"),
        "ticket_comments",
        type_="check",
    )
    op.drop_column("ticket_comments", "agent_step_id")

    # Phase B reverse
    op.drop_constraint(
        conv("ck_tickets_subtask_has_parent"), "tickets", type_="check"
    )
    op.drop_index("gin_tickets_fix_versions", table_name="tickets")
    op.drop_index("ix_tickets_component_id", table_name="tickets")
    op.drop_index("ix_tickets_epic_id", table_name="tickets")
    op.drop_index("ix_tickets_sprint_id", table_name="tickets")
    op.drop_index("ix_tickets_project_id", table_name="tickets")

    op.drop_constraint("fk_tickets_epic_id", "tickets", type_="foreignkey")
    op.drop_constraint(
        "fk_tickets_component_id", "tickets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_tickets_sprint_id", "tickets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_tickets_project_id", "tickets", type_="foreignkey"
    )

    op.drop_constraint(
        conv("ck_tickets_created_agent_step_id"), "tickets", type_="check"
    )
    op.drop_column("tickets", "created_agent_step_id")
    op.drop_column("tickets", "resolved_at")
    op.drop_column("tickets", "resolution")
    op.drop_column("tickets", "fix_versions")
    op.drop_column("tickets", "epic_id")
    op.drop_column("tickets", "component_id")
    op.drop_column("tickets", "sprint_id")
    op.drop_column("tickets", "project_id")
    op.drop_column("tickets", "display_id")

    # Re-add the plain ``display_id`` (was previously GENERATED ALWAYS,
    # but we cannot recreate the GENERATED expression because the column
    # has been gone in v2; documented in module docstring).
    op.add_column(
        "tickets",
        sa.Column("display_id", sa.Text(), nullable=True),
    )

    # Drop the per-project sequence + Default project row.
    op.execute(f"DROP SEQUENCE IF EXISTS {DEFAULT_PROJECT_SEQUENCE}")

    # Phase A reverse — drop new tables in FK-order.
    op.drop_index(
        "ix_ticket_attachments_ticket_id", table_name="ticket_attachments"
    )
    op.drop_table("ticket_attachments")

    op.drop_index("ix_ticket_watchers_watcher", table_name="ticket_watchers")
    op.drop_table("ticket_watchers")

    op.drop_table("project_members")
    op.drop_table("components")

    op.drop_index("uq_sprints_active_per_project", table_name="sprints")
    op.drop_index("ix_sprints_project_id", table_name="sprints")
    op.drop_table("sprints")

    op.drop_index("ix_projects_archived", table_name="projects")
    op.drop_table("projects")

    postgresql.ENUM(name="sprint_state").drop(bind, checkfirst=True)
    postgresql.ENUM(name="project_role").drop(bind, checkfirst=True)

    # Phase C reverse: ALTER TYPE ... DROP VALUE is unsupported on most
    # PG versions and we have no rows using these new values pre-upgrade
    # (downgrade clears them by dropping the dependent columns/tables).
    # We deliberately leave the enum values in place — tombstoned, as
    # per Cross-WP Rule 3.
