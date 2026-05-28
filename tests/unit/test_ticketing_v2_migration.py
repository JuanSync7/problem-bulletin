"""Live-DB smoke checks for the ``a9_ticketing_v2`` migration.

Skipped when Postgres is unreachable. The actual upgrade is expected to
have already been applied by the developer / CI before running this suite
(matches ``tests/migrations/test_migration_roundtrip.py``); we just
verify the resulting shape.
"""
from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest


_DEFAULT_URL = "postgresql+asyncpg://aion:changeme@localhost:5432/aion_bulletin"
TEST_DB_URL = os.getenv("PB_TEST_DATABASE_URL", _DEFAULT_URL)


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(_dsn(TEST_DB_URL))


async def _check_db() -> bool:
    try:
        c = await _connect()
        await c.execute("SELECT 1")
        await c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not asyncio.run(_check_db()),
    reason=f"live postgres unreachable at {TEST_DB_URL}",
)


async def _scalar(sql: str):
    conn = await _connect()
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


async def _fetch(sql: str):
    conn = await _connect()
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


def test_default_project_row_exists():
    """The Default project (key=DEF) is created by the migration backfill."""
    row = asyncio.run(_fetch("SELECT key, name FROM projects WHERE key = 'DEF'"))
    assert len(row) == 1
    assert row[0]["name"] == "Default"


def test_seq_def_sequence_exists():
    """Per-project sequence ``seq_def`` is created for the Default project."""
    count = asyncio.run(
        _scalar(
            "SELECT count(*) FROM pg_class "
            "WHERE relkind = 'S' AND relname = 'seq_def'"
        )
    )
    assert count == 1


def test_every_pre_v2_ticket_has_default_project_id():
    """Backfill: tickets.project_id is the Default project for all rows."""
    bad = asyncio.run(
        _scalar(
            "SELECT count(*) FROM tickets WHERE project_id IS NULL"
        )
    )
    assert bad == 0
    # And they all point at the DEF project specifically.
    misaligned = asyncio.run(
        _scalar(
            "SELECT count(*) FROM tickets t "
            "JOIN projects p ON p.id = t.project_id "
            "WHERE p.key <> 'DEF'"
        )
    )
    assert misaligned == 0


def test_every_pre_v2_ticket_has_def_display_id():
    """Backfill: tickets.display_id = 'DEF-<seq_number>' for all rows."""
    bad = asyncio.run(
        _scalar(
            "SELECT count(*) FROM tickets "
            "WHERE display_id IS NULL OR display_id NOT LIKE 'DEF-%'"
        )
    )
    assert bad == 0


def test_epic_id_populated_for_children_of_epics():
    """Backfill: ``epic_id`` denormalised from recursive parent_id walk."""
    # Rows that have ANY epic ancestor must have a non-null epic_id.
    leftover = asyncio.run(
        _scalar(
            """
            WITH RECURSIVE chain AS (
                SELECT id, parent_id, type, id AS start_id
                  FROM tickets WHERE parent_id IS NOT NULL
                UNION ALL
                SELECT t.id, t.parent_id, t.type, c.start_id
                  FROM tickets t JOIN chain c ON t.id = c.parent_id
            ),
            has_epic_ancestor AS (
                SELECT DISTINCT start_id FROM chain WHERE type = 'epic'
            )
            SELECT count(*) FROM tickets t
              JOIN has_epic_ancestor h ON h.start_id = t.id
             WHERE t.epic_id IS NULL
            """
        )
    )
    assert leftover == 0


def test_new_tables_exist():
    """All v2 tables are present at head."""
    rows = asyncio.run(
        _fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    )
    names = {r["table_name"] for r in rows}
    for t in (
        "projects",
        "sprints",
        "components",
        "project_members",
        "ticket_watchers",
        "ticket_attachments",
    ):
        assert t in names, f"missing table {t}"


def test_ticket_has_v2_columns():
    rows = asyncio.run(
        _fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tickets'"
        )
    )
    cols = {r["column_name"] for r in rows}
    for c in (
        "project_id",
        "sprint_id",
        "component_id",
        "epic_id",
        "fix_versions",
        "resolution",
        "resolved_at",
        "created_agent_step_id",
        "display_id",
    ):
        assert c in cols, f"missing column tickets.{c}"


def test_audit_tables_have_agent_step_id():
    for tbl in ("ticket_comments", "ticket_transitions", "ticket_links", "audit_log"):
        col = asyncio.run(
            _scalar(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{tbl}' AND column_name = 'agent_step_id'"
            )
        )
        assert col == "agent_step_id", f"{tbl} missing agent_step_id"


def test_widened_enum_values_present():
    rows = asyncio.run(
        _fetch(
            "SELECT t.typname, e.enumlabel "
            "FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname IN ('ticket_type','ticket_status','ticket_link_type',"
            "'project_role','sprint_state')"
        )
    )
    by_type: dict[str, set[str]] = {}
    for r in rows:
        by_type.setdefault(r["typname"], set()).add(r["enumlabel"])
    assert "workpackage" in by_type["ticket_type"]
    assert "backlog" in by_type["ticket_status"]
    assert {"clones", "is_cloned_by"}.issubset(by_type["ticket_link_type"])
    assert by_type["project_role"] == {"lead", "member", "viewer"}
    assert by_type["sprint_state"] == {"planned", "active", "closed"}


def test_same_project_trigger_blocks_cross_project_parent():
    """The BEFORE INSERT/UPDATE trigger raises on cross-project parents."""
    async def _run() -> str | None:
        conn = await _connect()
        try:
            # Find the Default project id and any existing ticket.
            def_id = await conn.fetchval(
                "SELECT id FROM projects WHERE key = 'DEF'"
            )
            existing = await conn.fetchrow(
                "SELECT id FROM tickets WHERE project_id = $1 LIMIT 1", def_id
            )
            if existing is None:
                return "no-ticket"
            # Create a second project + try to make a ticket whose parent
            # lives in the Default project. Trigger should reject.
            other_id = await conn.fetchval(
                """
                INSERT INTO projects (key, name) VALUES ('TST', 'Test')
                ON CONFLICT (key) DO UPDATE SET name = excluded.name
                RETURNING id
                """
            )
            # Need a reporter — borrow first user.
            reporter = await conn.fetchval("SELECT id FROM users LIMIT 1")
            if reporter is None:
                # No user exists; create one purely for the trigger test.
                reporter = await conn.fetchval(
                    """
                    INSERT INTO users (email, display_name)
                    VALUES ('trigger-test@example.local', 'Trigger Test')
                    RETURNING id
                    """
                )
            try:
                await conn.execute(
                    """
                    INSERT INTO tickets
                        (seq_number, display_id, title, type, status,
                         priority, parent_id, project_id, reporter_id,
                         reporter_type, labels, custom_fields)
                    VALUES
                        (nextval('tickets_seq_number_seq'), 'TST-xprj',
                         'cross-project', 'task', 'todo', 'medium',
                         $1, $2, $3, 'user',
                         '{}'::text[], '{}'::jsonb)
                    """,
                    existing["id"],
                    other_id,
                    reporter,
                )
                return "unexpectedly-accepted"
            except asyncpg.exceptions.CheckViolationError:
                return "ok"
            except asyncpg.exceptions.RaiseError:
                # Some PG drivers map plpgsql RAISE to RaiseError when
                # ERRCODE isn't a recognised SQLSTATE alias.
                return "ok"
            except Exception as exc:  # surface unexpected errors
                return f"unexpected:{type(exc).__name__}:{exc}"
        finally:
            # Best-effort cleanup; ignore failures.
            try:
                await conn.execute("DELETE FROM projects WHERE key = 'TST'")
            except Exception:
                pass
            await conn.close()

    result = asyncio.run(_run())
    if result == "no-ticket":
        pytest.skip("no pre-existing tickets to use as parent fixture")
    assert result == "ok", f"trigger did not fire: {result}"
