"""V8a: share_posts + share_post_votes — the Share space (v2.29-S3).

Revision ID: v8a
Revises: v7a_ticket_comment_parent
Create Date: 2026-06-12

Adds:
- ``share_posts`` — dual-author (user/agent) posts about agent/AI/LLM
  usage. tags TEXT[] DEFAULT '{}', optional FK links to tickets(id) and
  agent_run(id) (both ON DELETE SET NULL), denormalized ``upvotes``.
- ``share_post_votes`` — one row per (post, voter); UNIQUE on
  (post_id, voter_id, voter_type); CASCADE on post delete.
- BTREE index on share_posts(created_at DESC) for the newest-first feed.

Downgrade drops both tables (votes first).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.sql.elements import conv


revision: str = "v8a"
down_revision: Union[str, None] = "v7a_ticket_comment_parent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "share_posts",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "author_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name=conv("fk_share_posts_author_user_id_users"),
            ),
            nullable=True,
        ),
        sa.Column(
            "author_agent_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_accounts.id",
                ondelete="SET NULL",
                name=conv("fk_share_posts_author_agent_id_agent_accounts"),
            ),
            nullable=True,
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column(
            "ticket_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "tickets.id",
                ondelete="SET NULL",
                name=conv("fk_share_posts_ticket_id_tickets"),
            ),
            nullable=True,
        ),
        sa.Column(
            "agent_run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_run.id",
                ondelete="SET NULL",
                name=conv("fk_share_posts_agent_run_id_agent_run"),
            ),
            nullable=True,
        ),
        sa.Column(
            "upvotes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "source IN ('user','agent')",
            name=conv("ck_share_posts_source"),
        ),
    )
    op.create_index(
        "ix_share_posts_created_at",
        "share_posts",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "share_post_votes",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "post_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "share_posts.id",
                ondelete="CASCADE",
                name=conv("fk_share_post_votes_post_id_share_posts"),
            ),
            nullable=False,
        ),
        sa.Column("voter_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("voter_type", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "voter_type IN ('user','agent')",
            name=conv("ck_share_post_votes_voter_type"),
        ),
        sa.UniqueConstraint(
            "post_id",
            "voter_id",
            "voter_type",
            name=conv("uq_share_post_votes_post_voter"),
        ),
    )


def downgrade() -> None:
    op.drop_table("share_post_votes")
    op.drop_index("ix_share_posts_created_at", table_name="share_posts")
    op.drop_table("share_posts")
