"""agent-kanban A2: add agent_accounts and audit_log tables

Revision ID: a2_agent_kanban
Revises: a1_agent_kanban
Create Date: 2026-05-12

Creates:
- agent_accounts: API-keyed bot accounts (argon2id hash + prefix lookup)
- audit_log: append-only event journal with REVOKE UPDATE,DELETE
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a2_agent_kanban"
down_revision: Union[str, None] = "a1_agent_kanban"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column("api_key_prefix", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint("name", name="uq_agent_accounts_name"),
    )
    op.create_index(
        "ix_agent_accounts_api_key_prefix",
        "agent_accounts",
        ["api_key_prefix"],
        postgresql_where=sa.text("active = true AND revoked_at IS NULL"),
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column(
            "diff",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user','agent')", name="ck_audit_log_actor_type"
        ),
    )
    op.create_index(
        "ix_audit_log_entity",
        "audit_log",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_id", "created_at"])
    op.create_index("ix_audit_log_correlation", "audit_log", ["correlation_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")


def downgrade() -> None:
    # Re-grant before drop to avoid leaving stray ACL state.
    op.execute("GRANT UPDATE, DELETE ON audit_log TO PUBLIC")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_correlation", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(
        "ix_agent_accounts_api_key_prefix", table_name="agent_accounts"
    )
    op.drop_table("agent_accounts")
