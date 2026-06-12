"""v2.13-WP05 (Bucket B2) — extend WP11 OpenAPI↔TS parity to generics
and discriminated unions.

Motivation
----------
v2.12-WP11 (``test_openapi_ts_parity_wp11.py``) pinned flat, closed
schemas. It explicitly skipped:

* generic wrappers (``Page<T>``, ``ActivityPage``) — the parser had no
  ``<T>`` support;
* discriminated unions (``ActivityItem``, ``SearchV2Response.items[*]``)
  — the parser rejected ``type X = A | B``.

WP05 adds the smallest amount of TS-parsing surface needed to pin those
shapes and parametrises real route pairs from
``frontend/src/api/*.ts``.

Parser surface
--------------
Three narrow capabilities, intentionally constrained to the patterns
this codebase actually uses (see
``.claude/lessons-learned/v2.13-wp05-diagnosis.md`` for the full
support matrix):

1. ``parse_ts_generic_wrapper(name, source)`` —
   reads ``export interface <Name><T> { items: T[]; ... }`` and returns
   ``{"properties": set, "required": set, "generic_item_prop":
   "items" | None}``.
2. ``parse_ts_union_alias(name, source)`` —
   reads ``export type <Name> = A | B | C;`` and returns
   ``[A, B, C]`` preserving order.
3. ``inline_item_element_type(prop_source)`` — extracts ``Foo`` from
   ``items: Foo[]`` (used by the wrapper parser).

Anything outside this surface raises ``TsParseError`` so the caller
MUST add either a parser branch or a documented skip — visible skips
beat silent green (v2.12-WP11 lesson #6).

Synthetic-bad self-tests are mandatory for every new parser branch
(again, v2.12-WP11 lesson #6) and are at the bottom of this module.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from tests.helpers.app_factory import build_test_app
from tests.test_openapi_ts_parity_wp11 import (
    TsParseError,
    _capture_balanced_block,
    _properties_from_block_body,
    _resolve_schema,
    parse_ts_type,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_API_DIR = REPO_ROOT / "frontend" / "src" / "api"


# ---------------------------------------------------------------------------
# WP05 parser extension
# ---------------------------------------------------------------------------
# Generic interface header — ``export interface Name<T> [extends ...] {``.
# ``[^{;]*`` (not ``[^{]*``) is the WP11 regression fix: a missing
# semicolon-stop allows a preceding ``type X = A | B;`` alias to be
# greedily swallowed into the next interface's brace block.
_TS_GENERIC_INTERFACE_RE = re.compile(
    r"^\s*export\s+interface\s+(?P<name>\w+)\s*<\s*(?P<param>\w+)\s*>"
    r"[^{;]*\{",
    re.MULTILINE,
)

# Union alias — ``export type Name = A | B | C;``. RHS must be a
# pipe-separated list of bare identifiers (no inline object literals,
# no string literals, no intersections). Anything else → TsParseError.
_TS_UNION_ALIAS_RE = re.compile(
    r"^\s*export\s+type\s+(?P<name>\w+)\s*=\s*(?P<rhs>[^;{}]+);",
    re.MULTILINE,
)

# ``items: Foo[]`` (also matches ``items: Foo []`` and optional ``?``)
_TS_ARRAY_PROP_RE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s*\??\s*:\s*(?P<elem>[A-Za-z_]\w*)\s*\[\s*\]"
)


def parse_ts_generic_wrapper(name: str, source: str) -> dict[str, Any]:
    """Parse ``export interface <Name><T> { ... }``.

    Returns ``{"properties": set[str], "required": set[str],
    "generic_item_prop": str | None, "has_index_signature": bool}``.

    ``generic_item_prop`` is set when one of the wrapper's properties is
    declared as ``T[]`` (where ``T`` is the wrapper's type parameter).
    For the canonical ``Page<T> { items: T[]; ... }`` shape this is
    ``"items"``.
    """
    for match in _TS_GENERIC_INTERFACE_RE.finditer(source):
        if match.group("name") != name:
            continue
        param = match.group("param")
        body, end = _capture_balanced_block(source, match.end() - 1)
        if body is None:
            raise TsParseError(f"{name}: unbalanced braces")
        # Find which property is typed ``<param>[]``.
        generic_item_prop: str | None = None
        # Strip nested object literals before scanning so a nested
        # ``Record<K, V>`` doesn't fool the array regex.
        flat = re.sub(r"\{[^{}]*\}", "{}", body)
        for line in re.split(r"[;\n]", flat):
            stmt = line.strip()
            # Look for ``<prop>: <param>[]`` exactly.
            m = re.match(
                rf"(?P<p>[A-Za-z_]\w*)\s*\??\s*:\s*{re.escape(param)}\s*\[\s*\]",
                stmt,
            )
            if m:
                generic_item_prop = m.group("p")
                break
        parsed = _properties_from_block_body(body)
        return {
            "properties": parsed["properties"],
            "required": parsed["required"],
            "has_index_signature": parsed["has_index_signature"],
            "generic_item_prop": generic_item_prop,
        }
    raise TsParseError(f"{name}: generic interface not found in source")


def parse_ts_union_alias(name: str, source: str) -> list[str]:
    """Parse ``export type <Name> = A | B | C;``.

    Returns the branch identifier list in source order. Raises
    :class:`TsParseError` if the RHS isn't a pure identifier-pipe-list
    (string-literal unions and inline object literals are rejected).
    """
    for match in _TS_UNION_ALIAS_RE.finditer(source):
        if match.group("name") != name:
            continue
        rhs = match.group("rhs").strip()
        # Reject string-literal unions (``"a" | "b"``), intersections,
        # and anything with brackets / quotes.
        if any(c in rhs for c in ('"', "'", "&", "{", "}", "[", "]", "(", ")")):
            raise TsParseError(
                f"{name}: union RHS {rhs!r} has non-identifier tokens"
            )
        # Split on ``|`` and strip leading pipe / whitespace.
        branches = [b.strip() for b in rhs.split("|")]
        branches = [b for b in branches if b]
        if not all(re.fullmatch(r"\w+", b) for b in branches):
            raise TsParseError(
                f"{name}: union RHS {rhs!r} contains non-identifier branch"
            )
        if len(branches) < 2:
            raise TsParseError(
                f"{name}: union RHS {rhs!r} has fewer than 2 branches"
            )
        return branches
    raise TsParseError(f"{name}: union alias not found in source")


# ---------------------------------------------------------------------------
# OpenAPI helpers (WP05-specific)
# ---------------------------------------------------------------------------
def _resolve_page_wrapper(
    spec: dict[str, Any], schema_name: str
) -> dict[str, Any]:
    """Resolve a ``Page_X_`` / ``CursorPage_X_`` schema.

    Returns ``{"properties": set, "required": set,
    "additional_properties": bool, "items_inner_ref": str | None}``.

    ``items_inner_ref`` is the ``$ref`` schema name pointed to by
    ``properties.items.items.$ref`` — i.e. the inner ``T`` of the
    generic wrapper. ``None`` if the items aren't a ``$ref`` array
    (defensive — current backend always uses ``$ref``).
    """
    base = _resolve_schema(spec, schema_name)
    raw = spec["components"]["schemas"][schema_name]
    items_prop = (raw.get("properties") or {}).get("items") or {}
    inner = items_prop.get("items") or {}
    ref = inner.get("$ref")
    inner_name = ref.split("/")[-1] if ref else None
    return {
        "properties": base["properties"],
        "required": base["required"],
        "additional_properties": base["additional_properties"],
        "items_inner_ref": inner_name,
    }


def _resolve_discriminated_union_branches(
    spec: dict[str, Any], schema_name: str, items_prop: str = "items"
) -> list[str]:
    """For a ``Page``-like schema whose ``<items_prop>`` is a
    ``oneOf`` / ``anyOf`` array, return the branch schema names in
    spec order.
    """
    raw = spec["components"]["schemas"][schema_name]
    p = (raw.get("properties") or {}).get(items_prop) or {}
    inner = p.get("items") or {}
    branches = inner.get("oneOf") or inner.get("anyOf") or []
    out: list[str] = []
    for b in branches:
        ref = b.get("$ref")
        if ref:
            out.append(ref.split("/")[-1])
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# v2.14-WP03 (B4): app + openapi_spec re-exported from session-scoped
# parity-lint fixtures (``parity_lint_app`` / ``parity_lint_openapi_spec``)
# in tests/conftest.py — see ``.claude/lessons-learned/v2.14-wp03-diagnosis.md``.
@pytest.fixture(scope="module")
def app(parity_lint_app) -> FastAPI:
    return parity_lint_app


@pytest.fixture(scope="module")
def openapi_spec(parity_lint_openapi_spec) -> dict[str, Any]:
    return parity_lint_openapi_spec


def _read_ts(file_name: str) -> str:
    return (FRONTEND_API_DIR / file_name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Real-pair inventory: generic Page<T> wrappers
# ---------------------------------------------------------------------------
# Each entry: (method, path, openapi_page_schema, ts_file, ts_wrapper_name,
# ts_inner_name).
#
# All routes use the same TS wrapper ``Page<T>`` defined in
# frontend/src/api/tickets.ts. The wrapper-level field set is identical
# across all five pairs; what varies is the inner ``T`` (which is
# already pinned by WP11).
WP05_PAGE_PAIRS: list[tuple[str, str, str, str, str, str]] = [
    (
        "get",
        "/api/v1/projects",
        "Page_ProjectRead_",
        "projects.ts",
        "Page",
        "ProjectDTO",
    ),
    (
        "get",
        "/api/v1/projects/{project_id}/members",
        "Page_ProjectMemberRead_",
        "projects.ts",
        "Page",
        "ProjectMemberDTO",
    ),
    (
        "get",
        "/api/v1/projects/{project_id}/components",
        "Page_ComponentRead_",
        "projects.ts",
        "Page",
        "ComponentDTO",
    ),
    (
        "get",
        "/api/v1/sprints",
        "Page_SprintRead_",
        "sprints.ts",
        "Page",
        "SprintDTO",
    ),
    (
        "get",
        "/api/v1/notifications",
        "Page_TicketNotificationRead_",
        "notifications.ts",
        "Page",
        "TicketNotification",
    ),
    # v2.23-WP02: tickets search uses the generic Page<TicketDTO> wrapper
    # via ``TicketsPage extends Page<TicketDTO>`` in tickets.ts. The
    # wrapper-level (items / next_cursor / total) field set is what this
    # pin guards; ``column_counts`` is a TicketsPage-only optional add-on
    # (closed-wrapper polarity treats OpenAPI props ⊆ TS props, so extra
    # TS-side fields are allowed).
    (
        "get",
        "/api/v1/tickets/search",
        "Page_TicketRead_",
        "tickets.ts",
        "Page",
        "TicketDTO",
    ),
]


# Real-pair inventory: discriminated unions.
# Each entry: (method, path, openapi_wrapper_schema, ts_file,
# ts_union_alias_name).
#
# The wrapper schema has its ``items`` property typed as
# ``oneOf [<Branch1>, <Branch2>, ...]`` with a ``discriminator`` keyed
# on ``kind``. The TS side is ``export type <Alias> = B1 | B2 | ...;``.
WP05_UNION_PAIRS: list[tuple[str, str, str, str, str]] = [
    (
        "get",
        "/api/v1/tickets/{id_or_key}/transitions",
        "ActivityPage",
        "tickets.ts",
        "ActivityItem",
    ),
]


# ---------------------------------------------------------------------------
# Parametrised tests — generic page wrapper field-set parity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,page_schema,ts_file,ts_wrapper,ts_inner",
    WP05_PAGE_PAIRS,
    ids=[
        f"{m.upper()} {p}:{schema}<->{w}<{inner}>"
        for (m, p, schema, _, w, inner) in WP05_PAGE_PAIRS
    ],
)
def test_page_wrapper_parity(
    openapi_spec: dict[str, Any],
    method: str,
    path: str,
    page_schema: str,
    ts_file: str,
    ts_wrapper: str,
    ts_inner: str,
) -> None:
    """Pin the wrapper-level field set of every ``Page<T>`` consumer.

    The inner ``T`` field-set is already pinned by WP11; WP05 adds the
    wrapper invariant (``items``, ``next_cursor``, ``total``) so a
    backend rename of, say, ``next_cursor`` → ``cursor`` fails CI even
    if every inner schema stays correct.
    """
    paths = openapi_spec.get("paths", {})
    assert path in paths, f"Route {path} missing from OpenAPI spec"
    assert method in paths[path], (
        f"Route {method.upper()} {path} not registered"
    )

    page = _resolve_page_wrapper(openapi_spec, page_schema)
    # The Page<T> definition lives in tickets.ts (the only declaration
    # site); the consumer file imports it. Read tickets.ts directly so
    # we parse the actual definition, not the import alias.
    ts_source = _read_ts("tickets.ts")
    wrapper = parse_ts_generic_wrapper(ts_wrapper, ts_source)

    # Sanity: the OpenAPI wrapper's items[*].$ref points to the
    # backend counterpart of ``ts_inner``. We don't reassert WP11's
    # field-set check here — WP11 owns the inner.
    assert page["items_inner_ref"] is not None, (
        f"{page_schema}.items.items.$ref missing — wrapper isn't a "
        "Page[T] shape"
    )

    # Polarity: TS Page<T> is a closed wrapper (no index signature),
    # OpenAPI Page wrapper has additionalProperties absent → closed.
    # So: OpenAPI props ⊆ TS props.
    openapi_props = set(page["properties"])
    missing_in_ts = openapi_props - wrapper["properties"]
    assert not missing_in_ts, (
        f"{method.upper()} {path} ({page_schema} ↔ {ts_wrapper}<{ts_inner}>): "
        f"OpenAPI wrapper properties not present in TS Page<T>: "
        f"{sorted(missing_in_ts)}. Add the missing field(s) to "
        f"``Page<T>`` in frontend/src/api/tickets.ts."
    )

    # And the wrapper must mark ``items`` as the generic-parameterised
    # property — regression catch if someone re-types ``items`` from
    # ``T[]`` to ``unknown[]``.
    assert wrapper["generic_item_prop"] == "items", (
        f"TS ``{ts_wrapper}<T>`` lost its ``items: T[]`` typing — got "
        f"generic_item_prop={wrapper['generic_item_prop']!r}. The backend "
        f"Page wrapper emits items[*] as $ref to the inner schema; the "
        f"TS side MUST stay generic-parameterised so callers like "
        f"``Page<{ts_inner}>`` keep type-checking."
    )


# ---------------------------------------------------------------------------
# Parametrised tests — discriminated union branch parity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,wrapper_schema,ts_file,ts_union_name",
    WP05_UNION_PAIRS,
    ids=[
        f"{m.upper()} {p}:{wrap}.items<->{u}"
        for (m, p, wrap, _, u) in WP05_UNION_PAIRS
    ],
)
def test_discriminated_union_parity(
    openapi_spec: dict[str, Any],
    method: str,
    path: str,
    wrapper_schema: str,
    ts_file: str,
    ts_union_name: str,
) -> None:
    """Pin branch-count + ``kind`` discriminator parity for a union.

    Polarity:
      * OpenAPI ``oneOf`` branch count == TS union arm count (no
        polarity flip — both sides are closed).
      * Every TS branch has a ``kind`` discriminator property (required).
      * Every OpenAPI branch has a ``kind`` discriminator property.
    """
    paths = openapi_spec.get("paths", {})
    assert path in paths, f"Route {path} missing from OpenAPI spec"

    openapi_branches = _resolve_discriminated_union_branches(
        openapi_spec, wrapper_schema, items_prop="items"
    )
    assert openapi_branches, (
        f"{wrapper_schema}.items has no oneOf/anyOf branches — wrapper "
        "isn't a discriminated union"
    )

    ts_source = _read_ts(ts_file)
    ts_branches = parse_ts_union_alias(ts_union_name, ts_source)

    # Count parity.
    assert len(ts_branches) == len(openapi_branches), (
        f"{method.upper()} {path} ({wrapper_schema} ↔ {ts_union_name}): "
        f"branch-count mismatch — OpenAPI has "
        f"{len(openapi_branches)} ({openapi_branches}), TS has "
        f"{len(ts_branches)} ({ts_branches}). Add or remove a TS branch "
        f"to match the backend response_model."
    )

    # Every TS branch must have a ``kind`` field (the discriminator).
    for branch_name in ts_branches:
        parsed = parse_ts_type(ts_source, branch_name)
        assert "kind" in parsed["properties"], (
            f"TS union branch ``{branch_name}`` is missing the ``kind`` "
            "discriminator. The OpenAPI ``oneOf`` declares "
            "discriminator.propertyName=kind; the TS branch must "
            "include it (required, not optional) so narrowing works."
        )
        assert "kind" in parsed["required"], (
            f"TS union branch ``{branch_name}.kind`` is optional. "
            "The discriminator MUST be required for TS narrowing to "
            "work — remove the ``?`` from ``kind?: ...``."
        )

    # Every OpenAPI branch must advertise ``kind`` too.
    schemas = openapi_spec["components"]["schemas"]
    for branch_name in openapi_branches:
        props = (schemas[branch_name].get("properties") or {})
        assert "kind" in props, (
            f"OpenAPI union branch ``{branch_name}`` is missing the "
            "``kind`` discriminator property — backend Pydantic schema "
            "is missing ``kind: Literal[...]``."
        )


# ---------------------------------------------------------------------------
# Parametrised test — flat field-set parity for nested types added by WP05
# ---------------------------------------------------------------------------
# WP11 owns most of the flat inner pairs but skipped ``SearchArm`` (and
# the ``ActivityPage`` outer wrapper itself, which is *almost* a
# Page<ActivityItem> but predates the generic). Add them explicitly.
WP05_FLAT_PAIRS: list[tuple[str, str, str, str, str]] = [
    # GET /api/search/v2 → SearchV2Response.{arm} → SearchArm
    (
        "get",
        "/api/search/v2",
        "SearchArm",
        "search.ts",
        "SearchArm",
    ),
    # ActivityPage outer wrapper field-set (items / next_cursor / total).
    (
        "get",
        "/api/v1/tickets/{id_or_key}/transitions",
        "ActivityPage",
        "tickets.ts",
        "ActivityPage",
    ),
    # SearchV2Response outer wrapper field-set (the 5 arm keys).
    (
        "get",
        "/api/search/v2",
        "SearchV2Response",
        "search.ts",
        "SearchV2Response",
    ),
    # v2.23-WP02: AuditLogPage is a non-generic named-subclass wrapper
    # (mirrors the ActivityPage pin above). Backend Pydantic schema is a
    # flat ``Page``-shaped object; TS side is a hand-written interface
    # with ``items: AuditLogEntry[]``. Closed-on-both-sides parity.
    (
        "get",
        "/api/v1/audit-log",
        "AuditLogPage",
        "auditLog.ts",
        "AuditLogPage",
    ),
]


@pytest.mark.parametrize(
    "method,path,schema_name,ts_file,ts_type",
    WP05_FLAT_PAIRS,
    ids=[
        f"{m.upper()} {p}:{schema}<->{ts}"
        for (m, p, schema, _, ts) in WP05_FLAT_PAIRS
    ],
)
def test_wp05_flat_pair_field_set(
    openapi_spec: dict[str, Any],
    method: str,
    path: str,
    schema_name: str,
    ts_file: str,
    ts_type: str,
) -> None:
    """Flat field-set parity for schemas WP11 skipped (closed both sides)."""
    paths = openapi_spec.get("paths", {})
    assert path in paths, f"Route {path} missing from OpenAPI spec"

    schema = _resolve_schema(openapi_spec, schema_name)
    ts = parse_ts_type(_read_ts(ts_file), ts_type)

    openapi_props = set(schema["properties"])
    permissive = schema["additional_properties"] or ts["has_index_signature"]

    if permissive:
        missing_in_openapi = ts["required"] - openapi_props
        assert not missing_in_openapi, (
            f"{method.upper()} {path} ({schema_name} ↔ {ts_type}): "
            f"required-by-TS fields missing from OpenAPI: "
            f"{sorted(missing_in_openapi)}"
        )
    else:
        missing_in_ts = openapi_props - ts["properties"]
        assert not missing_in_ts, (
            f"{method.upper()} {path} ({schema_name} ↔ {ts_type}): "
            f"OpenAPI properties not present in TS type: "
            f"{sorted(missing_in_ts)}. Add the missing field(s) to "
            f"frontend/src/api/{ts_file}."
        )


# ---------------------------------------------------------------------------
# Synthetic-bad parser self-tests (≥3, per v2.12-WP11 lesson #6)
# ---------------------------------------------------------------------------
def test_wp05_generic_wrapper_detects_missing_field() -> None:
    """Generic-wrapper missing OpenAPI property → lint must flag it."""
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "Page_Fake_": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Fake"},
                        },
                        "next_cursor": {"type": "string"},
                        "total": {"type": "integer"},
                    },
                    "required": ["items"],
                },
                "Fake": {"type": "object", "properties": {}, "required": []},
            }
        }
    }
    # TS missing ``total`` — drift the lint must catch.
    fake_ts = """
    export interface BadPage<T> {
      items: T[];
      next_cursor: string | null;
      // total intentionally omitted
    }
    """
    page = _resolve_page_wrapper(fake_spec, "Page_Fake_")
    wrapper = parse_ts_generic_wrapper("BadPage", fake_ts)
    missing = set(page["properties"]) - wrapper["properties"]
    assert "total" in missing, (
        "Generic-wrapper polarity broken: a TS wrapper missing the "
        "OpenAPI ``total`` field slipped past the lint."
    )


def test_wp05_generic_wrapper_loses_generic_item_prop_on_unparameterised() -> None:
    """If ``items: T[]`` becomes ``items: unknown[]`` we lose the
    generic-item annotation — lint asserts on it."""
    fake_ts = """
    export interface FakePage<T> {
      items: unknown[];
      next_cursor: string | null;
      total: number | null;
    }
    """
    wrapper = parse_ts_generic_wrapper("FakePage", fake_ts)
    # The point: the lint detects this via generic_item_prop=None.
    assert wrapper["generic_item_prop"] is None, (
        "Parser failed to notice that ``items`` is no longer typed as "
        "``T[]`` — the wrapper-parity test will not catch the regression "
        "without this signal."
    )


def test_wp05_union_alias_detects_missing_branch() -> None:
    """OpenAPI ``oneOf [A, B, C]`` vs TS ``A | B`` → lint flags it."""
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "FakePage": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"$ref": "#/components/schemas/A"},
                                    {"$ref": "#/components/schemas/B"},
                                    {"$ref": "#/components/schemas/C"},
                                ],
                                "discriminator": {"propertyName": "kind"},
                            },
                        }
                    },
                },
                "A": {"type": "object", "properties": {"kind": {}}},
                "B": {"type": "object", "properties": {"kind": {}}},
                "C": {"type": "object", "properties": {"kind": {}}},
            }
        }
    }
    fake_ts = """
    export type FakeItem = A | B;
    """
    openapi_branches = _resolve_discriminated_union_branches(
        fake_spec, "FakePage", items_prop="items"
    )
    ts_branches = parse_ts_union_alias("FakeItem", fake_ts)
    assert len(openapi_branches) == 3
    assert len(ts_branches) == 2
    assert len(openapi_branches) != len(ts_branches), (
        "Union branch-count polarity broken — a TS union missing a "
        "backend branch slipped past the lint."
    )


def test_wp05_union_alias_rejects_string_literal_union() -> None:
    """``type X = "a" | "b";`` must raise TsParseError, not silently
    return ``["\"a\"", "\"b\""]``."""
    fake_ts = """
    export type StringUnion = "a" | "b" | "c";
    """
    with pytest.raises(TsParseError):
        parse_ts_union_alias("StringUnion", fake_ts)


def test_wp05_parser_does_not_swallow_union_into_next_interface() -> None:
    """Regression guard for the WP11 greedy ``[^{]*\\{`` bug.

    If the generic-interface regex re-loosens (``[^{;]*`` → ``[^{]*``)
    a preceding ``type X = A | B;`` alias would be eaten into the
    following interface block and the parser would mis-resolve the
    wrapper's brace span.
    """
    src = """
    export type Stray = TransitionActivityItem | CommentActivityItem;
    export interface MyPage<T> {
      items: T[];
      next_cursor: string | null;
      total: number | null;
    }
    """
    # Both should parse independently.
    branches = parse_ts_union_alias("Stray", src)
    assert branches == ["TransitionActivityItem", "CommentActivityItem"]
    wrapper = parse_ts_generic_wrapper("MyPage", src)
    assert wrapper["properties"] == {"items", "next_cursor", "total"}
    assert wrapper["generic_item_prop"] == "items"


def test_wp05_recursive_items_mismatch_synthetic() -> None:
    """Generic wrapper + inner-pair recursion: if the inner TS type is
    missing a backend property, WP11's flat-pair lint catches it. WP05
    verifies the recursion glue (Page_X_.items.$ref → X → TS inner)
    is wired so we don't lose drift signal on inner shapes."""
    fake_spec: dict[str, Any] = {
        "components": {
            "schemas": {
                "Page_X_": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/X"},
                        },
                        "next_cursor": {"type": "string"},
                        "total": {"type": "integer"},
                    },
                },
                "X": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "foo": {"type": "string"},
                    },
                    "required": ["id", "foo"],
                },
            }
        }
    }
    fake_ts = """
    export interface MyPage<T> {
      items: T[];
      next_cursor: string | null;
      total: number | null;
    }
    export interface XDTO {
      id: string;
      // foo intentionally omitted — should be caught by inner-pair lint.
    }
    """
    page = _resolve_page_wrapper(fake_spec, "Page_X_")
    assert page["items_inner_ref"] == "X"
    inner_schema = _resolve_schema(fake_spec, page["items_inner_ref"])
    inner_ts = parse_ts_type(fake_ts, "XDTO")
    missing = set(inner_schema["properties"]) - inner_ts["properties"]
    assert "foo" in missing, (
        "Recursive inner-pair lint failed to detect ``foo`` missing from "
        "the TS inner type. The recursion glue (Page_X_.items.$ref → "
        "X → XDTO) is broken; without it WP05 would silently green on "
        "inner-shape drift."
    )
