"""v2.12-WP11 (Bucket C3) — OpenAPI vs frontend ``*.ts`` parity lint.

Motivation
----------
v2.11-WP07 caught a latent ``TicketRead`` narrowing only because WP06's
OpenAPI introspection tests pinned the schema shape. WP11 generalises
the invariant: every response schema in ``app.main:app.openapi()`` for
an in-scope route should match (or be a superset of) the corresponding
TypeScript response type in ``frontend/src/api/*.ts``. Field-level
drift fails CI rather than waiting for a runtime bug.

Polarity
--------
For each in-scope route we resolve the success-response schema in
``components.schemas`` (chasing ``$ref`` / ``allOf``) and compare its
property names against the matching TS ``export interface`` /
``export type Foo = { ... }`` block:

* **Closed OpenAPI schema** (``additionalProperties`` falsy and TS type
  has no ``[k: string]: unknown`` index signature) →
  ``OpenAPI props ⊆ TS props`` — a missing TS field fails the test.
* **Permissive on either side** (Pydantic ``extra="allow"`` →
  ``additionalProperties: true`` on the OpenAPI side, or a TS catch-all
  index signature like ``[k: string]: unknown``) → flip the polarity to
  ``REQUIRED TS props ⊆ OpenAPI props``. Same reasoning as v2.12-WP03:
  permissive shapes can carry arbitrary backend keys, so we only pin
  the *required-by-TS* contract.

The TS parser is intentionally simple — it walks the source as text
and looks for one ``export (interface|type) <Name>`` block, captures
identifier tokens before ``:``/``?:`` at brace-depth 1, and ignores
nested object literals. It rejects union/intersection RHS types so
``type X = A | B`` style declarations are *not* in scope (caught by
the in-scope inventory rather than the parser).

A synthetic-bad self-test in this module verifies the polarity
direction so a parser regression cannot silently disable the lint.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from tests.helpers.app_factory import build_test_app


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_API_DIR = REPO_ROOT / "frontend" / "src" / "api"


# ---------------------------------------------------------------------------
# In-scope route inventory
# ---------------------------------------------------------------------------
# Each entry: (method, path, openapi_schema_name, ts_file, ts_type_name).
#
# Inclusion rule: the backend route declares ``response_model=`` (so the
# OpenAPI schema is named, not inline) AND the matching frontend client
# uses a hand-written ``export interface`` / ``export type X = {...}``
# for the response. Routes whose frontend response is ``unknown`` /
# ``any`` / an inline shape are deliberately omitted (see SKIPPED list
# below).
WP11_ROUTES: list[tuple[str, str, str, str, str]] = [
    # GET /api/v1/projects/{idOrKey} → ProjectRead ↔ ProjectDTO
    (
        "get",
        "/api/v1/projects/{id_or_key}",
        "ProjectRead",
        "projects.ts",
        "ProjectDTO",
    ),
    # GET /api/v1/projects/{id}/members.items[*] → ProjectMemberRead ↔
    # ProjectMemberDTO. The list endpoint wraps in ``{items: [...]}`` but
    # the per-item shape is what drifts, so we pin the inner schema.
    (
        "get",
        "/api/v1/projects/{project_id}/members",
        "ProjectMemberRead",
        "projects.ts",
        "ProjectMemberDTO",
    ),
    # GET /api/v1/projects/{id}/components.items[*] → ComponentRead ↔
    # ComponentDTO.
    (
        "get",
        "/api/v1/projects/{project_id}/components",
        "ComponentRead",
        "projects.ts",
        "ComponentDTO",
    ),
    # GET /api/v1/sprints/{id} → SprintRead ↔ SprintDTO
    (
        "get",
        "/api/v1/sprints/{sprint_id}",
        "SprintRead",
        "sprints.ts",
        "SprintDTO",
    ),
    # GET /api/v1/people/search → PeopleSearchResponse ↔ PeopleSearchResponse
    (
        "get",
        "/api/v1/people/search",
        "PeopleSearchResponse",
        "people.ts",
        "PeopleSearchResponse",
    ),
    # PATCH /api/v1/users/me/handle → UserHandleResponse ↔ UpdateHandleResponse
    (
        "patch",
        "/api/v1/users/me/handle",
        "UserHandleResponse",
        "users.ts",
        "UpdateHandleResponse",
    ),
    # POST /api/v1/tickets/{id_or_key}/comments → TicketCommentRead ↔ CommentDTO
    (
        "post",
        "/api/v1/tickets/{id_or_key}/comments",
        "TicketCommentRead",
        "tickets.ts",
        "CommentDTO",
    ),
    # POST /api/v1/tickets/{id_or_key}/links → TicketLinkRead ↔ LinkDTO
    (
        "post",
        "/api/v1/tickets/{id_or_key}/links",
        "TicketLinkRead",
        "tickets.ts",
        "LinkDTO",
    ),
    # GET /api/v1/notifications.items[*] → TicketNotificationRead ↔
    # TicketNotification
    (
        "get",
        "/api/v1/notifications",
        "TicketNotificationRead",
        "notifications.ts",
        "TicketNotification",
    ),
    # v2.22-WP03: coverage expansion ----------------------------------------
    # GET /api/v1/agents/activity.items[*] → AgentActivityItem ↔ ActivityEntry.
    # The route declares ``response_model=Page[AgentActivityItem]``; we pin
    # the inner-item schema (same precedent as TicketNotificationRead).
    (
        "get",
        "/api/v1/agents/activity",
        "AgentActivityItem",
        "audit.ts",
        "ActivityEntry",
    ),
    # GET /api/v1/audit-log.items[*] → AuditLogEntryRead ↔ AuditLogEntry.
    # The skip-list note in this module flagged AuditLogEntry as "punted
    # for now to keep the parser surface small; can be added incrementally
    # without re-architecting" — v2.22-WP03 picks it up.
    (
        "get",
        "/api/v1/audit-log",
        "AuditLogEntryRead",
        "auditLog.ts",
        "AuditLogEntry",
    ),
    # GET /api/v1/audit-log.items[*].actor → PersonRef ↔ AuditLogActor.
    # Different TS name for the same backend schema — both interfaces
    # consume the response so both contracts are pinned.
    (
        "get",
        "/api/v1/audit-log",
        "PersonRef",
        "auditLog.ts",
        "AuditLogActor",
    ),
    # GET /api/v1/people/search.items[*] → PersonRef ↔ PersonRef
    # (people.ts). The outer envelope ``PeopleSearchResponse`` is already
    # pinned; this pin covers the inner-item shape directly.
    (
        "get",
        "/api/v1/people/search",
        "PersonRef",
        "people.ts",
        "PersonRef",
    ),
    # GET /api/v1/notifications.items[*].actor → PersonRef ↔ PersonRef
    # (notifications.ts). The actor block is a separate hand-written TS
    # type alias in notifications.ts; pinned alongside the existing
    # TicketNotification entry above.
    (
        "get",
        "/api/v1/notifications",
        "PersonRef",
        "notifications.ts",
        "PersonRef",
    ),
]


# Documented skip-list (in-test discoverability matters more than a
# parametrised skip — these are decisions, not pending work).
#
# - ``TicketRead`` ↔ ``TicketDTO``: TicketRead is ``extra="allow"`` AND
#   TicketDTO has ``[k: string]: unknown`` — both sides are permissive
#   so a property-set test would be a near-tautology. WP07 already
#   pins the response-model wiring.
# - ``Page_*`` / ``CursorPage_*`` / ``ActivityPage``: TypeScript-side
#   generics (``Page<T>``) and discriminated unions (``ActivityItem``)
#   exceed the parser's "flat interface" support.
# - ``SearchV2Response`` / ``SearchArm`` / ``SearchItem``: SearchItem is
#   ``extra="allow"`` and the TS side adds a catch-all index — same
#   reason as TicketRead/TicketDTO. SearchV2Response has only optional
#   arm-keys; field-set parity adds no signal over WP07-style pins.
# - ``AuditLogEntryRead`` ↔ ``AuditLogEntry``: outer page exposes only
#   ``items``/``next_cursor``/``total`` and the inner shape is asserted
#   by the JSON-only smoke tests in tests/routes/test_audit_log.py.
#   Punted for now to keep the parser's surface area small; can be
#   added incrementally without re-architecting the lint.


# ---------------------------------------------------------------------------
# OpenAPI helpers
# ---------------------------------------------------------------------------
# v2.14-WP03 (B4): app + openapi_spec are now thin re-exports of the
# session-scoped fixtures in tests/conftest.py
# (``parity_lint_app`` / ``parity_lint_openapi_spec``). This eliminates
# the duplicate ``build_test_app()`` boot paid when both parity-lint
# modules run in the same session. See
# ``.claude/lessons-learned/v2.14-wp03-diagnosis.md``.
@pytest.fixture(scope="module")
def app(parity_lint_app) -> FastAPI:
    return parity_lint_app


@pytest.fixture(scope="module")
def openapi_spec(parity_lint_openapi_spec) -> dict[str, Any]:
    return parity_lint_openapi_spec


def _resolve_schema(
    spec: dict[str, Any], schema_name: str
) -> dict[str, Any]:
    """Resolve ``components.schemas.<name>`` and flatten ``allOf`` once.

    Pydantic inheritance shows up as ``allOf: [<base>, <self>]``. We
    recurse one level — sufficient for the current schemas — and union
    the resulting ``properties`` dicts.
    """
    schemas = spec["components"]["schemas"]
    raw = schemas[schema_name]
    properties: dict[str, Any] = dict(raw.get("properties", {}))
    additional = raw.get("additionalProperties")
    for branch in raw.get("allOf", []) or []:
        if "$ref" in branch:
            ref = branch["$ref"].split("/")[-1]
            sub = _resolve_schema(spec, ref)
            for k, v in sub["properties"].items():
                properties.setdefault(k, v)
            if sub.get("additional_properties") and additional is None:
                additional = True
        else:
            for k, v in (branch.get("properties") or {}).items():
                properties.setdefault(k, v)
    required = set(raw.get("required") or [])
    return {
        "properties": properties,
        "required": required,
        # Pydantic v2 emits ``additionalProperties: true`` only when the
        # model has ``extra="allow"``; absence means closed.
        "additional_properties": bool(additional),
    }


# ---------------------------------------------------------------------------
# TypeScript parser
# ---------------------------------------------------------------------------
# Look for either:
#   export interface <Name> [extends ...] { ... }
#   export type <Name> = { ... }
# and capture the brace block.
_TS_BLOCK_RE = re.compile(
    # ``[^{;]*`` stops at ``;`` so union-typed aliases like
    # ``export type X = "a" | "b";`` do not greedily swallow the
    # following ``export interface ... {`` block. Leading ``\s*``
    # tolerates indented synthetic test fixtures while still matching
    # column-0 declarations in real ``frontend/src/api/*.ts`` files.
    r"^\s*export\s+(?:interface|type)\s+(?P<name>\w+)\b[^{;]*\{",
    re.MULTILINE,
)


class TsParseError(Exception):
    """Raised when the parser cannot extract a flat-shape TS type."""


def parse_ts_type(source: str, type_name: str) -> dict[str, Any]:
    """Extract property names + index-signature flag for one TS type.

    Returns ``{"properties": set[str], "required": set[str],
    "has_index_signature": bool}``.

    ``required`` is the set of properties WITHOUT a ``?`` modifier —
    i.e. the strictly required-by-TS contract. ``properties`` is the
    full set (required ∪ optional).

    Limitations (documented at module level): RHS unions /
    intersections / generics are unsupported — the parser raises
    :class:`TsParseError` so the caller can document a skip.
    """
    for match in _TS_BLOCK_RE.finditer(source):
        if match.group("name") != type_name:
            continue
        # Refuse unions/intersections on the RHS, e.g.
        # ``export type X = A | { ... }``. Look at the text between
        # the ``=`` (if any) and the opening ``{``.
        head = source[match.start() : match.start("name") + 1]
        eq_idx = source.find("=", match.start("name"), match.start() + match.end() - match.start())
        if eq_idx != -1:
            between = source[eq_idx + 1 : match.end() - 1]
            if "|" in between or "&" in between:
                raise TsParseError(
                    f"{type_name}: union/intersection RHS unsupported"
                )
        # Walk braces from match.end() (we're right after the opening ``{``).
        body, end = _capture_balanced_block(source, match.end() - 1)
        if body is None:
            raise TsParseError(f"{type_name}: unbalanced braces")
        return _properties_from_block_body(body)
    raise TsParseError(f"{type_name}: not found in source")


def _capture_balanced_block(source: str, brace_start: int) -> tuple[str | None, int]:
    """Return the content between matching braces starting at ``brace_start``."""
    assert source[brace_start] == "{"
    depth = 0
    i = brace_start
    in_str: str | None = None
    while i < len(source):
        c = source[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'", "`"):
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : i], i + 1
        i += 1
    return None, -1


def _properties_from_block_body(body: str) -> dict[str, Any]:
    """Extract field metadata from the body of a TS interface block."""
    properties: set[str] = set()
    required: set[str] = set()
    has_index_signature = False
    # Strip nested braces so we only see top-level fields. Replace each
    # balanced ``{...}`` with a placeholder.
    flat = _strip_nested_braces(body)
    # Also strip single-line and block comments so they don't confuse
    # the property regex.
    flat = re.sub(r"/\*.*?\*/", "", flat, flags=re.DOTALL)
    flat = re.sub(r"//[^\n]*", "", flat)
    # Split on ``;`` or newline — TS allows either as a statement
    # terminator inside object types.
    for raw in re.split(r"[;\n]", flat):
        stmt = raw.strip().rstrip(",")
        if not stmt:
            continue
        # Index signature: ``[key: string]: unknown`` etc.
        if stmt.startswith("["):
            has_index_signature = True
            continue
        # Method-like / readonly modifier stripping.
        m = re.match(r"(?:readonly\s+)?(?P<name>[A-Za-z_]\w*)\s*(?P<opt>\??)\s*:", stmt)
        if not m:
            continue
        name = m.group("name")
        properties.add(name)
        if not m.group("opt"):
            required.add(name)
    return {
        "properties": properties,
        "required": required,
        "has_index_signature": has_index_signature,
    }


def _strip_nested_braces(body: str) -> str:
    """Replace each balanced ``{...}`` inside ``body`` with a placeholder."""
    out: list[str] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "{":
            _, end = _capture_balanced_block(body, i)
            if end < 0:
                # Unbalanced — bail and append the rest unchanged.
                out.append(body[i:])
                break
            out.append("__NESTED__")
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Self-test for parser polarity (synthetic bad fixture).
# ---------------------------------------------------------------------------
def test_parser_self_test_detects_missing_field() -> None:
    """Polarity invariant: a TS type missing an OpenAPI property fails.

    Build a hand-rolled OpenAPI fragment + TS source pair where the TS
    side is *missing* a backend property. The lint logic — reused in
    the parametrised test — must flag it.
    """
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "FakeResp": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "secret_new_field": {"type": "string"},
                    },
                    "required": ["id", "title", "secret_new_field"],
                    # additionalProperties absent → closed
                }
            }
        }
    }
    fake_ts = """
    export interface FakeResp {
      id: string;
      title: string;
      // secret_new_field intentionally omitted
    }
    """
    schema = _resolve_schema(fake_spec, "FakeResp")
    ts = parse_ts_type(fake_ts, "FakeResp")
    # Closed schema → OpenAPI ⊆ TS.
    missing = set(schema["properties"]) - ts["properties"]
    assert "secret_new_field" in missing, (
        "Parser failed to detect a missing field. Polarity is broken: "
        "without this guard a regression of either parser or comparison "
        "logic could silently let drift slip through CI."
    )


def test_parser_self_test_accepts_extra_ts_fields() -> None:
    """A TS-only field is not a failure for a closed OpenAPI schema."""
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "FakeResp": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                }
            }
        }
    }
    fake_ts = """
    export interface FakeResp {
      id: string;
      ui_only_field?: string;
    }
    """
    schema = _resolve_schema(fake_spec, "FakeResp")
    ts = parse_ts_type(fake_ts, "FakeResp")
    missing = set(schema["properties"]) - ts["properties"]
    assert not missing


def test_parser_self_test_permissive_flips_polarity() -> None:
    """If OpenAPI is ``additionalProperties: true`` we test the reverse."""
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "FakeResp": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                    "additionalProperties": True,
                }
            }
        }
    }
    # TS declares a required field that the backend does NOT advertise —
    # this should fail because the backend cannot honour the contract.
    fake_ts = """
    export interface FakeResp {
      id: string;
      ts_only_required: string;
    }
    """
    schema = _resolve_schema(fake_spec, "FakeResp")
    ts = parse_ts_type(fake_ts, "FakeResp")
    assert schema["additional_properties"] is True
    ts_required_missing_from_openapi = (
        ts["required"] - set(schema["properties"])
    )
    assert "ts_only_required" in ts_required_missing_from_openapi


# ---------------------------------------------------------------------------
# Parametrised parity tests
# ---------------------------------------------------------------------------
def _read_ts(file_name: str) -> str:
    return (FRONTEND_API_DIR / file_name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "method,path,schema_name,ts_file,ts_type",
    WP11_ROUTES,
    ids=[
        f"{m.upper()} {p}:{schema}<->{ts}"
        for (m, p, schema, _, ts) in WP11_ROUTES
    ],
)
def test_openapi_ts_parity(
    openapi_spec: dict[str, Any],
    method: str,
    path: str,
    schema_name: str,
    ts_file: str,
    ts_type: str,
) -> None:
    """Pin field-set parity between an OpenAPI schema and its TS type.

    Polarity:
      * If either side is permissive (OpenAPI ``extra=allow`` or TS has
        a ``[k: string]: unknown`` index signature) → REQUIRED TS props
        must all appear in OpenAPI.
      * Otherwise → OpenAPI props ⊆ TS props (extra TS-only optional
        fields are tolerated).
    """
    # Sanity check the route is wired (no silent skip if the path moves).
    paths = openapi_spec.get("paths", {})
    assert path in paths, f"Route {path} missing from OpenAPI spec"
    assert method in paths[path], (
        f"Route {method.upper()} {path} not registered (have: "
        f"{list(paths[path].keys())})"
    )

    schema = _resolve_schema(openapi_spec, schema_name)
    ts = parse_ts_type(_read_ts(ts_file), ts_type)

    openapi_props = set(schema["properties"])
    permissive = schema["additional_properties"] or ts["has_index_signature"]

    if permissive:
        # Backend can return extra keys (or TS allows them) — only pin
        # the REQUIRED-by-TS contract.
        missing_in_openapi = ts["required"] - openapi_props
        assert not missing_in_openapi, (
            f"{method.upper()} {path} ({schema_name} ↔ {ts_type}): "
            f"required-by-TS fields missing from OpenAPI: "
            f"{sorted(missing_in_openapi)}. The TS client declares them "
            "required but the backend response_model does not advertise "
            "them — either drop the TS field or add it to the Pydantic "
            "schema."
        )
    else:
        missing_in_ts = openapi_props - ts["properties"]
        assert not missing_in_ts, (
            f"{method.upper()} {path} ({schema_name} ↔ {ts_type}): "
            f"OpenAPI properties not present in TS type: "
            f"{sorted(missing_in_ts)}. Add the missing field(s) to "
            f"frontend/src/api/{ts_file} or convert the TS type to use "
            f"a ``[k: string]: unknown`` index signature if the field "
            "is intentionally absent from the typed contract."
        )
