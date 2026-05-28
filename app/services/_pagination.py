"""Shared cursor encode/decode helpers for ticket-domain pagination.

Wire format: base64url(JSON) where the JSON payload is::

    {"t": "<iso8601 datetime>", "i": "<uuid>"}

The base64 uses ``urlsafe_b64encode`` with trailing ``=`` padding stripped so
the cursor is safe to pass as a URL query parameter without further encoding.

Consumers:
- ``app.services.tickets`` — ``GET /api/v1/tickets`` listing and per-ticket
  activity feed (``list`` + ``list_activity`` methods).
- ``app.services.ticket_notifications`` — ``GET /api/v1/notifications`` inbox
  listing (``list_for_recipient`` method).

WP62: adds HMAC-signed cursor helpers for the multi-entity search arms.
"""
from __future__ import annotations

import base64 as _b64
import binascii
import hashlib as _hashlib
import hmac as _hmac
import json as _json
from datetime import datetime
from typing import Any
from uuid import UUID


def encode_cursor(created_at: datetime, id_: UUID) -> str:
    """Encode ``(created_at, id_)`` as an opaque base64url(JSON) cursor string.

    The resulting string has no ``=`` padding and is safe for use as a URL
    query parameter.  Do not change this format — existing client cursors
    must remain valid across deployments.
    """
    payload = {"t": created_at.isoformat(), "i": str(id_)}
    raw = _json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _b64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(c: str | None) -> tuple[datetime, UUID] | None:
    """Decode an opaque cursor produced by :func:`encode_cursor`.

    Returns ``None`` on missing or invalid input so callers can treat a bad
    cursor the same as an absent one (or raise their own domain error).
    Narrowly catches ``binascii.Error``, ``ValueError``, ``KeyError``, and
    ``json.JSONDecodeError``; truly unexpected errors propagate.

    Args:
        c: The cursor string, or ``None`` / empty string.

    Returns:
        A ``(datetime, UUID)`` pair, or ``None`` if the cursor is absent or
        cannot be decoded.
    """
    if not c:
        return None
    try:
        pad = "=" * (-len(c) % 4)
        raw = _b64.urlsafe_b64decode(c + pad)
    except binascii.Error:
        return None
    try:
        obj = _json.loads(raw.decode("utf-8"))
        ts = datetime.fromisoformat(obj["t"])
        uid = UUID(obj["i"])
        return ts, uid
    except (ValueError, KeyError, _json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# WP62 — HMAC-signed cursors for /api/search/v2
# ---------------------------------------------------------------------------


class InvalidCursorError(Exception):
    """Raised when a signed cursor is malformed, tampered, or arm-mismatched.

    Route layer catches this and maps to HTTP 400. Do NOT include the cursor
    contents in the error message — they may contain attacker-controlled data.
    """


def _canonical_json(obj: dict[str, Any]) -> bytes:
    """Canonical JSON encoding for HMAC: sorted keys, compact separators."""
    return _json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_sig(secret: str, arm: str, payload: dict[str, Any]) -> str:
    """Compute hex HMAC-SHA256 over canonical_json({"a": arm, "p": payload})."""
    msg = _canonical_json({"a": arm, "p": payload})
    return _hmac.new(secret.encode("utf-8"), msg, _hashlib.sha256).hexdigest()


def encode_signed_cursor(arm: str, payload: dict[str, Any], *, secret: str) -> str:
    """Encode an HMAC-signed opaque cursor.

    The cursor is base64url(JSON) of ``{"a": arm, "p": payload, "s": sig}``
    where ``sig`` is the hex HMAC-SHA256 over ``{"a": arm, "p": payload}``
    using ``secret``. Verification with :func:`decode_signed_cursor` uses
    :func:`hmac.compare_digest` so timing attacks on the signature are not
    feasible.

    ``payload`` should be JSON-serialisable. Datetimes, UUIDs etc. must be
    pre-stringified by the caller; this helper does not convert types.

    Args:
        arm: Logical scope of the cursor (e.g. ``"problems"``, ``"tickets"``).
        payload: Cursor payload (arm-specific seek tuple).
        secret: HMAC secret. Use the same secret as the JWT layer so cursors
            share rotation lifecycle.

    Returns:
        Base64url cursor string, no ``=`` padding.
    """
    sig = _hmac_sig(secret, arm, payload)
    envelope = {"a": arm, "p": payload, "s": sig}
    raw = _json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_signed_cursor(arm: str, cursor: str, *, secret: str) -> dict[str, Any]:
    """Decode an HMAC-signed cursor and return its payload.

    Raises :class:`InvalidCursorError` if:
    - The cursor is empty / not valid base64url.
    - The decoded JSON is missing ``a``, ``p``, or ``s`` keys.
    - The ``a`` field does not match the expected ``arm``.
    - The signature does not match.

    The expected-arm check is what binds a cursor to a specific entity — a
    cursor minted for ``problems`` cannot be replayed against ``tickets``
    even though both share the same secret.

    Args:
        arm: Expected arm. The cursor's ``a`` field must equal this.
        cursor: The base64url cursor string.
        secret: HMAC secret (same as :func:`encode_signed_cursor`).

    Returns:
        The original ``payload`` dict that was signed.
    """
    if not cursor:
        raise InvalidCursorError("empty cursor")
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = _b64.urlsafe_b64decode(cursor + pad)
    except binascii.Error as exc:
        raise InvalidCursorError("malformed base64") from exc
    try:
        envelope = _json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
        raise InvalidCursorError("malformed json") from exc
    if not isinstance(envelope, dict):
        raise InvalidCursorError("malformed envelope")
    try:
        got_arm = envelope["a"]
        payload = envelope["p"]
        got_sig = envelope["s"]
    except KeyError as exc:
        raise InvalidCursorError("missing field") from exc
    if not isinstance(got_arm, str) or not isinstance(payload, dict) or not isinstance(got_sig, str):
        raise InvalidCursorError("malformed field types")
    if got_arm != arm:
        raise InvalidCursorError("arm mismatch")
    expected_sig = _hmac_sig(secret, arm, payload)
    if not _hmac.compare_digest(expected_sig, got_sig):
        raise InvalidCursorError("bad signature")
    return payload
