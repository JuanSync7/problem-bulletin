"""v2.11-WP08 (C1) — ``unittest.mock.patch("dotted.path", ...)`` resolution lint.

Background
----------
``unittest.mock.patch("app.X.symbol", ...)`` resolves the dotted target
**at runtime** when the test executes — collection-time inspection
gives no warning. If ``symbol`` was renamed, moved, or deleted, the
patch silently becomes a no-op: the **real** production object runs
unmocked, and the test still "passes" because the surrounding
assertions don't notice. v2.10-WP03 / WP05 / WP07 each shipped a fix
for a real instance of this class of bug.

Scope
-----
- Scans ``tests/**/*.py``.
- Targets calls to ``patch(...)`` and ``mock.patch(...)`` /
  ``unittest.mock.patch(...)`` where the first positional argument is a
  string literal containing at least one ``.`` (i.e. a dotted path).
- Skips ``patch.dict(...)`` — entirely different mechanism (env vars /
  dict mutation), the first arg isn't a dotted-symbol path.
- Skips first-args with no ``.`` separator — that's not a module.symbol
  reference; can't import-resolve it meaningfully.
- Skips f-string first args — dynamic target, can't statically resolve.
- For each candidate, imports the prefix (``a.b.c`` → ``import a.b``,
  ``getattr(a.b, "c")``). If import raises (missing optional dep,
  import-time side effect crash), the file is recorded as a SKIP — not
  a failure — because we can't tell whether the target is bad or the
  import environment is.

Lessons-pin
-----------
This is the regression-lint surface for the v2.11-WP08 (C1) sweep.
``mock.patch`` is famously fragile: a typo'd or renamed symbol gives
you a *passing* test that doesn't actually patch anything. This lint
turns that silent failure into a loud one at test-collection time.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.helpers.source_lint import (
    iter_calls,
    iter_source_files,
    parse_module,
    resolve_patch_target,
)


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"


def _iter_test_py_files() -> list[pathlib.Path]:
    return list(iter_source_files(_TESTS_DIR))


def _is_patch_dict_call(node: ast.Call) -> bool:
    """``patch.dict(...)`` / ``*.patch.dict(...)`` — different mechanism."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "dict":
        return False
    inner = func.value
    if isinstance(inner, ast.Name) and inner.id == "patch":
        return True
    if isinstance(inner, ast.Attribute) and inner.attr == "patch":
        return True
    return False


def _scan(path: pathlib.Path) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Return ``(hits, skips)``.

    ``hits`` is a list of ``(lineno, dotted_target, reason)`` for
    genuine resolution failures. ``skips`` is a list of human-readable
    reasons we couldn't analyse something (file unreadable, module
    crashed at import).
    """
    hits: list[tuple[int, str, str]] = []
    skips: list[str] = []
    tree = parse_module(path)
    if tree is None:
        return hits, skips

    for node in iter_calls(tree, dotted_name="patch"):
        # Exclude patch.dict — different mechanism. iter_calls(dotted_name="patch")
        # matches anything ending in .patch; patch.dict ends in .dict so it
        # won't show up here, but a future refactor of iter_calls could change
        # that — defensive check retained.
        if _is_patch_dict_call(node):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.JoinedStr):
            continue
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        dotted = first.value
        if "." not in dotted:
            continue
        res = resolve_patch_target(dotted)
        if res.ok:
            continue
        if res.skip:
            skips.append(
                f"{path.relative_to(_REPO_ROOT)}:{node.lineno}: {dotted} — {res.detail}"
            )
            continue
        hits.append((node.lineno, dotted, res.detail))
    return hits, skips


def test_patch_string_targets_resolve_in_tests():
    """Every ``patch("dotted.path", ...)`` in ``tests/**`` resolves to a
    real attribute on a real importable module.

    Failure modes flagged:

    - ``ImportError`` on the prefix — the module was moved or deleted.
    - ``AttributeError`` on the leaf — the symbol was renamed within
      its module (the classic silent-no-op bug).

    Exclusions:

    - ``patch.dict(...)`` — patches a mapping, not a dotted symbol.
    - ``patch.object(real_obj, "attr")`` — first arg is a real object,
      not a string.
    - First arg with no ``.`` — not a dotted-path pattern.
    - f-string first arg — dynamic target, can't statically resolve.

    If this test fails, you've reintroduced the silent-no-op
    ``mock.patch`` drift v2.10-WP03/WP05/WP07 each closed once.
    """
    all_hits: list[tuple[pathlib.Path, int, str, str]] = []
    all_skips: list[str] = []
    for path in _iter_test_py_files():
        # Don't scan THIS file — it deliberately contains synthetic-bad
        # patch strings inside the self-test below.
        if path.name == pathlib.Path(__file__).name:
            continue
        hits, skips = _scan(path)
        for lineno, dotted, detail in hits:
            all_hits.append((path, lineno, dotted, detail))
        all_skips.extend(skips)

    if all_hits:
        lines = [
            f"  {p.relative_to(_REPO_ROOT)}:{lineno}: patch({dotted!r}) — {detail}"
            for p, lineno, dotted, detail in all_hits
        ]
        pytest.fail(
            "Unresolvable ``mock.patch(...)`` targets detected — these "
            "patches silently become no-ops at runtime (production code "
            "runs unmocked, tests pass for the wrong reason). Either "
            "fix the dotted path or delete the stale test:\n"
            + "\n".join(lines)
        )


def test_patch_resolution_lint_detects_synthetic_bad(tmp_path: pathlib.Path):
    """Self-test: the resolver actually catches a synthetic bad target,
    so a future refactor of the scanner can't silently neuter the lint.

    Three cases:

    1. ``patch("os.path.this_symbol_does_not_exist_xyz", ...)`` — must
       be flagged as an AttributeError on a real module.
    2. ``patch("os.path.join", ...)`` — correct target, must NOT be
       flagged.
    3. ``patch.dict("os.environ", {...})`` — different mechanism, must
       NOT be flagged even though the first arg "looks dotted".
    """
    bad = tmp_path / "bad.py"
    bad.write_text(
        'from unittest.mock import patch\n'
        'def test_x():\n'
        '    with patch("os.path.this_symbol_does_not_exist_xyz", None):\n'
        '        pass\n'
    )
    hits, _ = _scan(bad)
    assert hits, "scanner should detect synthetic bad patch target"
    assert "this_symbol_does_not_exist_xyz" in hits[0][1]

    good = tmp_path / "good.py"
    good.write_text(
        'from unittest.mock import patch\n'
        'def test_x():\n'
        '    with patch("os.path.join", None):\n'
        '        pass\n'
    )
    hits, _ = _scan(good)
    assert not hits, f"scanner must not flag a real symbol; got {hits!r}"

    dict_form = tmp_path / "dict_form.py"
    dict_form.write_text(
        'from unittest.mock import patch\n'
        'def test_x():\n'
        '    with patch.dict("os.environ", {"X": "1"}):\n'
        '        pass\n'
    )
    hits, _ = _scan(dict_form)
    assert not hits, (
        f"scanner must not flag patch.dict() — different mechanism; got {hits!r}"
    )
