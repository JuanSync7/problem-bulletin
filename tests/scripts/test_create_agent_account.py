"""Smoke tests for scripts/create_agent_account.py (Task R5)."""
from __future__ import annotations

import pytest

from scripts.create_agent_account import _parse_argv


def test_parse_argv_minimal():
    ns = _parse_argv(["--name", "bot1"])
    assert ns.name == "bot1"
    assert ns.scope == []
    assert ns.description is None


def test_parse_argv_with_scopes_and_description():
    ns = _parse_argv([
        "--name", "bot2",
        "--scope", "tickets:read",
        "--scope", "tickets:write",
        "--description", "primary",
    ])
    assert ns.name == "bot2"
    assert ns.scope == ["tickets:read", "tickets:write"]
    assert ns.description == "primary"


def test_parse_argv_missing_name_raises():
    with pytest.raises(SystemExit):
        _parse_argv([])
