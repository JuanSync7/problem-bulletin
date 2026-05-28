"""v2.13-WP04 (B3) — request-side schema-to-consumer contract pins.

This is the inverse of v2.12-WP03's response-side pin. WP03 caught the
case where ``ORM.to_dict()`` produced a key that the matching ``*Read``
schema silently dropped (response narrowing). The mirror bug class:
the frontend sends a field that the ``*Create`` / ``*Update`` schema
happily validates, but the route handler / service function drops it
on the floor before reaching the ORM row.

**Invariant pinned here**

For every (request-schema, consumer) pair, every field name on the
schema must be referenced in the consumer's source code, where
"referenced" means one of:

* ``payload.fname`` / ``data.fname`` / ``body.fname`` attribute access
  (the payload variable name varies by route convention)
* the field name appears as a string-literal constant in the consumer
  (catches the ``mutable = {"name", ...}`` set guard used by the
  PATCH service functions, where ``model_dump(exclude_unset=True)``
  feeds straight into a ``setattr`` loop)
* the field name appears as a keyword-arg name in a function call
  (catches ``svc.create(title=payload.title, ...)`` style fan-out)

False positives (a name is referenced but not actually persisted to
the row) are acceptable. False negatives — a field that is truly
ignored by the consumer — are the bug class this test pins.

Polarity per pair: schemas in this WP are all closed (no ``extra=
"allow"``), so the invariant is ``schema.model_fields ⊆ consumer
references``, modulo a per-pair ``excluded_fields`` set for legitimate
control-fields like ``version`` (OCC token) that the route consumes
via ``exclude={"version"}`` and never propagates to the service.

The collection-time walk uses the v2.12-WP02 ``source_lint`` helper
(``parse_module``).
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.schemas._legacy import (
    CommentCreate,
    CommentUpdate,
    DisplayNameUpdate,
    ProblemCreate,
    SolutionCreate,
    SolutionVersionCreate,
)
from app.schemas.projects import (
    ComponentCreate,
    ComponentUpdate,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberUpdate,
    ProjectUpdate,
    SprintCreate,
    SprintUpdate,
)
from app.schemas.tickets import TicketCreate, TicketUpdate
from app.schemas.users import HandleUpdate

from tests.helpers.source_lint import parse_module


# ---------------------------------------------------------------------------
# Source-walk helper
# ---------------------------------------------------------------------------


def _referenced_names_in_module(path: pathlib.Path) -> set[str]:
    """Collect every identifier-like name referenced in ``path``.

    Yields a superset of names that could plausibly be a schema-field
    reference:

    * ``Attribute(attr=X)`` for any X — catches ``payload.fname``,
      ``data.fname``, ``body.fname``, ``self.fname`` etc. (we don't
      gate on the value name; if a route renames its payload param,
      false positives are still acceptable, and we'd rather not
      miss).
    * ``Constant(value=str)`` — catches string-literal guards
      (``mutable = {"name", "description", ...}``,
      ``patch.get("lead_id", ...)``).
    * ``keyword(arg=X)`` — catches keyword-arg fan-out
      (``svc.create(title=payload.title, ...)``).
    * ``Name(id=X)`` — catches the rare case where a field name
      coincides with a local var (e.g. ``priority = payload.priority``
      shadowing — defensive).
    """
    tree = parse_module(path)
    assert tree is not None, f"failed to parse {path}"
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


# ---------------------------------------------------------------------------
# Pair inventory
# ---------------------------------------------------------------------------


_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _p(rel: str) -> pathlib.Path:
    return _ROOT / rel


# Each row: (label, schema, [consumer_paths], excluded_fields)
# Multiple consumer paths are unioned — for PATCH schemas the route does
# the ``exclude={"version"}`` dance and the service holds the ``mutable``
# set, so the union of route+service is the contract surface.
_PAIRS: list[tuple[str, type[BaseModel], list[pathlib.Path], frozenset[str]]] = [
    (
        "TicketCreate->routes.tickets",
        TicketCreate,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "TicketUpdate->routes.tickets+services.tickets",
        TicketUpdate,
        [_p("app/routes/tickets.py"), _p("app/services/tickets.py")],
        frozenset({"version"}),  # OCC token; route excludes it from patch
    ),
    (
        "ProjectCreate->routes.projects",
        ProjectCreate,
        [_p("app/routes/projects.py")],
        frozenset(),
    ),
    (
        "ProjectUpdate->routes.projects+services.projects",
        ProjectUpdate,
        [_p("app/routes/projects.py"), _p("app/services/projects.py")],
        frozenset({"version"}),
    ),
    (
        "ProjectMemberCreate->routes.projects",
        ProjectMemberCreate,
        [_p("app/routes/projects.py")],
        frozenset(),
    ),
    (
        "ProjectMemberUpdate->routes.projects",
        ProjectMemberUpdate,
        [_p("app/routes/projects.py")],
        frozenset(),
    ),
    (
        "SprintCreate->routes.sprints",
        SprintCreate,
        [_p("app/routes/sprints.py")],
        frozenset(),
    ),
    (
        "SprintUpdate->routes.sprints+services.sprints",
        SprintUpdate,
        [_p("app/routes/sprints.py"), _p("app/services/sprints.py")],
        frozenset(),
    ),
    (
        "ComponentCreate->routes.projects",
        ComponentCreate,
        [_p("app/routes/projects.py")],
        frozenset(),
    ),
    (
        "ComponentUpdate->routes.projects+services.components",
        ComponentUpdate,
        [_p("app/routes/projects.py"), _p("app/services/components.py")],
        frozenset(),
    ),
    (
        "HandleUpdate->routes.users",
        HandleUpdate,
        [_p("app/routes/users.py")],
        frozenset(),
    ),
    (
        "DisplayNameUpdate->routes.auth",
        DisplayNameUpdate,
        [_p("app/routes/auth.py")],
        frozenset(),
    ),
    (
        "ProblemCreate->services.problems",
        ProblemCreate,
        [_p("app/services/problems.py")],
        frozenset(),
    ),
    (
        "SolutionCreate->services.solutions",
        SolutionCreate,
        [_p("app/services/solutions.py")],
        frozenset(),
    ),
    (
        "SolutionVersionCreate->services.solutions",
        SolutionVersionCreate,
        [_p("app/services/solutions.py")],
        frozenset(),
    ),
    (
        "CommentCreate->services.comments",
        CommentCreate,
        [_p("app/services/comments.py")],
        frozenset(),
    ),
    (
        "CommentUpdate->routes.comments",
        CommentUpdate,
        [_p("app/routes/comments.py")],
        frozenset(),
    ),
]


# ---------------------------------------------------------------------------
# Parametrized contract test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,schema_cls,consumer_paths,excluded",
    _PAIRS,
    ids=[row[0] for row in _PAIRS],
)
def test_request_schema_fields_referenced_in_consumer(
    label: str,
    schema_cls: type[BaseModel],
    consumer_paths: list[pathlib.Path],
    excluded: frozenset[str],
) -> None:
    """Pin the request side: no field accepted by the schema is silently
    dropped by the consumer (v2.13-WP04 / Bucket B3).

    Mirror of v2.12-WP03's response-side ``to_dict ⊆ *Read`` pin.
    """
    declared = set(schema_cls.model_fields.keys()) - set(excluded)

    referenced: set[str] = set()
    for path in consumer_paths:
        assert path.exists(), f"consumer path missing: {path}"
        referenced |= _referenced_names_in_module(path)

    missing = declared - referenced
    assert not missing, (
        f"{schema_cls.__name__} field(s) {sorted(missing)} are accepted by "
        f"the schema but never referenced in the consumer(s) "
        f"{[p.name for p in consumer_paths]}. WP04 request-side contract: "
        f"frontend can send these fields and the backend will silently "
        f"discard them."
    )


# ---------------------------------------------------------------------------
# Synthetic-bad self-test — proves the assertion fires red when a
# consumer truly drops a schema field.
# ---------------------------------------------------------------------------


class _SyntheticBadSchema(BaseModel):
    """Toy schema with a field the synthetic consumer will not touch."""

    model_config = ConfigDict(extra="forbid")

    name: str
    forgotten_field: str = Field(default="x")


def test_synthetic_drift_fires_red(tmp_path: pathlib.Path) -> None:
    """A fake consumer that uses ``payload.name`` but never references
    ``forgotten_field`` (no attribute access, no string literal, no
    kwarg) must be flagged by the same walk used in the real pair test.
    """
    fake = tmp_path / "fake_consumer.py"
    fake.write_text(
        "def handle(payload):\n"
        "    return {'name': payload.name}\n"
    )
    referenced = _referenced_names_in_module(fake)
    declared = set(_SyntheticBadSchema.model_fields.keys())
    missing = declared - referenced
    assert missing == {"forgotten_field"}, (
        f"synthetic-bad self-test expected to flag 'forgotten_field'; "
        f"got missing={sorted(missing)}, referenced={sorted(referenced)}"
    )


def test_synthetic_good_passes(tmp_path: pathlib.Path) -> None:
    """Sanity check: a synthetic consumer that DOES reference every
    field of the synthetic schema must NOT be flagged."""
    fake = tmp_path / "good_consumer.py"
    fake.write_text(
        "def handle(payload):\n"
        "    return {'name': payload.name, 'forgotten_field': payload.forgotten_field}\n"
    )
    referenced = _referenced_names_in_module(fake)
    declared = set(_SyntheticBadSchema.model_fields.keys())
    missing = declared - referenced
    assert not missing
