"""A2a: pg_trgm extension + GIN trigram indexes for typeahead search.

Revision ID: z_pg_trgm_indexes
Revises: a20_ck_convention_alignment
Create Date: 2026-06-01

Adds:
- CREATE EXTENSION IF NOT EXISTS pg_trgm
- GIN trigram index on tickets.title
- GIN trigram index on problems.title
- GIN trigram index on components.name
- GIN trigram index on tags.name  (labels arm uses tags table)
- GIN trigram index on users.handle

Downgrade: DROP INDEX IF EXISTS for each (extension kept — removing it
could affect other installations using it; it is idempotent on re-create).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "z_pg_trgm_indexes"
down_revision: Union[str, None] = "a20_ck_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm is shipped with Postgres; IF NOT EXISTS makes it idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GIN indexes using gin_trgm_ops for trigram similarity queries.
    op.execute(
        "CREATE INDEX IF NOT EXISTS gin_tickets_title_trgm "
        "ON tickets USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gin_problems_title_trgm "
        "ON problems USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gin_components_name_trgm "
        "ON components USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gin_tags_name_trgm "
        "ON tags USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS gin_users_handle_trgm "
        "ON users USING gin (handle gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS gin_users_handle_trgm")
    op.execute("DROP INDEX IF EXISTS gin_tags_name_trgm")
    op.execute("DROP INDEX IF EXISTS gin_components_name_trgm")
    op.execute("DROP INDEX IF EXISTS gin_problems_title_trgm")
    op.execute("DROP INDEX IF EXISTS gin_tickets_title_trgm")
    # Extension intentionally not dropped — it may be used by other features.
