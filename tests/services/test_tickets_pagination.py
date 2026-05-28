"""v2.1-WP10 — Service-level cursor encode/decode and ordering tests."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.tickets import (
    InvalidCursorError,
    TicketService,
    _decode_cursor,
    _encode_cursor,
)


def test_cursor_encode_decode_roundtrip():
    ts = datetime(2026, 5, 16, 12, 34, 56, 789000, tzinfo=timezone.utc)
    tid = uuid4()
    s = _encode_cursor(ts, tid)
    assert isinstance(s, str) and "=" not in s  # base64 padding stripped
    ts2, id2 = _decode_cursor(s)
    assert ts2 == ts
    assert id2 == tid


def test_cursor_decode_malformed_raises():
    with pytest.raises(InvalidCursorError):
        _decode_cursor("not-a-valid-cursor")
    with pytest.raises(InvalidCursorError):
        _decode_cursor("!!!")


@pytest.mark.asyncio
async def test_service_list_deterministic_order(db, user_actor):
    """list() orders by (created_at DESC, id DESC) — keyset requires it."""
    svc = TicketService()
    # Pre-create the user row so reporter_id FK satisfies.
    from sqlalchemy import text

    await db.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :e, 'u')"),
        {"id": user_actor.id, "e": f"u-{user_actor.id}@x.test"},
    )
    await db.flush()
    titles = []
    for i in range(5):
        t = await svc.create(db, actor=user_actor, title=f"t{i}")
        titles.append(t.id)

    page = await svc.list_page(db, limit=10)
    rows = page["items"]
    # Newest first.
    timestamps = [r.created_at for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
