"""v2.12-WP03 (C1+C2) — ORM ``to_dict()`` ⊆ matching ``*Read`` schema lint.

Pins the contract that every key an ORM ``to_dict()`` emits is either
declared on the matching ``*Read`` Pydantic schema OR the schema sets
``model_config = ConfigDict(extra="allow")``.

v2.11-WP07 retrospective lesson #2 ("Schema convergence narrows surfaces
silently"): WP06 added ``Page[T]`` and WP07 added ``response_model=`` on
adjacent routes; in between, ``TicketRead`` got narrowed without anyone
noticing. The right invariant is a contract test across every
(ORM_class, schema_class) pair. This is that test.

**Polarity per pair.**

* **Closed schemas (default — no ``extra="allow"``)**: assert
  ``to_dict().keys() ⊆ schema.model_fields.keys()``. Catches schema
  narrowing — i.e. the WP07 failure mode.
* **Open schemas (``extra="allow"``)**: subset constraint is relaxed
  by definition (the schema accepts any extra key). Flip polarity:
  assert every REQUIRED schema field is present in ``to_dict()``
  output, so removing one from ``to_dict()`` still fails.

Both directions of narrowing are pinned. No conftest hooks; one
collected test per pair; ids legible as ``"Ticket<->TicketRead"``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.enums import (
    ProjectRole,
    SprintState,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from app.models.project import Component, Project, ProjectMember, Sprint
from app.models.ticket import Ticket
from app.models.ticket_attachment import TicketAttachment
from app.models.ticket_watcher import TicketWatcher
from app.schemas.projects import (
    ComponentRead,
    ProjectMemberRead,
    ProjectRead,
    SprintRead,
)
from app.schemas.tickets import (
    TicketAttachmentRead,
    TicketRead,
    TicketWatcherRead,
)


# ---------------------------------------------------------------------------
# Factories — minimal ORM instances populated by attribute assignment.
#
# ``to_dict()`` reads attributes only; no DB session is required as long as
# every column accessed in the body is set. We deliberately do not call
# ``Session.add()`` / flush — this keeps the test pure-Python and fast.
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _project_instance() -> Project:
    p = Project()
    p.id = uuid4()
    p.key = "PRJ"
    p.name = "Test Project"
    p.description = "desc"
    p.lead_id = uuid4()
    p.lead_type = "user"
    p.archived = False
    p.wip_limits = {"todo": 5}
    p.state_change_coalesce_seconds = 60
    p.version = 1
    p.created_at = _now()
    p.updated_at = _now()
    return p


def _sprint_instance() -> Sprint:
    s = Sprint()
    s.id = uuid4()
    s.project_id = uuid4()
    s.name = "Sprint 1"
    s.goal = "ship it"
    s.state = SprintState.planned
    s.start_date = date(2026, 1, 1)
    s.end_date = date(2026, 1, 14)
    s.created_at = _now()
    s.updated_at = _now()
    return s


def _component_instance() -> Component:
    c = Component()
    c.id = uuid4()
    c.project_id = uuid4()
    c.name = "Frontend"
    c.description = "UI"
    c.lead_id = uuid4()
    c.lead_type = "user"
    c.created_at = _now()
    c.updated_at = _now()
    return c


def _project_member_instance() -> ProjectMember:
    m = ProjectMember()
    m.id = uuid4()
    m.project_id = uuid4()
    m.member_id = uuid4()
    m.member_type = "user"
    m.role = ProjectRole.member
    m.created_at = _now()
    return m


def _ticket_instance() -> Ticket:
    t = Ticket()
    t.id = uuid4()
    t.seq_number = 1
    t.display_id = "PRJ-1"
    t.title = "Test Ticket"
    t.description = "body"
    t.type = TicketType.task
    t.status = TicketStatus.todo
    t.priority = TicketPriority.medium
    t.parent_id = None
    t.project_id = uuid4()
    t.sprint_id = None
    t.component_id = None
    t.epic_id = None
    t.reporter_id = uuid4()
    t.reporter_type = "user"
    t.assignee_id = None
    t.assignee_type = None
    t.story_points = None
    t.due_date = None
    t.labels = []
    t.fix_versions = []
    t.custom_fields = {}
    t.resolution = None
    t.resolved_at = None
    t.created_agent_step_id = None
    t.last_actor_type = "user"
    t.last_actor_id = uuid4()
    t.last_activity_at = _now()
    t.last_agent_step_id = None
    t.version = 1
    t.created_at = _now()
    t.updated_at = _now()
    return t


def _ticket_watcher_instance() -> TicketWatcher:
    w = TicketWatcher()
    w.id = uuid4()
    w.ticket_id = uuid4()
    w.watcher_id = uuid4()
    w.watcher_type = "user"
    w.created_at = _now()
    return w


def _ticket_attachment_instance() -> TicketAttachment:
    a = TicketAttachment()
    a.id = uuid4()
    a.ticket_id = uuid4()
    a.uploaded_by = uuid4()
    a.uploaded_by_type = "user"
    a.filename = "a.txt"
    a.content_type = "text/plain"
    a.byte_size = 12
    a.storage_path = "/tmp/a.txt"
    a.agent_step_id = None
    a.created_at = _now()
    return a


# ---------------------------------------------------------------------------
# Mapping — one row per (ORM, schema) pair currently in the codebase.
# Unmatched ORMs (no wire-shape schema) are recorded in the WP03 diagnosis
# doc, not parametrized here.
# ---------------------------------------------------------------------------


_PAIRS: list[tuple[str, type, type, callable]] = [
    ("Ticket<->TicketRead", Ticket, TicketRead, _ticket_instance),
    ("Project<->ProjectRead", Project, ProjectRead, _project_instance),
    ("Sprint<->SprintRead", Sprint, SprintRead, _sprint_instance),
    ("Component<->ComponentRead", Component, ComponentRead, _component_instance),
    (
        "ProjectMember<->ProjectMemberRead",
        ProjectMember,
        ProjectMemberRead,
        _project_member_instance,
    ),
    (
        "TicketWatcher<->TicketWatcherRead",
        TicketWatcher,
        TicketWatcherRead,
        _ticket_watcher_instance,
    ),
    (
        "TicketAttachment<->TicketAttachmentRead",
        TicketAttachment,
        TicketAttachmentRead,
        _ticket_attachment_instance,
    ),
]


def _schema_extra_allow(schema_cls: type[BaseModel]) -> bool:
    cfg = getattr(schema_cls, "model_config", {}) or {}
    # ConfigDict is a TypedDict at runtime → plain dict access.
    return cfg.get("extra") == "allow"


@pytest.mark.parametrize(
    "label,orm_cls,schema_cls,factory",
    _PAIRS,
    ids=[row[0] for row in _PAIRS],
)
def test_orm_to_dict_matches_schema_contract(
    label: str,
    orm_cls: type,
    schema_cls: type[BaseModel],
    factory,
) -> None:
    """Pin every (ORM, *Read) pair: no silent schema narrowing.

    v2.11-WP07 retrospective lesson #2. Polarity flips based on whether
    the schema sets ``extra="allow"`` (open) vs default (closed) — both
    directions of narrowing are caught.
    """
    instance = factory()
    produced = set(instance.to_dict().keys())
    declared = set(schema_cls.model_fields.keys())

    if _schema_extra_allow(schema_cls):
        # Open schema: subset constraint vacuous. Pin the other direction
        # — every REQUIRED schema field must be produced by to_dict().
        required = {
            name
            for name, field in schema_cls.model_fields.items()
            if field.is_required()
        }
        missing = required - produced
        assert not missing, (
            f"{orm_cls.__name__}.to_dict() is missing required "
            f"{schema_cls.__name__} field(s): {sorted(missing)}. "
            f"Open schema (extra='allow') — silent ORM narrowing."
        )
    else:
        # Closed schema: classic WP07 polarity. Any to_dict() key the
        # schema drops would be silently lost on the wire.
        dropped = produced - declared
        assert not dropped, (
            f"{schema_cls.__name__} drops {orm_cls.__name__}.to_dict() "
            f"key(s): {sorted(dropped)}. Closed schema — silent wire "
            f"narrowing (WP07 failure mode)."
        )
