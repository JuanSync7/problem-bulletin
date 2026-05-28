"""v2.11-WP07 — single-item route ``response_model=`` adoption assertions.

These tests pin the OpenAPI shape of the single-item routes converted in
WP07. For each route we assert via OpenAPI introspection that:

  1. The handler declares a non-inline ``response_model`` (the 200 response
     schema resolves to a ``$ref`` into ``components.schemas`` rather than
     an inline anonymous object).
  2. The resolved schema name matches the expected pydantic model.

These are structural pins; they fail loudly if a future refactor strips
the ``response_model=`` annotation. They reuse the WP06 fixture pattern
in :mod:`tests.routes.test_page_t_adoption_wp06`.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from tests.helpers.app_factory import build_test_app


def _build_openapi_app() -> FastAPI:
    """Return the full production app for OpenAPI introspection.

    WP06 migration: previously hand-mounted a subset of routers on a bare
    ``FastAPI()``. Switched to ``build_test_app()`` — OpenAPI lookups are
    path-keyed so the broader app surface is harmless, and we now exercise
    the same router wiring production uses.
    """
    return build_test_app()


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    return _build_openapi_app().openapi()


# ---------------------------------------------------------------------------
# (method, path, expected response_model schema name)
# Schema name uses FastAPI's ``Model.__name__`` (no Page_T_ wrapping here).
# ---------------------------------------------------------------------------
WP07_ROUTES: list[tuple[str, str, str]] = [
    # edit_suggestions.py
    ("post", "/api/problems/{problem_id}/edit-suggestions", "EditSuggestionResponse"),
    ("post", "/api/edit-suggestions/{suggestion_id}/accept", "EditSuggestionActionResponse"),
    ("post", "/api/edit-suggestions/{suggestion_id}/reject", "EditSuggestionActionResponse"),
    # leaderboard.py
    ("get", "/api/leaderboard", "LeaderboardResponse"),
    # users.py (v1)
    ("patch", "/api/v1/users/me/handle", "UserHandleResponse"),
    ("patch", "/api/v1/admin/users/{user_id}/handle", "UserHandleResponse"),
    # problems.py
    ("post", "/api/problems/{problem_id}/claim", "ClaimToggleResponse"),
    # tickets.py — single-item handlers
    ("post", "/api/v1/tickets", "TicketRead"),
    ("get", "/api/v1/tickets/{id_or_key}", "TicketRead"),
    ("patch", "/api/v1/tickets/{id_or_key}", "TicketRead"),
    ("post", "/api/v1/tickets/{id_or_key}/transition", "TicketRead"),
    ("post", "/api/v1/tickets/{id_or_key}/assign", "TicketRead"),
    ("post", "/api/v1/tickets/{id_or_key}/claim", "TicketRead"),
    ("get", "/api/v1/tickets/{id_or_key}/subtree", "TicketSubtreeResponse"),
    ("get", "/api/v1/tickets/{id_or_key}/comments", "TicketCommentsList"),
    ("post", "/api/v1/tickets/{id_or_key}/comments", "TicketCommentRead"),
    ("post", "/api/v1/tickets/{id_or_key}/links", "TicketLinkRead"),
    ("get", "/api/v1/tickets/{id_or_key}/links", "TicketLinksGrouped"),
    ("post", "/api/v1/tickets/{id_or_key}/watchers", "TicketWatcherRead"),
    ("post", "/api/v1/tickets/{id_or_key}/attachments", "TicketAttachmentRead"),
]


def _success_response_schema(
    spec: dict[str, Any], method: str, path: str
) -> dict[str, Any]:
    """Return the application/json schema dict for the success response.

    Tries 200 first, falls back to 201 for ``status_code=HTTP_201_CREATED``
    endpoints. Returns ``{}`` if no JSON success response is declared.
    """
    op = spec["paths"][path][method]
    responses = op["responses"]
    for code in ("200", "201"):
        if code in responses:
            content = responses[code].get("content", {})
            if "application/json" in content:
                return content["application/json"]["schema"]
    return {}


@pytest.mark.parametrize(
    "method,path,expected_name",
    WP07_ROUTES,
    ids=[f"{m.upper()} {p} -> {n}" for m, p, n in WP07_ROUTES],
)
def test_route_declares_response_model_ref(
    openapi_spec: dict[str, Any], method: str, path: str, expected_name: str
) -> None:
    """G2: each WP07 single-item route declares a response_model.

    The OpenAPI 200/201 schema MUST resolve to a ``$ref`` into
    ``components.schemas.<ExpectedName>`` rather than be an inline shape.
    A missing ``$ref`` means the handler still returns ad-hoc dicts.
    """
    schema = _success_response_schema(openapi_spec, method, path)
    assert "$ref" in schema, (
        f"{method.upper()} {path}: success-response schema is inline "
        f"(no $ref). Expected response_model={expected_name}. "
        f"Got schema={schema!r}"
    )
    name = schema["$ref"].split("/")[-1]
    assert name == expected_name, (
        f"{method.upper()} {path}: response_model schema name "
        f"resolved to {name!r}; expected {expected_name!r}."
    )


def test_components_schemas_register_all_wp07_models(
    openapi_spec: dict[str, Any],
) -> None:
    """G7: every expected response_model is in components.schemas."""
    schemas = openapi_spec["components"]["schemas"]
    missing = []
    for _, _, expected_name in WP07_ROUTES:
        if expected_name not in schemas:
            missing.append(expected_name)
    assert not missing, (
        f"WP07 response_model schemas missing from OpenAPI components: {missing}"
    )
