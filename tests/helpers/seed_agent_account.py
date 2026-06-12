"""Shared agent-account / user seeding helpers (v2.10-WP02).

Background
----------
``alembic/versions/a17_agent_accounts_created_by_not_null.py`` tightened the
``agent_accounts.created_by`` column to NOT NULL.  Every production INSERT
goes through the admin route, which always passes ``actor.id``.  Tests that
seed agents directly (via raw SQL or ``AgentAccountService.create_account``
without ``created_by``) would otherwise fail with::

    NotNullViolationError: null value in column "created_by" of relation
    "agent_accounts" violates not-null constraint

This module provides two thin helpers so tests can satisfy the constraint
without each one repeating the user-seed dance.

Functions
~~~~~~~~~
``seed_user(db, *, email, display_name, ...)``
    Insert a row into ``users`` with a unique handle and return the UUID.
``seed_agent_account(db, *, name, created_by=None, ...)``
    Insert a row into ``agent_accounts``.  If ``created_by`` is ``None`` the
    helper auto-seeds a fresh user and uses that id, guaranteeing the row
    satisfies the NOT NULL constraint.
"""
from __future__ import annotations

import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_user(
    db: AsyncSession,
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    role: str = "user",
    is_active: bool = True,
    handle: Optional[str] = None,
) -> UUID:
    """Insert a ``users`` row with a unique handle. Returns the user id."""
    uid = uuid.uuid4()
    if email is None:
        email = f"seed-{uid.hex[:8]}@x.test"
    if display_name is None:
        display_name = f"Seed {uid.hex[:6]}"
    if handle is None:
        handle = f"user_{uid.hex[:8]}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, display_name, handle, role, is_active) "
            "VALUES (:id, :email, :dn, :h, :role, :active)"
        ),
        {
            "id": uid,
            "email": email,
            "dn": display_name,
            "h": handle,
            "role": role,
            "active": is_active,
        },
    )
    return uid


async def seed_agent_account(
    db: AsyncSession,
    *,
    name: str,
    created_by: Optional[UUID] = None,
    handle: Optional[str] = None,
    api_key_hash: str = "h",
    api_key_prefix: str = "p",
    active: bool = True,
    scopes: Optional[list[str]] = None,
) -> UUID:
    """Insert an ``agent_accounts`` row with a guaranteed-NOT-NULL ``created_by``.

    If the caller does not pass ``created_by``, a throw-away user is seeded
    first and its id is used.  The function never returns a row that would
    violate the DB constraint added by migration ``a17``.
    """
    aid = uuid.uuid4()
    if created_by is None:
        created_by = await seed_user(db, display_name=f"creator-of-{name}")
    # If the caller passes handle=None we leave it NULL so the DB trigger
    # (``trg_agent_accounts_handle_set``) derives + collision-resolves it.
    # If a value is supplied we honour it verbatim.
    await db.execute(
        text(
            "INSERT INTO agent_accounts "
            "(id, name, handle, api_key_hash, api_key_prefix, scopes, "
            " created_by, active, created_at) "
            "VALUES (:id, :n, :h, :hash, :prefix, :scopes, :created_by, "
            "        :active, now())"
        ),
        {
            "id": aid,
            "n": name,
            "h": handle,
            "hash": api_key_hash,
            "prefix": api_key_prefix,
            "scopes": list(scopes or []),
            "created_by": created_by,
            "active": active,
        },
    )
    return aid
