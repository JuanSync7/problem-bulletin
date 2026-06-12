"""Unit tests for app.services._pagination — encode_cursor / decode_cursor.

Spec: v2.3-WP20. These tests exercise the shared helpers directly and do NOT
require a database connection — all assertions are pure-Python.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.services._pagination import decode_cursor, encode_cursor


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_roundtrip_naive_datetime():
    """encode then decode returns the original (datetime, UUID) tuple."""
    ts = datetime(2026, 5, 16, 12, 34, 56, 789000)
    uid = uuid4()
    cursor = encode_cursor(ts, uid)
    result = decode_cursor(cursor)
    assert result is not None
    got_ts, got_id = result
    assert got_ts == ts
    assert got_id == uid


def test_roundtrip_aware_datetime():
    """Timezone-aware datetime (UTC) survives the encode/decode round-trip."""
    ts = datetime.now(timezone.utc).replace(microsecond=123456)
    uid = uuid4()
    cursor = encode_cursor(ts, uid)
    result = decode_cursor(cursor)
    assert result is not None
    got_ts, got_id = result
    assert got_ts == ts
    assert got_id == uid


def test_encode_produces_no_padding():
    """Encoded cursor must not contain '=' padding characters."""
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    uid = UUID("12345678-1234-5678-1234-567812345678")
    cursor = encode_cursor(ts, uid)
    assert "=" not in cursor


# ---------------------------------------------------------------------------
# decode_cursor — None / empty / garbage inputs
# ---------------------------------------------------------------------------


def test_decode_none_returns_none():
    """decode_cursor(None) returns None."""
    assert decode_cursor(None) is None


def test_decode_empty_string_returns_none():
    """decode_cursor("") returns None."""
    assert decode_cursor("") is None


def test_decode_invalid_base64_returns_none():
    """decode_cursor with non-base64 text returns None."""
    assert decode_cursor("not-valid-base64!!!") is None


def test_decode_valid_base64_but_not_json_returns_none():
    """decode_cursor with valid base64 that decodes to non-JSON returns None."""
    raw = base64.urlsafe_b64encode(b"this is not json").rstrip(b"=").decode()
    assert decode_cursor(raw) is None


def test_decode_missing_t_field_returns_none():
    """decode_cursor of a payload missing the 't' key returns None."""
    uid = str(uuid4())
    payload = json.dumps({"i": uid}).encode()
    cursor = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    assert decode_cursor(cursor) is None


def test_decode_missing_i_field_returns_none():
    """decode_cursor of a payload missing the 'i' key returns None."""
    ts = datetime.now(timezone.utc).isoformat()
    payload = json.dumps({"t": ts}).encode()
    cursor = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    assert decode_cursor(cursor) is None


def test_decode_bad_timestamp_returns_none():
    """decode_cursor with a malformed ISO timestamp returns None."""
    payload = json.dumps({"t": "not-a-date", "i": str(uuid4())}).encode()
    cursor = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    assert decode_cursor(cursor) is None


def test_decode_bad_uuid_returns_none():
    """decode_cursor with a malformed UUID returns None."""
    payload = json.dumps(
        {"t": datetime.now(timezone.utc).isoformat(), "i": "not-a-uuid"}
    ).encode()
    cursor = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    assert decode_cursor(cursor) is None
