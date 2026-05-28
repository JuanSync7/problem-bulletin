"""v2.12-WP02 (Bucket B1) — shared source-shape lint primitives.

Extracted from the seven independent source-lints landed in v2.11
(WP02 / WP08-a / WP08-b / WP09-a / WP09-b / WP10 / WP11 / WP12 / WP15).
Each one walked ``app/`` or ``tests/`` looking for a forbidden AST
shape; each one independently re-implemented file iteration,
``ast.parse``+``ast.walk``, and (in WP08-a) the
``unittest.mock._get_target`` longest-importable-prefix algorithm.

This module consolidates the plumbing. Lint semantics are unchanged —
this is a pure refactor; downstream tests keep their existing
assertion shapes.

Public API
----------
* ``iter_source_files(root, *, allow_list=None, suffix=".py")`` —
  best-effort iterator over source files under ``root``, skipping
  ``__pycache__`` and ``.venv``. ``allow_list`` is an iterable of
  paths relative to ``root`` to exclude (accepts ``set``, ``list``,
  ``dict.keys()``).
* ``parse_module(path)`` — ``ast.parse(path.read_text(),
  filename=str(path))``; returns ``None`` on OSError /
  UnicodeDecodeError / SyntaxError for best-effort scans.
* ``iter_string_literals(tree)`` — yields ``(node, value)`` for every
  ``ast.Constant`` whose ``value`` is ``str``, including those nested
  inside ``ast.JoinedStr``.
* ``iter_calls(tree, *, dotted_name=None)`` — yields every
  ``ast.Call``; if ``dotted_name`` is given, filters to calls whose
  ``.func`` chain matches the dotted path (conservative tail-match on
  Name/Attribute).
* ``resolve_patch_target(target)`` — implements unittest.mock's
  ``_get_target`` algorithm and returns a ``PatchTargetResolution``
  3-state record (``ok`` / ``unresolvable`` / ``skip``).
"""
from __future__ import annotations

import ast
import importlib
import pathlib
from dataclasses import dataclass
from typing import Iterable, Iterator


__all__ = [
    "PatchTargetResolution",
    "iter_calls",
    "iter_source_files",
    "iter_string_literals",
    "parse_module",
    "resolve_patch_target",
]


# ---------------------------------------------------------------------------
# File iteration
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({"__pycache__", ".venv"})


def iter_source_files(
    root: pathlib.Path,
    *,
    allow_list: Iterable[str] | None = None,
    suffix: str = ".py",
) -> Iterator[pathlib.Path]:
    """Yield every ``*<suffix>`` file under ``root`` in sorted order.

    Skips any path traversing a directory in ``_SKIP_DIRS``
    (``__pycache__`` or ``.venv``). ``allow_list`` is an iterable of
    paths relative to ``root`` (string form) to exclude from the yield;
    the canonical consumer shape is ``dict[str, str].keys()`` (the
    WP09 / WP11 allow-list dicts).
    """
    excluded = {str(s) for s in (allow_list or ())}
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:  # pragma: no cover - defensive
            rel = str(path)
        if rel in excluded:
            continue
        yield path


# ---------------------------------------------------------------------------
# AST parsing
# ---------------------------------------------------------------------------


def parse_module(path: pathlib.Path) -> ast.Module | None:
    """``ast.parse`` ``path`` with file-name set. Returns ``None`` on
    OSError, UnicodeDecodeError, or SyntaxError — the established
    best-effort behaviour from every existing v2.11 lint.
    """
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def iter_string_literals(
    tree: ast.AST,
) -> Iterator[tuple[ast.Constant, str]]:
    """Yield ``(constant_node, value)`` for every ``ast.Constant`` whose
    ``value`` is ``str``. JoinedStr (f-string) literal segments are
    yielded individually — matches the WP08-b / WP15 walk pattern.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, node.value


# ---------------------------------------------------------------------------
# Call walking
# ---------------------------------------------------------------------------


def _func_dotted_chain(func: ast.expr) -> list[str] | None:
    """Return the dotted attribute chain for ``func`` as a list of names
    (e.g. ``ast.Attribute(value=ast.Name('os'), attr='path').attr='join'``
    → ``['os', 'path', 'join']``). Returns ``None`` for non-Name/Attribute
    chains (e.g. ``foo()()`` — ``Call`` as ``func``).
    """
    parts: list[str] = []
    cur: ast.expr = func
    while True:
        if isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
            continue
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return list(reversed(parts))
        return None


def iter_calls(
    tree: ast.AST,
    *,
    dotted_name: str | None = None,
) -> Iterator[ast.Call]:
    """Yield every ``ast.Call`` in ``tree``. When ``dotted_name`` is
    given, filter to calls whose ``func`` chain matches it.

    Matching is conservative: the chain produced by
    ``_func_dotted_chain`` must END with the components of
    ``dotted_name`` (so ``dotted_name='patch'`` matches both
    ``patch(...)`` and ``mock.patch(...)`` and
    ``unittest.mock.patch(...)``; ``dotted_name='os.environ.setdefault'``
    matches ``os.environ.setdefault(...)`` but not ``x.setdefault(...)``).
    """
    target_parts = dotted_name.split(".") if dotted_name else None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if target_parts is None:
            yield node
            continue
        chain = _func_dotted_chain(node.func)
        if chain is None:
            continue
        if len(chain) < len(target_parts):
            continue
        if chain[-len(target_parts):] == target_parts:
            yield node


# ---------------------------------------------------------------------------
# unittest.mock patch-target resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatchTargetResolution:
    """Result of ``resolve_patch_target``.

    Three terminal states:

    * ``ok=True`` — the target resolves (or has no ``.`` — out of scope,
      passes by convention so callers can apply a single filter).
    * ``ok=False, skip=False`` — genuine resolution failure
      (``ImportError`` on every prefix, or ``AttributeError`` on the
      tail). The detail string describes the failure.
    * ``ok=False, skip=True`` — environmental failure (import-time
      side-effect crash). Caller should treat as a skip, not a
      regression. ``detail`` carries the underlying exception text.
    """

    ok: bool
    skip: bool
    detail: str


def resolve_patch_target(target: str) -> PatchTargetResolution:
    """Mirror ``unittest.mock._get_target``: import the longest
    importable prefix of ``target``, then walk the remaining components
    via ``getattr``.

    Single-token (no ``.``) targets are out of scope (e.g.
    ``patch.dict('K')`` — the key, not a symbol). They return
    ``ok=True`` for caller convenience.
    """
    if "." not in target:
        return PatchTargetResolution(ok=True, skip=False, detail="no dot")

    parts = target.split(".")
    base = None
    consumed = 0
    last_import_error: Exception | None = None
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        try:
            base = importlib.import_module(prefix)
            consumed = i
            break
        except ImportError as exc:
            last_import_error = exc
            continue
        except Exception as exc:  # pragma: no cover - defensive
            return PatchTargetResolution(
                ok=False,
                skip=True,
                detail=f"{type(exc).__name__}({prefix!r}): {exc}",
            )

    if base is None:
        return PatchTargetResolution(
            ok=False,
            skip=False,
            detail=(
                f"ImportError: no importable prefix of {target!r}"
                + (f" (last: {last_import_error})" if last_import_error else "")
            ),
        )

    obj = base
    walked = parts[:consumed]
    for attr in parts[consumed:]:
        if not hasattr(obj, attr):
            walked_repr = ".".join(walked) or "<root>"
            return PatchTargetResolution(
                ok=False,
                skip=False,
                detail=(
                    f"AttributeError: {walked_repr!r} has no attribute {attr!r}"
                ),
            )
        obj = getattr(obj, attr)
        walked.append(attr)
    return PatchTargetResolution(ok=True, skip=False, detail="ok")
