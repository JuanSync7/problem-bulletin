"""Project / Sprint / Component service-layer tests (WP3)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from app.enums import ProjectRole, SprintState, UserRole
from app.exceptions import OptimisticConcurrencyError, ValidationError
from app.services.components import (
    ComponentNameConflictError,
    component_service,
)
from app.services.projects import (
    ProjectKeyConflictError,
    ProjectHasTicketsError,
    project_service,
)
from app.services.sprints import SprintStateError, sprint_service


def _admin_user(uid=None):
    """Mock admin User for service calls that now require acting_user."""
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.role = UserRole.admin
    return user


def _unique_key(prefix: str = "P") -> str:
    """Generate a UNIQUE project key that fits ^[A-Z][A-Z0-9]{1,9}$.

    Uses the uuid4 hex without a leading digit. Keys are uppercase and
    capped at 10 chars. Tests run inside a rollback'd transaction so the
    sequence DDL won't actually persist.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    suffix = "".join(c if c.isalnum() else "0" for c in suffix)
    return (prefix + suffix)[:10]


@pytest.mark.asyncio
async def test_create_project_creates_sequence(db):
    """Project creation registers a Postgres SEQUENCE seq_<lc_key>."""
    key = _unique_key("PROJ")
    proj = await project_service.create(db, key=key, name="Test")
    assert proj.key == key
    # Sequence must exist and be callable.
    n = await project_service.next_seq_number(db, key)
    assert n == 1
    # next_display_id formats `<KEY>-<n+1>` (next call increments).
    disp = await project_service.next_display_id(db, key)
    assert disp == f"{key}-2"


@pytest.mark.asyncio
async def test_create_project_rejects_bad_key(db):
    """Key must match the documented regex."""
    with pytest.raises(ValidationError):
        await project_service.create(db, key="lowercase", name="x")
    with pytest.raises(ValidationError):
        await project_service.create(db, key="1ABC", name="x")
    with pytest.raises(ValidationError):
        await project_service.create(db, key="X", name="x")  # too short


@pytest.mark.asyncio
async def test_duplicate_key_rejected(db):
    """A second project with the same key surfaces a domain error."""
    key = _unique_key("DUP")
    await project_service.create(db, key=key, name="one")
    with pytest.raises(ProjectKeyConflictError):
        await project_service.create(db, key=key, name="two")


@pytest.mark.asyncio
async def test_update_with_occ(db):
    """update() honours optimistic-concurrency on version."""
    # v2.2-WP15: update() now requires acting_user; use admin to bypass permission.
    admin = _admin_user()
    p = await project_service.create(db, key=_unique_key("OCC"), name="x")
    initial_version = p.version
    p2 = await project_service.update(
        db, p.id, expected_version=initial_version, patch={"name": "y"},
        acting_user=admin,
    )
    assert p2.name == "y"
    assert p2.version == initial_version + 1
    # Re-send the old version; the row is now at version+1 so this is stale.
    with pytest.raises(OptimisticConcurrencyError):
        await project_service.update(
            db, p.id, expected_version=initial_version, patch={"name": "z"},
            acting_user=admin,
        )


@pytest.mark.asyncio
async def test_archive_unarchive_roundtrip(db):
    """archive() and unarchive() flip the boolean and bump version."""
    p = await project_service.create(db, key=_unique_key("ARC"), name="x")
    a = await project_service.archive(db, p.id)
    assert a.archived is True
    u = await project_service.unarchive(db, p.id)
    assert u.archived is False


@pytest.mark.asyncio
async def test_delete_blocked_by_tickets(db):
    """delete() refuses when the project still has tickets.

    We don't rely on the DEF project's content (it can legitimately be
    empty post-backfill). Instead create a fresh project and seed one
    ticket via the TicketService, then assert delete is refused.
    """
    from app.enums import ActorType
    from app.services.context import Actor
    from app.services.tickets import TicketService

    # Insert a real user (FK target for reporter_id).
    uid = uuid.uuid4()
    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:i, :e, 'u')"),
        {"i": uid, "e": f"u-{uid}@x.test"},
    )
    actor = Actor(id=uid, type=ActorType.user, label="u", scopes=())

    proj = await project_service.create(
        db, key=_unique_key("DEL"), name="x"
    )
    svc = TicketService()
    await svc.create(db, actor=actor, title="t", project_id=proj.id)

    with pytest.raises(ProjectHasTicketsError):
        await project_service.delete(db, proj.id)


@pytest.mark.asyncio
async def test_delete_empty_project_succeeds(db):
    """delete() on a ticket-free project drops the row + sequence."""
    p = await project_service.create(db, key=_unique_key("EMPTY"), name="x")
    await project_service.delete(db, p.id)
    assert await project_service.get(db, p.id) is None


@pytest.mark.asyncio
async def test_member_add_remove(db):
    """add_member is idempotent on conflict; remove_member is a no-op for unknown."""
    p = await project_service.create(db, key=_unique_key("MEM"), name="x")
    mid = uuid.uuid4()
    m1 = await project_service.add_member(
        db, p.id, member_id=mid, member_type="user", role=ProjectRole.member
    )
    m2 = await project_service.add_member(
        db, p.id, member_id=mid, member_type="user", role=ProjectRole.lead
    )
    assert m1.id == m2.id
    assert m2.role == ProjectRole.lead
    members = await project_service.list_members(db, p.id)
    assert len(members) == 1
    # v2.2-WP15: remove_member() now requires acting_user.
    await project_service.remove_member(
        db, p.id, member_id=mid, member_type="user", acting_user=_admin_user()
    )
    members = await project_service.list_members(db, p.id)
    assert members == []


# -- Sprints ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_sprint_lifecycle(db):
    """planned -> active -> closed; can't go planned->closed directly."""
    p = await project_service.create(db, key=_unique_key("SP"), name="x")
    s = await sprint_service.create(db, project_id=p.id, name="Sprint 1")
    assert s.state == SprintState.planned
    with pytest.raises(SprintStateError):
        await sprint_service.close(db, s.id)
    started = await sprint_service.start(db, s.id)
    assert started.state == SprintState.active
    closed = await sprint_service.close(db, s.id)
    assert closed.state == SprintState.closed


@pytest.mark.asyncio
async def test_one_active_sprint_per_project(db):
    """Starting a second active sprint in the same project is refused."""
    p = await project_service.create(db, key=_unique_key("SP2"), name="x")
    s1 = await sprint_service.create(db, project_id=p.id, name="A")
    s2 = await sprint_service.create(db, project_id=p.id, name="B")
    await sprint_service.start(db, s1.id)
    with pytest.raises(ValidationError):
        await sprint_service.start(db, s2.id)


# -- Components -------------------------------------------------------------

@pytest.mark.asyncio
async def test_component_create_and_unique_name(db):
    """(project_id, name) uniqueness surfaces a typed conflict error."""
    p = await project_service.create(db, key=_unique_key("CMP"), name="x")
    c1 = await component_service.create(
        db, project_id=p.id, name="Frontend"
    )
    assert c1.name == "Frontend"
    with pytest.raises(ComponentNameConflictError):
        await component_service.create(
            db, project_id=p.id, name="Frontend"
        )
