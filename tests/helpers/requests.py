"""v2.11-WP11 (C5) — Mock ``Request`` factory using ``starlette.datastructures.Headers``.

Background
----------
v2.10-WP03 surfaced a bug class: tests that stub ``request.headers`` with
a plain ``dict`` silently mask case-sensitivity bugs. Production receives
``starlette.datastructures.Headers`` (case-insensitive), so a handler
calling ``request.headers.get("authorization")`` works fine when the
client sends ``Authorization``. A mock with ``request.headers = {"Authorization":
"Bearer ..."}`` is plain-dict, case-SENSITIVE, and would NOT match
``.get("authorization")`` — yet if a test happens to send the same casing
the handler is reading, the assertion still passes for the wrong reason.

This helper builds a ``MagicMock`` whose ``.headers`` is the real
``starlette.datastructures.Headers`` type. Tests get production-faithful
case behaviour without booting a full ASGI app.

Usage
-----
.. code-block:: python

    from tests.helpers.requests import build_mock_request

    request = build_mock_request(headers={"Authorization": "Bearer xyz"})
    # request.headers.get("authorization") -> "Bearer xyz" (case-insensitive)

Companion lint at ``tests/test_mock_headers_lint_wp11.py`` keeps new
tests from regressing back to plain-dict ``.headers``.
"""
from __future__ import annotations

from typing import Any, Mapping
from unittest.mock import MagicMock

from starlette.datastructures import Headers


def build_mock_request(
    *,
    headers: Mapping[str, str] | None = None,
    cookies: Mapping[str, str] | None = None,
    **extra: Any,
) -> MagicMock:
    """Return a ``MagicMock`` Request with a real ``Headers`` instance.

    Parameters
    ----------
    headers:
        Optional mapping wrapped in ``starlette.datastructures.Headers``.
        Case-insensitive lookups (``"Authorization"`` vs ``"authorization"``)
        behave the same as in production.
    cookies:
        Optional mapping assigned to ``request.cookies`` as a plain dict
        (Starlette's runtime cookie object is already dict-shaped).
    **extra:
        Additional attributes set on the mock via ``setattr``.

    Returns
    -------
    MagicMock
        With ``.headers`` = ``Headers(headers or {})`` and ``.cookies`` =
        ``cookies or {}``.
    """
    request = MagicMock()
    request.headers = Headers(dict(headers) if headers else {})
    request.cookies = dict(cookies) if cookies else {}
    for k, v in extra.items():
        setattr(request, k, v)
    return request
