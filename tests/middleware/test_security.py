"""
Tests for app.middleware.security.

Coverage:
- SecurityHeadersMiddleware: adds all 6 security headers to responses
- SecurityHeadersMiddleware: setdefault doesn't overwrite explicit headers
- sanitize_html: Pass 1 removes script, style, iframe elements entirely
- sanitize_html: Pass 2 strips non-safe tags, preserves allowed tags
- sanitize_html: strips on* event handler attributes
- sanitize_html: strips javascript: hrefs
- sanitize_html: preserves href on <a> tags (non-javascript)
- sanitize_html: empty input returns empty output

# GAP: javascript: href values are NOT stripped from href (only from on* handlers) — known XSS surface
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from app.middleware.security import SecurityHeadersMiddleware, sanitize_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_SECURITY_HEADERS = [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "X-XSS-Protection",
    "Permissions-Policy",
    "Content-Security-Policy",
]

CSP_REQUIRED_DIRECTIVES = [
    "default-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "frame-ancestors",
    "form-action",
    "base-uri",
]

SAFE_TAGS = [
    "p", "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li", "a", "br",
    "h1", "h2", "h3", "h4", "h5", "h6",
]

PASS1_REMOVED_TAGS = [
    "script", "style", "iframe", "object", "embed", "applet",
    "form", "input", "textarea", "select", "button",
]


def _make_app_with_middleware(handler=None):
    """Build a minimal FastAPI app wrapped with SecurityHeadersMiddleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    if handler is None:
        @app.get("/test")
        async def _default():
            return {"ok": True}
    else:
        app.add_api_route("/test", handler, methods=["GET"])

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware — header injection
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    def test_all_six_security_headers_present_on_200(self):
        client = _make_app_with_middleware()
        response = client.get("/test")

        for header in EXPECTED_SECURITY_HEADERS:
            assert header in response.headers, f"Missing header: {header}"

    def test_x_content_type_options_value(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_value(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_referrer_policy_value(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_xxss_protection_value(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        assert response.headers["X-XSS-Protection"] == "1; mode=block"

    def test_permissions_policy_value(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        policy = response.headers["Permissions-Policy"]
        assert "camera=()" in policy
        assert "microphone=()" in policy
        assert "geolocation=()" in policy

    def test_csp_header_present(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        assert "Content-Security-Policy" in response.headers

    def test_csp_contains_all_eight_directives(self):
        client = _make_app_with_middleware()
        response = client.get("/test")
        csp = response.headers["Content-Security-Policy"]
        for directive in CSP_REQUIRED_DIRECTIVES:
            assert directive in csp, f"CSP missing directive: {directive}"

    def test_setdefault_does_not_overwrite_explicit_x_frame_options(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/custom-header")
        async def _with_header():
            return Response(
                content="ok",
                headers={"X-Frame-Options": "SAMEORIGIN"},
            )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/custom-header")

        # Handler's value must be retained
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        # All other five headers still set by middleware
        for header in EXPECTED_SECURITY_HEADERS:
            if header != "X-Frame-Options":
                assert header in response.headers, f"Missing middleware header: {header}"

    def test_headers_present_on_404_response(self):
        client = _make_app_with_middleware()
        response = client.get("/nonexistent-route")

        assert response.status_code == 404
        for header in EXPECTED_SECURITY_HEADERS:
            assert header in response.headers, f"Missing header on 404: {header}"


# ---------------------------------------------------------------------------
# sanitize_html — Pass 1: dangerous element removal
# ---------------------------------------------------------------------------


class TestSanitizeHtmlPass1:
    def test_removes_script_element_entirely(self):
        result = sanitize_html("<p>before</p><script>alert(1)</script><p>after</p>")
        assert "<script" not in result
        assert "alert" not in result
        assert "<p>before</p>" in result
        assert "<p>after</p>" in result

    def test_removes_style_element_entirely(self):
        result = sanitize_html("<style>body{display:none}</style><p>text</p>")
        assert "<style" not in result
        assert "display:none" not in result
        assert "<p>text</p>" in result

    def test_removes_iframe_entirely(self):
        result = sanitize_html("<iframe src='evil.com'></iframe><p>safe</p>")
        assert "<iframe" not in result
        assert "evil.com" not in result
        assert "<p>safe</p>" in result

    def test_removes_form_and_input(self):
        result = sanitize_html('<form action="/steal"><input type="hidden" value="x"/></form>text')
        assert "<form" not in result
        assert "<input" not in result
        assert "text" in result

    def test_removes_object_element(self):
        result = sanitize_html("<object data='x.swf'></object><p>safe</p>")
        assert "<object" not in result

    def test_removes_embed_element(self):
        result = sanitize_html("<embed src='x.swf'/><p>safe</p>")
        assert "<embed" not in result

    def test_removes_applet_element(self):
        result = sanitize_html("<applet code='x.class'></applet><p>safe</p>")
        assert "<applet" not in result

    def test_removes_textarea_and_button(self):
        result = sanitize_html("<textarea>value</textarea><button>click</button>text")
        assert "<textarea" not in result
        assert "<button" not in result
        assert "text" in result

    def test_nested_dangerous_tags_do_not_raise(self):
        # Should not raise; dangerous content removed
        result = sanitize_html("<div><script><p>text</p></script></div>")
        assert "<script" not in result

    @pytest.mark.parametrize("tag", PASS1_REMOVED_TAGS)
    def test_each_pass1_tag_is_removed(self, tag):
        html = f"<{tag}>content</{tag}><p>safe</p>"
        result = sanitize_html(html)
        assert f"<{tag}" not in result.lower()


# ---------------------------------------------------------------------------
# sanitize_html — Pass 2: attribute stripping and non-safe tag removal
# ---------------------------------------------------------------------------


class TestSanitizeHtmlPass2:
    def test_strips_onclick_event_handler(self):
        result = sanitize_html('<a href="/ok" onclick="steal()">link</a>')
        assert "onclick" not in result
        assert "steal()" not in result
        assert "link" in result

    def test_strips_javascript_href(self):
        result = sanitize_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in result
        assert "click" in result

    def test_preserves_safe_href_on_anchor(self):
        result = sanitize_html('<a href="https://example.com">link</a>')
        assert 'href="https://example.com"' in result or "href='https://example.com'" in result
        assert "link" in result

    def test_preserves_relative_href_on_anchor(self):
        result = sanitize_html('<a href="/about">About</a>')
        assert "/about" in result

    def test_strips_div_preserves_content(self):
        result = sanitize_html("<div><p>text</p></div>")
        assert "<div" not in result
        assert "<p>text</p>" in result

    def test_strips_mixed_case_event_handlers(self):
        """_EVENT_HANDLER_RE must be case-insensitive."""
        result = sanitize_html('<p onClick="bad()" ONMOUSEOVER="worse()">text</p>')
        assert "onClick" not in result
        assert "ONMOUSEOVER" not in result
        assert "text" in result

    def test_all_safe_tags_preserved(self):
        parts = []
        for tag in SAFE_TAGS:
            if tag == "br":
                parts.append("<br/>")
            elif tag == "a":
                parts.append('<a href="/x">x</a>')
            else:
                parts.append(f"<{tag}>content</{tag}>")
        html = "".join(parts)
        result = sanitize_html(html)
        for tag in SAFE_TAGS:
            assert f"<{tag}" in result, f"Safe tag <{tag}> was stripped unexpectedly"

    def test_safe_tags_input_unchanged(self):
        html = "<p>Hello <strong>world</strong></p>"
        result = sanitize_html(html)
        assert result == html

    def test_strips_all_on_star_attributes(self):
        result = sanitize_html('<p onload="x()" onfocus="y()">text</p>')
        assert "onload" not in result
        assert "onfocus" not in result


# ---------------------------------------------------------------------------
# sanitize_html — Edge cases
# ---------------------------------------------------------------------------


class TestSanitizeHtmlEdgeCases:
    def test_empty_string_returns_empty_string(self):
        assert sanitize_html("") == ""

    def test_plain_text_returned_unchanged(self):
        assert sanitize_html("plain text") == "plain text"

    def test_deeply_nested_safe_tags_do_not_raise(self):
        html = "<p>" + "<em>" * 20 + "deep" + "</em>" * 20 + "</p>"
        result = sanitize_html(html)
        assert "deep" in result
        assert result  # non-empty

    def test_no_html_input_does_not_raise(self):
        result = sanitize_html("Hello, world! No tags here.")
        assert result == "Hello, world! No tags here."

    # GAP: javascript: href values are NOT stripped from href (only from on* handlers) — known XSS surface
    # The current implementation may not strip javascript: from href; document here as a known gap.
    # def test_gap_javascript_href_xss_surface(self):
    #     """Known gap: javascript: href may survive Pass 2 on some implementations."""
    #     result = sanitize_html('<a href="javascript:void(0)">x</a>')
    #     # This test documents that javascript: removal from href is NOT guaranteed.
    #     pass
