from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.config import get_settings


# v2.11-WP10 (Bucket C4): pin a deterministic SQLAlchemy naming convention
# on the project ``MetaData`` so any constraint declared without an explicit
# ``name=`` gets a stable, postgres-portable name. This is *advisory* for
# existing constraints (whose authoritative names already live in alembic
# migration history — we do NOT rename what postgres already has), and
# binding for any *new* constraints added going forward.
#
# Without this, ``op.create_foreign_key(None, ...)`` auto-stubs would defer
# naming to postgres' default (``<table>_<col>_fkey``), which then cannot
# be reliably dropped by name on downgrade — the exact bug WP06 fixed in
# ``7f57993c9b09_add_domains_table_and_domain_id_to_.py``.
#
# Note on the ``ck`` (check-constraint) key: the SQLAlchemy idiomatic
# template is ``ck_%(table_name)s_%(constraint_name)s``, which assumes
# callers pass SHORT names (``name="positive_price"`` →
# ``ck_table_positive_price``). v2.11-WP10 deferred this key because
# every pre-WP10 ``CheckConstraint(name=...)`` in this repo passed the
# FULL name (``name="ck_projects_coalesce_seconds_range"``), and the
# template double-wraps to
# ``ck_projects_ck_projects_coalesce_seconds_range`` at DDL compile time.
#
# v2.12-WP08 ports every model-side ``CheckConstraint(name=...)`` to
# the short form (``name="coalesce_seconds_range"``) and resurrects the
# ``ck`` key. After the port, the convention output equals the existing
# DB-side full names — no rename of postgres constraints is required.
# A companion alembic migration ``a20_ck_constraint_renames`` carries
# an idempotent guarded ``ALTER ... RENAME CONSTRAINT`` as a safety
# net + future-drift guard. Alembic migration files
# (``alembic/versions/*.py``) still carry the historical literal full
# names; these don't go through the convention because
# ``op.create_check_constraint(name, table, sql)`` / ``op.drop_constraint(
# name, ...)`` emit ``name`` directly as a DDL identifier — only
# ``MetaData``-attached ``CheckConstraint`` instances run the
# substitution.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
    # v2.13-WP02: ck resurrected. Models declare bare short names
    # (``name="positive"``) and the convention renders
    # ``ck_<table>_positive``. Alembic migration files that carry
    # historical FULL ``ck_<table>_<short>`` literals MUST wrap them
    # with ``sqlalchemy.sql.elements.conv(...)`` to short-circuit the
    # substitution and emit the literal as-is.
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


engine = create_async_engine(
    get_settings().DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Local import to avoid a circular dep on app.events (which has none here,
    # but keep this defensive — events imports nothing from app).
    from app.events import flush_session_events, discard_session_events

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
            flush_session_events(session)
        except Exception:
            await session.rollback()
            discard_session_events(session)
            raise
