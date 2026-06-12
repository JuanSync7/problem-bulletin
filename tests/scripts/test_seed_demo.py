"""V5a — Idempotency + shape tests for ``app.scripts.seed_demo``.

Running ``seed(session)`` populates a single Problem-Bulletin project
(key="PB") with the demo cast described in ``wp-V5a.md``. The script MUST
be idempotent: a second call against the same DB inserts no new rows and
raises no exception. We assert exact row counts on the second run match
the first.

These tests run against the live Postgres reachable at the standard
``PB_TEST_DATABASE_URL``. Because the seed is naturally rooted at the
``PB`` project key, we clean up that subtree before each test so the
suite is hermetic.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The ``db`` / ``pg_engine`` / ``session_factory`` fixtures live in the
# shared services conftest; re-export them here so this file can claim
# the live-DB session without owning a conftest of its own.
from tests.services.conftest import (  # noqa: F401
    db,
    pg_engine,
    session_factory,
    user_actor,
    agent_actor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _purge_pb(session: AsyncSession) -> None:
    """Delete every row produced by the demo seed under the ``PB`` key.

    The natural-key idempotency strategy in ``seed_demo`` keys everything
    off ``project.key='PB'`` + a fixed cast of handles. To avoid
    cross-test pollution we delete the project subtree (with all
    descendants via the application's FK cascades / explicit child
    deletes) before each test.

    Order matters: ticket_comments → tickets (children before parents
    via ``parent_id``) → project_members → projects, then the four
    seeded handles for users / agents. Each statement is best-effort
    (``IF EXISTS``-style via WHERE on lookup) so a clean DB is fine.
    """
    seeded_user_handles = ("alice", "bob")
    seeded_agent_handles = ("alice-planner", "alice-coder", "alice-reviewer")

    # Lookup the PB project (if any).
    proj_row = (
        await session.execute(
            text("SELECT id FROM projects WHERE key = 'PB'")
        )
    ).first()
    if proj_row is not None:
        pid = proj_row[0]
        # activity_audit_log targeting PB project
        await session.execute(
            text(
                "DELETE FROM activity_audit_log "
                "WHERE target_type = 'project' AND target_id = :p"
            ),
            {"p": pid},
        )
        # ticket_comments referencing tickets in PB
        await session.execute(
            text(
                "DELETE FROM ticket_comments WHERE ticket_id IN "
                "(SELECT id FROM tickets WHERE project_id = :p)"
            ),
            {"p": pid},
        )
        # tickets: clear parent_id pointers first (RESTRICT FK), then
        # bulk-delete. NOTE: the `ck_tickets_subtask_has_parent` CHECK
        # forbids NULLing a subtask's parent_id, so we cannot blanket-NULL
        # every row (the v2.29 hierarchy seed introduces subtask rows).
        # Instead: NULL the parents of non-subtask rows, delete subtasks
        # (always leaves) to drop their child FKs, then delete the rest.
        await session.execute(
            text("UPDATE tickets SET parent_id = NULL, epic_id = NULL "
                 "WHERE project_id = :p AND type <> 'subtask'"),
            {"p": pid},
        )
        await session.execute(
            text("DELETE FROM tickets WHERE project_id = :p "
                 "AND type = 'subtask'"),
            {"p": pid},
        )
        await session.execute(
            text("DELETE FROM tickets WHERE project_id = :p"),
            {"p": pid},
        )
        await session.execute(
            text("DELETE FROM project_members WHERE project_id = :p"),
            {"p": pid},
        )
        await session.execute(
            text("DELETE FROM projects WHERE id = :p"),
            {"p": pid},
        )
        # Per-project sequence (seed_demo recreates IF NOT EXISTS).
        await session.execute(
            text("DROP SEQUENCE IF EXISTS seq_pb")
        )

    # Activity rows pointing at the seeded users (actor_user_id).
    await session.execute(
        text(
            "DELETE FROM activity_audit_log "
            "WHERE actor_user_id IN "
            "(SELECT id FROM users WHERE handle = ANY(:h))"
        ),
        {"h": list(seeded_user_handles)},
    )

    # Agents owned by alice (or seeded agent handles directly).
    await session.execute(
        text("DELETE FROM agent_accounts WHERE handle = ANY(:h)"),
        {"h": list(seeded_agent_handles)},
    )
    # Users.
    await session.execute(
        text("DELETE FROM users WHERE handle = ANY(:h)"),
        {"h": list(seeded_user_handles)},
    )
    await session.commit()


async def _counts(session: AsyncSession, project_id) -> dict[str, int]:
    """Return row counts for the demo subtree, keyed by table label."""
    out: dict[str, int] = {}
    out["tickets"] = int(
        (
            await session.execute(
                text("SELECT count(*) FROM tickets WHERE project_id = :p"),
                {"p": project_id},
            )
        ).scalar_one()
    )
    out["ticket_comments"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM ticket_comments "
                    "WHERE ticket_id IN "
                    "(SELECT id FROM tickets WHERE project_id = :p)"
                ),
                {"p": project_id},
            )
        ).scalar_one()
    )
    out["project_members"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM project_members "
                    "WHERE project_id = :p"
                ),
                {"p": project_id},
            )
        ).scalar_one()
    )
    out["activity"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM activity_audit_log "
                    "WHERE target_type = 'project' AND target_id = :p"
                ),
                {"p": project_id},
            )
        ).scalar_one()
    )
    out["users"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM users WHERE handle = ANY(:h)"
                ),
                {"h": ["alice", "bob"]},
            )
        ).scalar_one()
    )
    out["agents"] = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM agent_accounts "
                    "WHERE handle = ANY(:h)"
                ),
                {"h": ["alice-planner", "alice-coder", "alice-reviewer"]},
            )
        ).scalar_one()
    )
    return out


@pytest_asyncio.fixture
async def clean_pb(db):  # noqa: F811 — re-uses imported fixture name
    """Strip the PB demo subtree before AND after each test."""
    await _purge_pb(db)
    yield
    await _purge_pb(db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_demo_creates_expected_shape(db, clean_pb):  # noqa: F811
    """First seed run populates the demo cast with the documented shape.

    Asserts exactly: 1 project (key='PB'), 2 users, 3 agent_accounts,
    >=7 tickets (1 epic + 2 stories + 4 tasks), >=3 comments, and
    >=2 activity rows targeted at the project.
    """
    from app.scripts.seed_demo import seed

    report = await seed(db)
    await db.commit()

    # Project resolved.
    proj_row = (
        await db.execute(
            text("SELECT id, key, name FROM projects WHERE key = 'PB'")
        )
    ).first()
    assert proj_row is not None, "seed must create a project with key=PB"
    pid, key, name = proj_row
    assert key == "PB"
    assert name == "Problem-Bulletin"

    counts = await _counts(db, pid)
    assert counts["users"] == 2, counts
    assert counts["agents"] == 3, counts
    # 1 epic + 2 stories + 4 tasks = 7
    assert counts["tickets"] >= 7, counts
    assert counts["ticket_comments"] >= 3, counts
    assert counts["project_members"] >= 2, counts  # alice + bob (agents may add more)
    assert counts["activity"] >= 2, counts

    # Report exposes the project id so callers can chain (V5b will reuse).
    assert str(report.project_id) == str(pid)


@pytest.mark.asyncio
async def test_seed_demo_is_idempotent(db, clean_pb):  # noqa: F811
    """Running ``seed()`` twice yields identical row counts on run 2."""
    from app.scripts.seed_demo import seed

    await seed(db)
    await db.commit()

    proj_id = (
        await db.execute(
            text("SELECT id FROM projects WHERE key = 'PB'")
        )
    ).scalar_one()
    first = await _counts(db, proj_id)

    # Re-run — must not raise, must not insert duplicate rows.
    await seed(db)
    await db.commit()

    second = await _counts(db, proj_id)
    assert second == first, (
        f"idempotency violated: first={first} second={second}"
    )
