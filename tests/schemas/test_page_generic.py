"""v2.1-WP10 — Generic Page[T] envelope serialization."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import Page


class _Foo(BaseModel):
    x: int
    name: str


def test_page_of_foo_roundtrip():
    p: Page[_Foo] = Page[_Foo](
        items=[_Foo(x=1, name="a"), _Foo(x=2, name="b")],
        next_cursor="abc",
        total=2,
    )
    dumped = p.model_dump()
    assert dumped == {
        "items": [{"x": 1, "name": "a"}, {"x": 2, "name": "b"}],
        "next_cursor": "abc",
        "total": 2,
    }
    # Round-trip back through validation.
    p2 = Page[_Foo].model_validate(dumped)
    assert p2.items[0].x == 1
    assert p2.next_cursor == "abc"


def test_page_total_optional():
    p = Page[_Foo](items=[], next_cursor=None)
    assert p.total is None
    assert p.next_cursor is None
    assert p.items == []


def test_page_total_null_serializes():
    p = Page[_Foo](items=[], next_cursor=None, total=None)
    assert p.model_dump()["total"] is None
