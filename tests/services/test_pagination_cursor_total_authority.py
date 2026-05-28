"""v2.11-WP14 (F1) — total_authority cursor-payload field roundtrip.

The HMAC-signed cursor payload may carry an optional ``"a"`` (total_authority)
field alongside the ``"t"`` (total) snapshot. These tests cover:

1. Encoding a payload that includes ``a`` and decoding it back returns the
   same value verbatim (HMAC signature verifies on the new shape).
2. A pre-WP14 cursor (no ``a`` field) still decodes successfully — the field
   is additive and absence is treated by callers as the ``"snapshot"``
   default.
"""
from __future__ import annotations

from app.services._pagination import decode_signed_cursor, encode_signed_cursor


_SECRET = "wp14-test-secret"


def test_cursor_roundtrip_carries_total_authority():
    payload = {
        "rank": 0.5,
        "id": "00000000-0000-0000-0000-000000000001",
        "t": 117,
        "a": "snapshot",
    }
    cursor = encode_signed_cursor("problems", payload, secret=_SECRET)
    decoded = decode_signed_cursor("problems", cursor, secret=_SECRET)
    assert decoded == payload
    assert decoded["a"] == "snapshot"


def test_cursor_roundtrip_authority_live_variant():
    payload = {
        "rank": 0.1,
        "id": "00000000-0000-0000-0000-000000000002",
        "t": 42,
        "a": "live",
    }
    cursor = encode_signed_cursor("problems", payload, secret=_SECRET)
    decoded = decode_signed_cursor("problems", cursor, secret=_SECRET)
    assert decoded["a"] == "live"


def test_legacy_cursor_without_authority_still_decodes():
    """A pre-WP14 cursor lacking the ``a`` key must still verify and decode.

    Callers (``search_multi._authority_from_cursor``) treat absence as
    ``"snapshot"``.
    """
    legacy_payload = {
        "rank": 0.1,
        "id": "00000000-0000-0000-0000-000000000003",
        "t": 7,
    }
    cursor = encode_signed_cursor("problems", legacy_payload, secret=_SECRET)
    decoded = decode_signed_cursor("problems", cursor, secret=_SECRET)
    assert "a" not in decoded
    assert decoded == legacy_payload
