"""Shared problem/solution/comment seeding helpers (v2.10-WP04a).

Used by the live-DB service tests that exercise the public problem
lifecycle (problems, solutions, comments, voting).  All inserts run on
the function-scoped ``db`` session from ``tests/services/conftest.py``
which is rolled back on teardown.
"""
from __future__ import annotations

import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.seed_agent_account import seed_user


async def seed_category(
    db: AsyncSession,
    *,
    name: Optional[str] = None,
    slug: Optional[str] = None,
) -> UUID:
    """Insert a categories row.  Returns the category id."""
    cid = uuid.uuid4()
    suffix = cid.hex[:8]
    if name is None:
        name = f"cat-{suffix}"
    if slug is None:
        slug = f"cat-{suffix}"
    await db.execute(
        text(
            "INSERT INTO categories (id, name, slug, sort_order) "
            "VALUES (:id, :n, :s, 0)"
        ),
        {"id": cid, "n": name, "s": slug},
    )
    return cid


async def seed_tag(db: AsyncSession, *, name: Optional[str] = None) -> UUID:
    tid = uuid.uuid4()
    if name is None:
        name = f"tag-{tid.hex[:8]}"
    await db.execute(
        text("INSERT INTO tags (id, name) VALUES (:id, :n)"),
        {"id": tid, "n": name},
    )
    return tid


async def seed_problem(
    db: AsyncSession,
    *,
    author_id: Optional[UUID] = None,
    category_id: Optional[UUID] = None,
    title: str = "Seed problem title",
    description: str = "Seed problem description text body",
    status: str = "open",
    is_pinned: bool = False,
    is_anonymous: bool = False,
) -> UUID:
    """Insert a problems row.  Returns the problem id.

    If ``author_id`` / ``category_id`` are omitted, throw-away rows are
    seeded automatically so the FK constraints are satisfied.
    """
    pid = uuid.uuid4()
    if author_id is None:
        author_id = await seed_user(db)
    if category_id is None:
        category_id = await seed_category(db)
    await db.execute(
        text(
            "INSERT INTO problems "
            "(id, title, description, author_id, category_id, status, "
            " is_pinned, is_anonymous, activity_at, created_at) "
            "VALUES (:id, :t, :d, :a, :c, :s, :p, :anon, now(), now())"
        ),
        {
            "id": pid,
            "t": title,
            "d": description,
            "a": author_id,
            "c": category_id,
            "s": status,
            "p": is_pinned,
            "anon": is_anonymous,
        },
    )
    return pid


async def seed_solution(
    db: AsyncSession,
    *,
    problem_id: UUID,
    author_id: Optional[UUID] = None,
    description: str = "Seed solution description text",
    status: str = "pending",
    is_anonymous: bool = False,
) -> tuple[UUID, UUID]:
    """Insert a solution + its first version.  Returns (solution_id, version_id)."""
    sid = uuid.uuid4()
    vid = uuid.uuid4()
    if author_id is None:
        author_id = await seed_user(db)
    await db.execute(
        text(
            "INSERT INTO solutions "
            "(id, problem_id, author_id, status, is_anonymous, created_at) "
            "VALUES (:id, :p, :a, :s, :anon, now())"
        ),
        {
            "id": sid,
            "p": problem_id,
            "a": author_id,
            "s": status,
            "anon": is_anonymous,
        },
    )
    await db.execute(
        text(
            "INSERT INTO solution_versions "
            "(id, solution_id, version_number, description, created_by, created_at) "
            "VALUES (:id, :sid, 1, :d, :cb, now())"
        ),
        {"id": vid, "sid": sid, "d": description, "cb": author_id},
    )
    await db.execute(
        text("UPDATE solutions SET current_version_id = :v WHERE id = :id"),
        {"v": vid, "id": sid},
    )
    return sid, vid


async def seed_comment(
    db: AsyncSession,
    *,
    problem_id: UUID,
    author_id: UUID,
    solution_id: Optional[UUID] = None,
    parent_comment_id: Optional[UUID] = None,
    body: str = "Seed comment body",
    is_anonymous: bool = False,
) -> UUID:
    cid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO comments "
            "(id, problem_id, solution_id, author_id, parent_comment_id, "
            " body, is_anonymous, is_edited, created_at) "
            "VALUES (:id, :p, :s, :a, :pc, :b, :anon, false, now())"
        ),
        {
            "id": cid,
            "p": problem_id,
            "s": solution_id,
            "a": author_id,
            "pc": parent_comment_id,
            "b": body,
            "anon": is_anonymous,
        },
    )
    return cid
