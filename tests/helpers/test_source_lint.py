"""v2.12-WP02 (B1) — self-tests for ``tests/helpers/source_lint.py``.

This module pins the public API of the shared source-shape lint helper
extracted from WP02, WP08, WP09, WP10, WP11, WP12, WP15. Every public
helper has a synthetic-bad self-test so a future refactor of the helper
cannot silently neuter the downstream lints that consume it.

Helpers under test:

* ``iter_source_files(root, *, allow_list=None, suffix=".py")``
* ``parse_module(path)``
* ``iter_string_literals(tree)``
* ``iter_calls(tree, *, dotted_name=None)``
* ``resolve_patch_target(target)``
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.helpers.source_lint import (
    PatchTargetResolution,
    iter_calls,
    iter_source_files,
    iter_string_literals,
    parse_module,
    resolve_patch_target,
)


# ---------------------------------------------------------------------------
# iter_source_files
# ---------------------------------------------------------------------------


def test_iter_source_files_yields_py_files_skipping_pycache(tmp_path: pathlib.Path):
    """Yields every ``*.py`` under root, skipping ``__pycache__`` and
    ``.venv`` directories regardless of nesting depth.
    """
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    (tmp_path / "sub" / "__pycache__").mkdir()
    (tmp_path / "sub" / "__pycache__" / "b.cpython-311.pyc").write_text("")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "bad.py").write_text("z = 3\n")

    found = sorted(p.name for p in iter_source_files(tmp_path))
    assert found == ["a.py", "b.py"], f"unexpected files: {found}"


def test_iter_source_files_respects_allow_list(tmp_path: pathlib.Path):
    """``allow_list`` (relative-path iterable) excludes matching files."""
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    (tmp_path / "c.py").write_text("z = 3\n")

    # Pass an iterable of relative paths (str). dict.keys() is the WP09
    # consumer shape — must accept that without conversion.
    allow = {"a.py": "irrelevant", "c.py": "irrelevant"}.keys()
    found = sorted(p.name for p in iter_source_files(tmp_path, allow_list=allow))
    assert found == ["b.py"], f"allow_list ignored; got {found}"


def test_iter_source_files_supports_arbitrary_suffix(tmp_path: pathlib.Path):
    """``suffix`` parameter overrides the default ``.py``."""
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "a.md").write_text("# doc\n")
    (tmp_path / "b.md").write_text("# doc\n")

    found = sorted(p.name for p in iter_source_files(tmp_path, suffix=".md"))
    assert found == ["a.md", "b.md"]


# ---------------------------------------------------------------------------
# parse_module
# ---------------------------------------------------------------------------


def test_parse_module_returns_ast_module(tmp_path: pathlib.Path):
    """``parse_module`` returns a real ``ast.Module`` for valid source."""
    path = tmp_path / "ok.py"
    path.write_text("x = 1\n")
    tree = parse_module(path)
    assert isinstance(tree, ast.Module)


def test_parse_module_returns_none_on_syntax_error(tmp_path: pathlib.Path):
    """SyntaxError is swallowed — returns ``None`` for best-effort scan."""
    path = tmp_path / "bad.py"
    path.write_text("def (oops\n")
    assert parse_module(path) is None


def test_parse_module_returns_none_on_unreadable(tmp_path: pathlib.Path):
    """Unreadable file → ``None`` rather than raising OSError."""
    path = tmp_path / "missing.py"
    # File never created.
    assert parse_module(path) is None


# ---------------------------------------------------------------------------
# iter_string_literals
# ---------------------------------------------------------------------------


def test_iter_string_literals_yields_plain_and_fstring_segments():
    """Every ``ast.Constant(str)`` is yielded, including literal segments
    nested inside an f-string (``ast.JoinedStr``).
    """
    src = (
        'a = "plain"\n'
        'b = f"prefix {x} suffix"\n'
        'c = 42\n'  # numeric — must NOT appear
        'd = b"bytes"\n'  # bytes — must NOT appear
    )
    tree = ast.parse(src)
    values = sorted(value for _, value in iter_string_literals(tree))
    # f-string literal segments are "prefix " and " suffix".
    assert "plain" in values
    assert "prefix " in values
    assert " suffix" in values
    assert "42" not in values
    assert "bytes" not in values


def test_iter_string_literals_synthetic_drift_check():
    """Self-test: a known-bad word planted in source is caught by an
    `iter_string_literals` walk — matches the WP15 lint usage pattern.
    """
    src = 'q = "SELECT id FROM problems p WHERE p.legacy_status = :s"\n'
    tree = ast.parse(src)
    hits = [v for _, v in iter_string_literals(tree) if "legacy_status" in v]
    assert hits, "synthetic bad string not detected"


# ---------------------------------------------------------------------------
# iter_calls
# ---------------------------------------------------------------------------


def test_iter_calls_yields_all_calls_when_unfiltered():
    src = "f()\ng.h()\ni.j.k()\n"
    tree = ast.parse(src)
    assert sum(1 for _ in iter_calls(tree)) == 3


def test_iter_calls_filters_by_bare_name():
    """``dotted_name='FastAPI'`` matches ``FastAPI(...)`` (Name)."""
    src = (
        "from fastapi import FastAPI\n"
        "a = FastAPI()\n"
        "b = OtherCls()\n"
    )
    tree = ast.parse(src)
    found = list(iter_calls(tree, dotted_name="FastAPI"))
    assert len(found) == 1
    assert isinstance(found[0].func, ast.Name)


def test_iter_calls_filters_by_attribute_tail():
    """``dotted_name='os.environ.setdefault'`` matches the attribute chain
    ``os.environ.setdefault(...)``.
    """
    src = (
        "import os\n"
        "os.environ.setdefault('K', 'V')\n"
        "os.environ['X'] = 'Y'\n"  # subscript, not setdefault
        "other.setdefault('K', 'V')\n"  # different chain
    )
    tree = ast.parse(src)
    found = list(iter_calls(tree, dotted_name="os.environ.setdefault"))
    assert len(found) == 1, f"expected 1 match, got {len(found)}"


def test_iter_calls_tail_attribute_filter():
    """``dotted_name='patch'`` matches both bare ``patch(...)`` and
    ``mock.patch(...)`` (attribute chain ending in ``patch``).
    """
    src = (
        "from unittest import mock\n"
        "from unittest.mock import patch\n"
        "patch('a.b')\n"
        "mock.patch('c.d')\n"
        "unittest.mock.patch('e.f')\n"
        "other_call()\n"
    )
    tree = ast.parse(src)
    found = list(iter_calls(tree, dotted_name="patch"))
    # Three patch-call sites; one non-match.
    assert len(found) == 3, f"got {len(found)}"


# ---------------------------------------------------------------------------
# resolve_patch_target
# ---------------------------------------------------------------------------


def test_resolve_patch_target_real_symbol():
    """A genuinely-resolvable dotted path (``os.path.join``) returns an
    ``ok`` resolution.
    """
    res = resolve_patch_target("os.path.join")
    assert isinstance(res, PatchTargetResolution)
    assert res.ok is True
    assert res.skip is False


def test_resolve_patch_target_attr_error():
    """A bad leaf attribute on a real module returns ``ok=False``,
    ``skip=False`` with an ``AttributeError`` reason — the load-bearing
    silent-no-op case (WP08-a).
    """
    res = resolve_patch_target("os.path.this_symbol_does_not_exist_xyz")
    assert res.ok is False
    assert res.skip is False
    assert "AttributeError" in res.detail


def test_resolve_patch_target_no_dot_passes():
    """Single-token (no dot) targets are out of scope — return ``ok=True``
    so the caller filters them out cheaply.
    """
    res = resolve_patch_target("just_a_name")
    assert res.ok is True


def test_resolve_patch_target_unimportable_prefix():
    """A wholly-unimportable prefix returns ``ok=False``, ``skip=False``
    with an ``ImportError`` reason.
    """
    res = resolve_patch_target("definitely_not_a_real_pkg_xyz123.submod.fn")
    assert res.ok is False
    assert res.skip is False
    assert "ImportError" in res.detail


def test_resolve_patch_target_synthetic_self_test():
    """Self-test (synthetic-bad + synthetic-good): scanner-resolver must
    flag a known-bad and pass a known-good.
    """
    bad = resolve_patch_target("os.path.totally_made_up_attr_name_xyz")
    assert bad.ok is False
    good = resolve_patch_target("os.path.join")
    assert good.ok is True
