"""v2.11-WP06 — Page[T] adoption assertions.

These tests pin the OpenAPI shape of seven ad-hoc paged-list routes that
were converted from raw ``dict[str, Any]`` returns to typed
``Page[ItemSchema]`` response_models in v2.11-WP06.

For each route we assert two things:

1. The OpenAPI ``responses.200`` schema $ref resolves to a definition that
   has Page[T]'s exact field set (``items``, ``next_cursor``, ``total``)
   and no extra keys (no ad-hoc ``limit``/``offset`` leakage).
2. The route handler returns a real Page[T] instance at runtime — i.e. an
   actual GET against an empty backend yields ``items=[]`` plus the
   ``next_cursor`` and ``total`` keys.

These are NOT regression-style end-to-end tests; they're structural pins
that fail loudly if a future refactor drops the response_model annotation
or replaces it with an inline dict.
"""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from tests.helpers.app_factory import build_test_app


def _resolve_schema(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a ``#/components/schemas/<Name>`` reference."""
    assert ref.startswith("#/components/schemas/"), ref
    name = ref.split("/")[-1]
    return spec["components"]["schemas"][name]


def _response_schema(spec: dict[str, Any], path: str, method: str = "get") -> dict[str, Any]:
    op = spec["paths"][path][method]
    media = op["responses"]["200"]["content"]["application/json"]
    schema = media["schema"]
    # Page[T] is a concrete generic class FastAPI registers as Page_T_.
    if "$ref" in schema:
        return _resolve_schema(spec, schema["$ref"])
    return schema


def _build_openapi_app():
    """Assemble an app that mounts every WP06 route via real create_app()."""
    return build_test_app()


# Each tuple: (description, openapi_path)
# These mirror the seven WP06 call-sites enumerated in the v2.11 diagnosis.
WP06_PAGED_ROUTES = [
    ("agents.activity", "/api/v1/agents/activity"),
    ("agents.activity.compat", "/api/agents/activity"),
    ("projects.list", "/api/v1/projects"),
    ("projects.members.list", "/api/v1/projects/{project_id}/members"),
    ("projects.components.list", "/api/v1/projects/{project_id}/components"),
    ("sprints.list", "/api/v1/sprints"),
    ("tickets.search", "/api/v1/tickets/search"),
    ("tickets.watchers.list", "/api/v1/tickets/{id_or_key}/watchers"),
    ("tickets.attachments.list", "/api/v1/tickets/{id_or_key}/attachments"),
]


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    app = _build_openapi_app()
    return app.openapi()


@pytest.mark.parametrize("label,path", WP06_PAGED_ROUTES, ids=[r[0] for r in WP06_PAGED_ROUTES])
def test_route_declares_page_t_response_model(
    openapi_spec: dict[str, Any], label: str, path: str
) -> None:
    """G3: each WP06 paged-list route declares a Page[T] response_model.

    The resolved 200 schema must:
      * have exactly the Page[T] field set ``{items, next_cursor, total}``
      * NOT carry an ad-hoc ``limit`` or ``offset`` property
    """
    schema = _response_schema(openapi_spec, path)
    properties = set(schema.get("properties", {}).keys())
    assert properties == {"items", "next_cursor", "total"}, (
        f"{label} ({path}) response_model is not Page[T]; got properties={sorted(properties)}"
    )
    # Belt-and-braces: route MUST NOT leak the old ad-hoc keys.
    assert "limit" not in properties, f"{label}: limit leaked into response schema"
    assert "offset" not in properties, f"{label}: offset leaked into response schema"


@pytest.mark.parametrize("label,path", WP06_PAGED_ROUTES, ids=[r[0] for r in WP06_PAGED_ROUTES])
def test_route_response_schema_name_is_page_generic(
    openapi_spec: dict[str, Any], label: str, path: str
) -> None:
    """G3 (stronger): the OpenAPI schema name resolves to a Page[...] alias.

    FastAPI registers ``Page[X]`` as ``Page_X_`` (or similar). The schema
    name being ``Page_<item>_`` (rather than an inline anonymous shape)
    confirms the route uses ``response_model=Page[Item]``.
    """
    op = openapi_spec["paths"][path]["get"]
    media = op["responses"]["200"]["content"]["application/json"]
    schema = media["schema"]
    assert "$ref" in schema, (
        f"{label}: 200 response is inline (no $ref) — likely missing response_model"
    )
    name = schema["$ref"].split("/")[-1]
    assert name.startswith("Page_") or name == "TicketsPage" or name == "ActivityPage", (
        f"{label}: $ref={name!r} doesn't look like a Page[T] alias"
    )


# --- Runtime smoke (G2): an actual GET returns Page[T] keys ----------------

@pytest.mark.asyncio
async def test_agents_activity_runtime_shape_is_page_t(db) -> None:
    """G2: ``GET /api/agents/activity`` returns the Page[T] envelope."""

    async def _override_db():
        yield db

    app = build_test_app(dependency_overrides={get_db: _override_db})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/agents/activity?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Page[T] keys exist…
    assert set(body.keys()) >= {"items", "next_cursor", "total"}
    assert isinstance(body["items"], list)
    # …and the old ad-hoc keys are gone.
    assert "limit" not in body
    assert "offset" not in body
