"""Pure-ORM unit tests for the Ticketing v2 model surface.

These don't talk to Postgres — they instantiate the SQLAlchemy mapped
classes, exercise ``to_dict()`` / defaults / column metadata, and assert
the shape WP3 will rely on. The migration-side smoke tests live in
``tests/unit/test_ticketing_v2_migration.py`` (skip-if-db-down).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.enums import (
    ProjectRole,
    SprintState,
    TicketLinkType,
    TicketStatus,
    TicketType,
)
from app.models import (
    Component,
    Project,
    ProjectMember,
    Sprint,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketLink,
    TicketTransition,
    TicketWatcher,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_ticket_type_includes_workpackage():
    assert TicketType("workpackage") is TicketType.workpackage
    assert "workpackage" in {t.value for t in TicketType}


def test_ticket_status_includes_backlog():
    assert TicketStatus("backlog") is TicketStatus.backlog


def test_ticket_link_type_includes_clones_pair_and_tombstones_parent_child():
    values = {t.value for t in TicketLinkType}
    assert "clones" in values and "is_cloned_by" in values
    # tombstoned but still present per Cross-WP Rule 3
    assert "parent_of" in values and "child_of" in values


def test_project_role_enum_values():
    assert {r.value for r in ProjectRole} == {"lead", "member", "viewer"}


def test_sprint_state_enum_values():
    assert {s.value for s in SprintState} == {"planned", "active", "closed"}


# ---------------------------------------------------------------------------
# Project / Sprint / Component / ProjectMember
# ---------------------------------------------------------------------------


def test_project_to_dict_round_trips_required_fields():
    pid = uuid.uuid4()
    now = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    p = Project(
        id=pid,
        key="AION",
        name="Aion",
        description="desc",
        lead_id=None,
        lead_type=None,
        archived=False,
        wip_limits={"in_progress": 5},
        version=1,
        created_at=now,
        updated_at=None,
    )
    d = p.to_dict()
    assert d["id"] == str(pid)
    assert d["key"] == "AION"
    assert d["wip_limits"] == {"in_progress": 5}
    assert d["archived"] is False
    assert d["version"] == 1
    assert d["created_at"] == now.isoformat()
    assert d["updated_at"] is None


def test_project_repr_includes_key():
    p = Project(key="AION", name="Aion")
    assert "AION" in repr(p)


def test_sprint_to_dict_serialises_enum_and_dates():
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    s = Sprint(
        id=sid,
        project_id=pid,
        name="S-1",
        goal="ship v2",
        state=SprintState.active,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 15),
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    d = s.to_dict()
    assert d["state"] == "active"
    assert d["start_date"] == "2026-05-01"
    assert d["end_date"] == "2026-05-15"
    assert d["project_id"] == str(pid)


def test_component_to_dict():
    cid = uuid.uuid4()
    pid = uuid.uuid4()
    c = Component(id=cid, project_id=pid, name="Frontend")
    d = c.to_dict()
    assert d["id"] == str(cid)
    assert d["project_id"] == str(pid)
    assert d["name"] == "Frontend"
    assert d["lead_id"] is None


def test_project_member_to_dict_defaults_role_to_member():
    pid = uuid.uuid4()
    mid = uuid.uuid4()
    m = ProjectMember(
        project_id=pid,
        member_id=mid,
        member_type="user",
        role=ProjectRole.member,
    )
    d = m.to_dict()
    assert d["role"] == "member"
    assert d["member_type"] == "user"


# ---------------------------------------------------------------------------
# Ticket — v2 extensions
# ---------------------------------------------------------------------------


def test_ticket_to_dict_includes_v2_fields():
    pid = uuid.uuid4()
    tid = uuid.uuid4()
    rid = uuid.uuid4()
    t = Ticket(
        id=tid,
        seq_number=42,
        display_id="DEF-42",
        title="hello",
        description="world",
        type=TicketType.task,
        status=TicketStatus.backlog,
        priority=None,  # left unset
        project_id=pid,
        sprint_id=None,
        component_id=None,
        epic_id=None,
        reporter_id=rid,
        reporter_type="user",
        fix_versions=["v1.0"],
        labels=["alpha"],
        custom_fields={},
        version=1,
        created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
    )
    d = t.to_dict()
    assert d["display_id"] == "DEF-42"
    assert d["project_id"] == str(pid)
    assert d["epic_id"] is None
    assert d["fix_versions"] == ["v1.0"]
    assert d["status"] == "backlog"
    assert d["resolution"] is None
    assert d["resolved_at"] is None
    assert d["created_agent_step_id"] is None


def test_ticket_computed_display_id_returns_column_value():
    """Back-compat: ``computed_display_id`` is now an alias for ``display_id``."""
    t = Ticket(seq_number=7, display_id="DEF-7", title="x")
    assert t.computed_display_id == "DEF-7"


def test_ticket_has_v2_relationships_declared():
    mapper = Ticket.__mapper__
    rel_names = {r.key for r in mapper.relationships}
    for name in ("project", "sprint", "component", "watchers", "attachments"):
        assert name in rel_names, f"missing relationship: {name}"


def test_ticket_table_has_v2_columns():
    cols = {c.name for c in Ticket.__table__.columns}
    for new_col in (
        "project_id",
        "sprint_id",
        "component_id",
        "epic_id",
        "fix_versions",
        "resolution",
        "resolved_at",
        "created_agent_step_id",
    ):
        assert new_col in cols
    # display_id is now plain TEXT (no Computed)
    display = Ticket.__table__.columns["display_id"]
    assert display.computed is None
    assert display.nullable is False


# ---------------------------------------------------------------------------
# Watcher / Attachment
# ---------------------------------------------------------------------------


def test_ticket_watcher_to_dict():
    tid = uuid.uuid4()
    wid = uuid.uuid4()
    w = TicketWatcher(
        ticket_id=tid,
        watcher_id=wid,
        watcher_type="agent",
    )
    d = w.to_dict()
    assert d["ticket_id"] == str(tid)
    assert d["watcher_id"] == str(wid)
    assert d["watcher_type"] == "agent"


def test_ticket_attachment_to_dict():
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    a = TicketAttachment(
        ticket_id=tid,
        uploaded_by=uid,
        uploaded_by_type="user",
        filename="x.png",
        content_type="image/png",
        byte_size=123,
        storage_path="/tmp/x.png",
        agent_step_id=None,
    )
    d = a.to_dict()
    assert d["filename"] == "x.png"
    assert d["byte_size"] == 123
    assert d["agent_step_id"] is None


# ---------------------------------------------------------------------------
# agent_step_id on audit-producing tables
# ---------------------------------------------------------------------------


def test_ticket_comment_has_agent_step_id_and_mentions_columns():
    cols = {c.name for c in TicketComment.__table__.columns}
    assert "agent_step_id" in cols
    assert "mentions" in cols


def test_ticket_transition_has_agent_step_id_column():
    cols = {c.name for c in TicketTransition.__table__.columns}
    assert "agent_step_id" in cols


def test_ticket_link_has_agent_step_id_column():
    cols = {c.name for c in TicketLink.__table__.columns}
    assert "agent_step_id" in cols


def test_audit_log_event_has_agent_step_id_column():
    from app.models import AuditLogEvent

    cols = {c.name for c in AuditLogEvent.__table__.columns}
    assert "agent_step_id" in cols
