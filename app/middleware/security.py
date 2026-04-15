"""
Security middleware and utilities.

Covers:
  REQ-908  Security response headers
  REQ-918  Content-Security-Policy
  REQ-924  HTML sanitization (XSS prevention)
"""

from __future__ import annotations

import re
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# REQ-918  Content-Security-Policy value
# ---------------------------------------------------------------------------
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)

# ---------------------------------------------------------------------------
# REQ-908 / REQ-918  Security-headers middleware
# ---------------------------------------------------------------------------

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "1; mode=block",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": _CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        response = await call_next(request)
        # Relax headers for attachment downloads so PDFs render in-browser
        is_attachment_download = "/attachments/" in request.url.path and request.url.path.endswith("/download")
        for header, value in _SECURITY_HEADERS.items():
            if is_attachment_download and header in ("X-Frame-Options", "Content-Security-Policy"):
                continue
            response.headers.setdefault(header, value)
        return response


# ---------------------------------------------------------------------------
# REQ-924  HTML sanitization
# ---------------------------------------------------------------------------

# Tags that are allowed to remain in sanitized output.
_SAFE_TAGS: set[str] = {
    "p", "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li", "a", "br",
    "h1", "h2", "h3", "h4", "h5", "h6",
}

# Matches any HTML tag (opening, closing, or self-closing).
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)(/?)>", re.IGNORECASE | re.DOTALL)

# Matches on* event-handler attributes (onclick, onerror, …).
_EVENT_HANDLER_RE = re.compile(
    r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",
    re.IGNORECASE,
)

# Matches href attributes whose value starts with javascript:.
_JS_HREF_RE = re.compile(
    r"""\s+href\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')""",
    re.IGNORECASE,
)


def _clean_attrs(attrs: str) -> str:
    """Remove dangerous attributes from an attribute string."""
    attrs = _EVENT_HANDLER_RE.sub("", attrs)
    attrs = _JS_HREF_RE.sub("", attrs)
    return attrs


def _replace_tag(match: re.Match) -> str:  # type: ignore[type-arg]
    slash_open = match.group(1)   # "/" for closing tags, "" otherwise
    tag_name = match.group(2).lower()
    attrs = match.group(3)
    slash_close = match.group(4)  # "/" for self-closing tags

    if tag_name not in _SAFE_TAGS:
        return ""

    attrs = _clean_attrs(attrs)
    return f"<{slash_open}{tag_name}{attrs}{slash_close}>"


def sanitize_html(text: str) -> str:
    """Sanitize *text* by stripping dangerous HTML while keeping safe tags.

    Safe tags: ``p, strong, em, code, pre, blockquote, ul, ol, li, a, br,
    h1-h6``.

    All event-handler attributes (``onclick``, ``onerror``, …) and
    ``javascript:`` hrefs are removed.
    """
    # First escape any raw HTML entities that aren't part of tags so that
    # bare text cannot inject scripts.  We do this by escaping the whole
    # string and then *un-escaping* the angle brackets so the tag regex
    # can still match legitimate tags.
    #
    # However, if the caller passes pre-formed HTML (which is the expected
    # use-case) we should NOT double-escape existing entities.  Instead we
    # operate directly on the raw text and rely on the tag regex to strip
    # anything dangerous.

    # Strip <script>, <style>, <iframe>, etc. entirely (content included).
    text = re.sub(
        r"<(script|style|iframe|object|embed|applet|form|input|textarea|select|button)"
        r"[\s>].*?</\1>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Replace each tag — keep safe ones (with cleaned attrs), drop the rest.
    text = _TAG_RE.sub(_replace_tag, text)
    return text
