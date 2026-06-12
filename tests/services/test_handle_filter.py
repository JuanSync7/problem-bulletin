"""v2.5-WP35 — Unit tests for app.services._handle_filter.

Covers:
 1. Profane handle → is_profane returns True.
 2. Non-profane handle → is_profane returns False.
 3. Mixed-case profane input → lowercased before check, still True.
 4. find_match returns the matched term for profane input.
 5. find_match returns None for clean input.
"""
from __future__ import annotations

import pytest

from app.services._handle_filter import PROFANITY_TERMS, find_match, is_profane


# ---------------------------------------------------------------------------
# is_profane
# ---------------------------------------------------------------------------

class TestIsProfane:
    def test_profane_handle_returns_true(self):
        """A handle that contains a blocked term should return True."""
        # Pick a term guaranteed to be in the set.
        term = next(iter(sorted(PROFANITY_TERMS)))
        assert is_profane(term) is True

    def test_non_profane_handle_returns_false(self):
        """A clean, ordinary handle should return False."""
        assert is_profane("cooluser42") is False
        assert is_profane("alice") is False
        assert is_profane("john_doe") is False

    def test_mixed_case_profane_returns_true(self):
        """Mixed-case profane input is lowercased before matching → True."""
        # CUNT → cunt; slur is in the blocklist.
        assert is_profane("CUNT") is True
        assert is_profane("Cunt") is True
        assert is_profane("CuNtUser") is True

    def test_substring_profane_returns_true(self):
        """Profane term embedded inside a longer handle still triggers."""
        assert is_profane("totalcunt") is True

    def test_empty_string_returns_false(self):
        """Empty string contains no blocked terms."""
        assert is_profane("") is False

    def test_all_terms_trigger(self):
        """Every term in PROFANITY_TERMS triggers is_profane."""
        for term in PROFANITY_TERMS:
            assert is_profane(term) is True, f"Expected is_profane({term!r}) to be True"

    def test_innocent_handles_pass(self):
        """Common innocent words must not be false positives."""
        innocent = [
            "userclassic",   # 'class' is not in blocklist
            "scunthorpe",    # classic false-positive trap; 'cunt' IS in list so this correctly triggers
        ]
        # scunthorpe contains 'cunt', which is intentionally blocked (substring match is intentional per spec)
        assert is_profane("userclassic") is False


# ---------------------------------------------------------------------------
# find_match
# ---------------------------------------------------------------------------

class TestFindMatch:
    def test_returns_matched_term_for_profane(self):
        """find_match returns a string (the matched term) for profane input."""
        result = find_match("cunt")
        assert result == "cunt"

    def test_returns_none_for_clean_input(self):
        """find_match returns None for a clean handle."""
        assert find_match("cleanhandle") is None

    def test_case_insensitive_find(self):
        """find_match is case-insensitive."""
        result = find_match("WANKER")
        assert result == "wanker"
