"""WP10 — Stable-total cursor field roundtrip.

The HMAC-signed cursor payload may carry an optional snapshot ``t`` (total)
field. These tests cover:

1. Encoding a payload that includes ``t`` and decoding it back returns the
   same value verbatim.
2. A legacy cursor (no ``t``) still decodes successfully — the helper does
   not require ``t`` to be present (backward compat).
"""
from __future__ import annotations

from app.services._pagination import decode_signed_cursor, encode_signed_cursor


_SECRET = "wp10-test-secret"


def test_cursor_roundtrip_carries_total_snapshot():
    payload = {
        "rank": 0.5,
        "id": "00000000-0000-0000-0000-000000000001",
        "t": 117,
    }
    cursor = encode_signed_cursor("problems", payload, secret=_SECRET)
    decoded = decode_signed_cursor("problems", cursor, secret=_SECRET)
    assert decoded == payload
    assert decoded["t"] == 117


def test_legacy_cursor_without_total_still_decodes():
    # Cursor minted before WP10 — no "t" field present.
    legacy_payload = {
        "rank": 0.1,
        "id": "00000000-0000-0000-0000-000000000002",
    }
    cursor = encode_signed_cursor("problems", legacy_payload, secret=_SECRET)
    decoded = decode_signed_cursor("problems", cursor, secret=_SECRET)
    assert "t" not in decoded
    assert decoded == legacy_payload
