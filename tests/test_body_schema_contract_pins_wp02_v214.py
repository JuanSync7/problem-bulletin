"""v2.14-WP02 (B3) — request-side contract pins for ``*Body`` schemas.

Extends v2.13-WP04's ``*Create`` / ``*Update`` request-side pin to the
seven one-shot ``*Body`` schemas that WP04 explicitly deferred:

* ``TicketTransitionBody``
* ``TicketAssignBody``
* ``TicketCommentBody``
* ``TicketLinkBody``
* ``TicketWatcherBody``
* ``TicketAttachmentBody``
* ``MagicLinkRequest``

These are ad-hoc action payloads (POST /tickets/{}/transition,
/assign, /comments, /links, /watchers, /attachments and POST
/auth/magic-link) rather than table-row CRUD schemas, but the bug
class is identical: a field accepted by the schema must be referenced
by the route/service that handles the request — otherwise the
frontend can send the field, Pydantic validates it, and the backend
silently drops it before reaching the side-effect.

Polarity is closed (no ``extra="allow"`` on any of these schemas), so
the invariant is the standard ``schema.model_fields ⊆ consumer
references``. Per-pair ``excluded`` is empty for all seven —
``TicketAssignBody.expected_version`` is the only OCC-flavoured token
and the assign route DOES forward it explicitly as
``expected_version=payload.expected_version``, so no exclusion is
needed.

The collection-time walk re-uses v2.12-WP02's
``parse_module()`` + v2.13-WP04's ``_referenced_names_in_module``
shape (re-implemented inline because the WP04 helper is module-private
and we don't want to bend its abstraction by exporting it for a
single sibling test).
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import BaseModel

from app.schemas._legacy import MagicLinkRequest
from app.schemas.tickets import (
    TicketAssignBody,
    TicketAttachmentBody,
    TicketCommentBody,
    TicketLinkBody,
    TicketTransitionBody,
    TicketWatcherBody,
)

from tests.helpers.source_lint import parse_module


# ---------------------------------------------------------------------------
# Source-walk helper (mirror of WP04's ``_referenced_names_in_module``).
# ---------------------------------------------------------------------------


def _referenced_names_in_module(path: pathlib.Path) -> set[str]:
    """Collect every identifier-like name referenced in ``path``.

    Same shape as v2.13-WP04: unions ``Attribute(attr=)``,
    ``Constant(value=str)``, ``keyword(arg=)`` and ``Name(id=)``. False
    positives (a name is referenced but not actually persisted) are
    acceptable; the only thing we pin is the false-negative —
    schema field that the consumer truly drops on the floor.
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
_PAIRS: list[tuple[str, type[BaseModel], list[pathlib.Path], frozenset[str]]] = [
    (
        "TicketTransitionBody->routes.tickets",
        TicketTransitionBody,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "TicketAssignBody->routes.tickets",
        TicketAssignBody,
        [_p("app/routes/tickets.py")],
        # expected_version is OCC-style but the route forwards it
        # explicitly via ``expected_version=payload.expected_version``,
        # so no exclusion needed — the kwarg-name walk picks it up.
        frozenset(),
    ),
    (
        "TicketCommentBody->routes.tickets",
        TicketCommentBody,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "TicketLinkBody->routes.tickets",
        TicketLinkBody,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "TicketWatcherBody->routes.tickets",
        TicketWatcherBody,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "TicketAttachmentBody->routes.tickets",
        TicketAttachmentBody,
        [_p("app/routes/tickets.py")],
        frozenset(),
    ),
    (
        "MagicLinkRequest->routes.auth",
        MagicLinkRequest,
        [_p("app/routes/auth.py")],
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
def test_body_schema_fields_referenced_in_consumer(
    label: str,
    schema_cls: type[BaseModel],
    consumer_paths: list[pathlib.Path],
    excluded: frozenset[str],
) -> None:
    """Pin the request side for one-shot ``*Body`` schemas
    (v2.14-WP02 / Bucket B3 carry-forward from v2.13-WP04).

    For every field declared on the body schema, the consumer route
    must reference it as an attribute access, string-literal constant
    or keyword-arg name. Otherwise the frontend can send the field
    and the backend will silently discard it.
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
        f"{[p.name for p in consumer_paths]}. WP02 *Body request-side "
        f"contract: frontend can send these fields and the backend "
        f"will silently discard them."
    )
