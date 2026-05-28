"""WP62 — Unit tests for HMAC-signed cursor helpers in app.services._pagination.

Pure-Python tests; no DB. Cover round-trip per arm, tamper detection, arm
mismatch, malformed b64/json, and the secret-rotation property (different
secret → cursor cannot be decoded).
"""
from __future__ import annotations

import base64
import json

import pytest

from app.services._pagination import (
    InvalidCursorError,
    decode_signed_cursor,
    encode_signed_cursor,
)


SECRET = "test-secret-do-not-use-in-prod"
OTHER_SECRET = "different-secret"


# ---------------------------------------------------------------------------
# Round-trip per arm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arm,payload",
    [
        ("problems", {"rank": 0.42, "id": "00000000-0000-0000-0000-000000000001"}),
        (
            "tickets",
            {
                "rank": 0.31,
                "created_at": "2026-05-20T12:34:56+00:00",
                "id": "00000000-0000-0000-0000-000000000002",
            },
        ),
        (
            "components",
            {"rank": 0.5, "name": "auth", "id": "00000000-0000-0000-0000-000000000003"},
        ),
        (
            "labels",
            {"rank": 1.0, "name": "bug", "id": "00000000-0000-0000-0000-000000000004"},
        ),
        (
            "users",
            {"rank": 0.5, "handle": "alice", "id": "00000000-0000-0000-0000-000000000005"},
        ),
    ],
)
def test_roundtrip_per_arm(arm: str, payload: dict) -> None:
    cursor = encode_signed_cursor(arm, payload, secret=SECRET)
    assert isinstance(cursor, str)
    assert "=" not in cursor  # no base64 padding
    decoded = decode_signed_cursor(arm, cursor, secret=SECRET)
    assert decoded == payload


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_tampered_signature_rejected():
    payload = {"rank": 0.5, "id": "abc"}
    cursor = encode_signed_cursor("problems", payload, secret=SECRET)
    # Flip one byte after decoding so the sig field changes.
    pad = "=" * (-len(cursor) % 4)
    raw = json.loads(base64.urlsafe_b64decode(cursor + pad))
    raw["s"] = ("0" if raw["s"][0] != "0" else "1") + raw["s"][1:]
    tampered = (
        base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", tampered, secret=SECRET)


def test_tampered_payload_rejected():
    payload = {"rank": 0.5, "id": "abc"}
    cursor = encode_signed_cursor("problems", payload, secret=SECRET)
    pad = "=" * (-len(cursor) % 4)
    raw = json.loads(base64.urlsafe_b64decode(cursor + pad))
    raw["p"]["rank"] = 999.0
    tampered = (
        base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", tampered, secret=SECRET)


# ---------------------------------------------------------------------------
# Arm mismatch
# ---------------------------------------------------------------------------


def test_arm_mismatch_rejected():
    payload = {"rank": 0.5, "id": "abc"}
    cursor = encode_signed_cursor("problems", payload, secret=SECRET)
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("tickets", cursor, secret=SECRET)


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


def test_empty_cursor_rejected():
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", "", secret=SECRET)


def test_malformed_base64_rejected():
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", "!!!not-base64!!!", secret=SECRET)


def test_valid_base64_but_not_json_rejected():
    raw = base64.urlsafe_b64encode(b"not json").rstrip(b"=").decode()
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", raw, secret=SECRET)


def test_json_missing_fields_rejected():
    raw = (
        base64.urlsafe_b64encode(json.dumps({"a": "problems"}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", raw, secret=SECRET)


def test_json_array_envelope_rejected():
    raw = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", raw, secret=SECRET)


# ---------------------------------------------------------------------------
# Secret rotation
# ---------------------------------------------------------------------------


def test_different_secret_rejects_cursor():
    payload = {"rank": 0.5, "id": "abc"}
    cursor = encode_signed_cursor("problems", payload, secret=SECRET)
    with pytest.raises(InvalidCursorError):
        decode_signed_cursor("problems", cursor, secret=OTHER_SECRET)
