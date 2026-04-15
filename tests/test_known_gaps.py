"""
Known-gap tests — spec/implementation divergences and security edge cases.

These tests document behaviors that diverge from the spec (AION_BULLETIN_SPEC.md)
or represent security surface area that the primary test suite does not cover.
Each test references the relevant REQ and explains the gap.

Run:  pytest tests/test_known_gaps.py -v
"""
import re

import pytest


# ============================================================================
# GAP 1: javascript: href bypass vectors in HTML sanitizer (REQ-924)
#
# The sanitizer regex _JS_HREF_RE only matches quoted href attributes:
#   href="javascript:..." or href='javascript:...'
# Several bypass vectors exist that could allow XSS through <a> tags.
# ============================================================================

from app.middleware.security import sanitize_html


class TestJavascriptHrefBypass:
    """REQ-924: javascript: href sanitization bypass vectors."""

    def test_quoted_double_javascript_href_is_stripped(self):
        """Baseline: double-quoted javascript: href is correctly stripped."""
        html = '<a href="javascript:alert(1)">click</a>'
        result = sanitize_html(html)
        assert "javascript:" not in result.lower()
        assert ">click</a>" in result

    def test_quoted_single_javascript_href_is_stripped(self):
        """Baseline: single-quoted javascript: href is correctly stripped."""
        html = "<a href='javascript:alert(1)'>click</a>"
        result = sanitize_html(html)
        assert "javascript:" not in result.lower()

    @pytest.mark.xfail(
        reason="GAP: unquoted href=javascript: not caught by _JS_HREF_RE regex"
    )
    def test_unquoted_javascript_href_is_stripped(self):
        """Bypass: unquoted href attribute bypasses quoted-only regex."""
        html = "<a href=javascript:alert(1)>click</a>"
        result = sanitize_html(html)
        assert "javascript:" not in result.lower()

    @pytest.mark.xfail(
        reason="GAP: HTML entity encoding in javascript: bypasses literal match"
    )
    def test_entity_encoded_javascript_href_is_stripped(self):
        """Bypass: &#106;avascript: uses HTML entity to dodge literal match."""
        html = '<a href="&#106;avascript:alert(1)">click</a>'
        result = sanitize_html(html)
        assert "javascript:" not in result.lower()
        assert "&#106;" not in result  # entity-encoded 'j'

    @pytest.mark.xfail(
        reason="GAP: tab characters inside javascript: bypass literal match"
    )
    def test_tab_injected_javascript_href_is_stripped(self):
        """Bypass: java\\tscript: inserts whitespace to dodge literal match."""
        html = '<a href="java\tscript:alert(1)">click</a>'
        result = sanitize_html(html)
        assert "script:" not in result.lower()

    @pytest.mark.xfail(
        reason="GAP: newline characters inside javascript: bypass literal match"
    )
    def test_newline_injected_javascript_href_is_stripped(self):
        """Bypass: java\\nscript: inserts newline to dodge literal match."""
        html = '<a href="java\nscript:alert(1)">click</a>'
        result = sanitize_html(html)
        assert "script:" not in result.lower()

    @pytest.mark.xfail(
        reason="GAP: data: URI in href not caught — different vector, same risk"
    )
    def test_data_uri_href_is_stripped(self):
        """Bypass: data: URI can execute scripts in some browsers."""
        html = '<a href="data:text/html,<script>alert(1)</script>">click</a>'
        result = sanitize_html(html)
        assert "data:" not in result.lower()

    @pytest.mark.xfail(
        reason="GAP: vbscript: href not caught (IE legacy but still a vector)"
    )
    def test_vbscript_href_is_stripped(self):
        """Bypass: vbscript: URI scheme — legacy IE vector."""
        html = '<a href="vbscript:MsgBox(1)">click</a>'
        result = sanitize_html(html)
        assert "vbscript:" not in result.lower()


# ============================================================================
# GAP 2: WATCH_ROUTING spec divergence (REQ-312)
#
# Spec (REQ-312) defines:
#   solutions_only → new_solution, solution_accepted, solution_upvote_milestone
#   status_only    → problem_claimed, claim_expired, duplicate_flagged, solution_accepted
#
# Implementation defines:
#   solutions_only → solution_posted, solution_accepted  (missing upstar_received)
#   status_only    → status_changed                      (missing 3 specific types)
#
# Note: Spec event names don't match enum values exactly. The enum uses
# solution_posted (not new_solution), upstar_received (not solution_upvote_milestone),
# and has no claim_expired or duplicate_flagged — these are covered by status_changed.
# ============================================================================

from app.enums import NotificationType, WatchLevel
from app.services.notifications import WATCH_ROUTING


class TestWatchRoutingSpecDivergence:
    """REQ-312: WATCH_ROUTING matrix should match spec definitions."""

    def test_all_activity_receives_all_types(self):
        """Spec: all_activity receives all 8 types — implementation agrees."""
        assert WATCH_ROUTING[WatchLevel.all_activity] == set(NotificationType)

    def test_none_receives_nothing(self):
        """Spec: none receives nothing — implementation agrees."""
        assert WATCH_ROUTING[WatchLevel.none] == set()

    def test_solutions_only_includes_solution_posted(self):
        """Spec: solutions_only includes new_solution (mapped to solution_posted)."""
        assert NotificationType.solution_posted in WATCH_ROUTING[WatchLevel.solutions_only]

    def test_solutions_only_includes_solution_accepted(self):
        """Spec: solutions_only includes solution_accepted."""
        assert NotificationType.solution_accepted in WATCH_ROUTING[WatchLevel.solutions_only]

    @pytest.mark.xfail(
        reason="GAP: spec says solutions_only gets upvote milestones (upstar_received), impl omits it"
    )
    def test_solutions_only_includes_upstar_milestone(self):
        """REQ-312 spec: solutions_only should receive solution_upvote_milestone
        (mapped to upstar_received in the enum)."""
        assert NotificationType.upstar_received in WATCH_ROUTING[WatchLevel.solutions_only]

    @pytest.mark.xfail(
        reason="GAP: spec says status_only gets problem_claimed, impl only has status_changed"
    )
    def test_status_only_includes_problem_claimed(self):
        """REQ-312 spec: status_only should receive problem_claimed."""
        assert NotificationType.problem_claimed in WATCH_ROUTING[WatchLevel.status_only]

    @pytest.mark.xfail(
        reason="GAP: spec says status_only gets solution_accepted, impl only has status_changed"
    )
    def test_status_only_includes_solution_accepted(self):
        """REQ-312 spec: status_only should receive solution_accepted."""
        assert NotificationType.solution_accepted in WATCH_ROUTING[WatchLevel.status_only]

    def test_status_only_current_implementation(self):
        """Documents current implementation: status_only only gets status_changed."""
        assert WATCH_ROUTING[WatchLevel.status_only] == {NotificationType.status_changed}


# ============================================================================
# GAP 3: ALLOWED_TYPES spec divergence (REQ-402)
#
# Spec (REQ-402) says allowed types:
#   images: png, jpg, gif, svg, webp
#   documents: pdf, txt, md, log, csv
#   archives: zip, tar.gz
#
# Implementation has:
#   images: png, jpeg, webp, gif         (missing: svg)
#   documents: pdf, txt, log             (missing: md, csv)
#   archives: (none)                     (missing: zip, tar.gz)
# ============================================================================

from app.services.attachments import ALLOWED_TYPES


class TestAllowedTypesSpecDivergence:
    """REQ-402: ALLOWED_TYPES should match spec allowlist."""

    # --- Types that ARE in the implementation (baseline) ---

    def test_png_allowed(self):
        assert "image/png" in ALLOWED_TYPES

    def test_jpeg_allowed(self):
        assert "image/jpeg" in ALLOWED_TYPES

    def test_webp_allowed(self):
        assert "image/webp" in ALLOWED_TYPES

    def test_gif_allowed(self):
        assert "image/gif" in ALLOWED_TYPES

    def test_pdf_allowed(self):
        assert "application/pdf" in ALLOWED_TYPES

    def test_plain_text_allowed(self):
        assert "text/plain" in ALLOWED_TYPES

    # --- Types the spec requires but implementation is missing ---

    @pytest.mark.xfail(reason="GAP: spec REQ-402 includes svg, implementation omits it")
    def test_svg_allowed(self):
        """REQ-402: spec says svg is allowed."""
        assert "image/svg+xml" in ALLOWED_TYPES

    @pytest.mark.xfail(reason="GAP: spec REQ-402 includes md, implementation omits it")
    def test_markdown_allowed(self):
        """REQ-402: spec says md is allowed."""
        assert "text/markdown" in ALLOWED_TYPES

    @pytest.mark.xfail(reason="GAP: spec REQ-402 includes csv, implementation omits it")
    def test_csv_allowed(self):
        """REQ-402: spec says csv is allowed."""
        assert "text/csv" in ALLOWED_TYPES

    @pytest.mark.xfail(reason="GAP: spec REQ-402 includes zip, implementation omits it")
    def test_zip_allowed(self):
        """REQ-402: spec says zip archives are allowed."""
        assert "application/zip" in ALLOWED_TYPES

    @pytest.mark.xfail(reason="GAP: spec REQ-402 includes tar.gz, implementation omits it")
    def test_tar_gz_allowed(self):
        """REQ-402: spec says tar.gz archives are allowed."""
        assert "application/gzip" in ALLOWED_TYPES or "application/x-tar" in ALLOWED_TYPES


# ============================================================================
# GAP 4: /healthz vs /health compose mismatch (REQ-928)
#
# The health route is registered at /healthz (app/routes/health.py)
# but podman-compose.yml healthcheck hits /health.
# This means the container healthcheck always fails.
# FIX: podman-compose.yml line 25 should use /healthz not /health.
# ============================================================================

# This gap is a configuration bug, not a code test.
# See the fix applied to podman-compose.yml.


# ============================================================================
# GAP 5: Concurrent SELECT FOR UPDATE (REQ-250, REQ-252, REQ-254, REQ-256)
#
# app/services/voting.py uses .with_for_update() to serialize concurrent
# votes on the same problem/solution. This prevents race conditions but
# can only be tested with a real PostgreSQL instance under concurrent load.
#
# NO TEST WRITTEN — requires real PostgreSQL + asyncio.gather with multiple
# sessions to verify row locking behavior.
# ============================================================================


# ============================================================================
# GAP 6: Frontend tests (REQ-926)
#
# Frontend is a React 18 SPA (frontend/src/). Testing requires a jsdom/browser
# environment with vitest or jest. No frontend test infrastructure exists yet.
#
# NO TEST WRITTEN — requires vitest + @testing-library/react setup.
# ============================================================================
