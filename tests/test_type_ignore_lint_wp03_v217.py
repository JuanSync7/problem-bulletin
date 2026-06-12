r"""v2.17-WP03 — ``# type: ignore`` / ``# noqa`` structural lint for ``app/``.

Background
----------
v2.17-WP02 pinned the TypeScript escape-hatch surface (`any`, `@ts-*`)
via ``frontend/src/__tests__/ts_any_lint.test.ts``. This file is the
Python mirror for the production tree: every ``# type: ignore`` and
``# noqa`` directive in ``app/**/*.py`` must appear in
``_OFFENDER_ALLOWLIST`` with a one-line ``BY-DESIGN:`` / ``LEGACY:``
justification.

PIN, not SWEEP — production code is untouched. A future WP can delete
LEGACY entries as it tightens the offender (and stale-entry detection
will force the deletion).

Scope
-----
- Scans ``app/**/*.py`` only. ``tests/``, ``alembic/``, ``scripts/`` are
  excluded — they are out of scope (alembic/ also lives at the repo
  root, not under app/, so the rglob naturally avoids it; the
  exclusion in ``_iter_app_py_files`` is defensive).
- Detects two comment-pragma patterns on a per-line basis:
    * ``# type: ignore`` — with or without a ``[code]`` suffix
      (``# type: ignore[arg-type]``, ``# type: ignore[attr-defined]``,
      etc.). Captured by ``r"#\s*type:\s*ignore\b"``.
    * ``# noqa`` — with or without ``: <rule>`` suffix
      (``# noqa: F401``, ``# noqa: BLE001 - reason``). Captured by
      ``r"#\s*noqa\b"``.
- Allow-list keys are ``path:line`` strings (path relative to repo
  root). Values are ``BY-DESIGN: <reason>`` or ``LEGACY: <reason>``.

Implementation choice
---------------------
Plain regex over ``Path.read_text().splitlines()`` — NOT AST. The
``ast`` module strips comments during parse, so an AST walk cannot
see ``# type: ignore`` or ``# noqa`` at all. Mirrors the v2.17-WP02
TypeScript approach where ``@ts-*`` directives were also caught via
regex (compiler API does not expose pragma comments as nodes either).

Edge cases (see ``.claude/lessons-learned/v2.17-wp03-diagnosis.md``):
- The patterns are searched on each whole line. A ``# type: ignore``
  embedded in a triple-quoted string literal would be a false positive,
  but no such site exists in ``app/`` today. Documented in the
  diagnosis doc; revisit only if a string-literal false-positive
  emerges.
- ``# type: ignore`` and ``# noqa`` on the same line both fire — and
  both are listed in the allow-list at the same ``path:line`` key,
  which is fine: a single dict key captures the line.

Pairs with
----------
- ``tests/test_create_app_factory_lint_wp09.py`` — canonical structural
  lint shape (allow-list + synthetic-bad self-tests + stale detection).
- ``tests/helpers/source_lint.py`` — ``iter_source_files`` helper.
- ``frontend/src/__tests__/ts_any_lint.test.ts`` — v2.17-WP02 TS twin.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.helpers.source_lint import iter_source_files


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP_DIR = _REPO_ROOT / "app"

# Defensive exclusion: ``alembic/`` lives at repo root today, not under
# ``app/``, so the rglob below already avoids it. If an ``app/migrations``
# subtree is ever introduced, the prefix check skips it.
_EXCLUDED_PREFIXES = ("app/migrations/", "app/alembic/")


_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\b")
_NOQA_RE = re.compile(r"#\s*noqa\b")


# -----------------------------------------------------------------------------
# Offender allow-list — ``path:line`` → ``BY-DESIGN`` / ``LEGACY`` justification.
#
# CLOSED inventory of the pre-WP03 state. Adding NEW entries should be
# exceptional and paired with a clear justification — prefer fixing the
# underlying type / lint issue instead. Stale-entry detection (below) fails
# loud if a file moves or the offender disappears, so this dict cannot drift
# silently past the real code.
# -----------------------------------------------------------------------------
_OFFENDER_ALLOWLIST: dict[str, str] = {
    # --- BY-DESIGN: type: ignore -------------------------------------------
    # v2.19-WP02: removed -- both pragmas were flagged by mypy with
    # ``warn_unused_ignores = true`` as redundant under the new
    # [tool.mypy] config. The underlying type-arg / attr-defined issues
    # mypy used to flag are no longer present (Python 3.12 generic
    # subscription of re.Match; correct module-level inference of
    # async_session_factory). The inline ignores were deleted at the
    # same time as this allow-list entry.
    "app/routes/admin/__init__.py:8": (
        "BY-DESIGN: fallback stub for ``require_admin`` when the auth "
        "module is unavailable at import time; mypy flags the redefinition "
        "against the real symbol, ``type: ignore[misc]`` pins the "
        "deliberate import-time shim."
    ),
    # --- BY-DESIGN: noqa ----------------------------------------------------
    "app/main.py:138": (
        "BY-DESIGN: local re-import of ``async_session_factory`` inside the "
        "lifespan startup path so the symbol is resolved lazily; ``F811`` "
        "(redefinition) is the expected lint we suppress."
    ),
    "app/models/__init__.py:3": (
        "BY-DESIGN: ``Base`` re-export — module is the SQLAlchemy registry "
        "barrel; ``F401`` (imported-but-unused) is exactly the side-effect "
        "we want."
    ),
    "app/models/__init__.py:5": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:6": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:15": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:16": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:17": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:18": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:19": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:20": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:21": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:22": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:23": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:24": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:25": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:28": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:29": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:30": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:31": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:32": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:33": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:36": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:42": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:43": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:46": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:47": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:50": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:53": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:56": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/models/__init__.py:59": "BY-DESIGN: model re-export barrel; F401 is the side effect.",
    "app/schemas/__init__.py:10": (
        "BY-DESIGN: ``from app.schemas._legacy import *`` is the schemas "
        "barrel for legacy DTOs awaiting per-entity migration; ``F401,F403`` "
        "(star-import + unused-re-export) are exactly the side effects we "
        "want for the barrel."
    ),
    "app/mcp_server/tools.py:38": (
        "BY-DESIGN: broad ``except Exception`` is the uniform error-translation "
        "boundary for the MCP tools surface (mirrors the FastAPI handler "
        "envelope); ``BLE001`` is suppressed here intentionally — see the "
        "v2.16-WP04 retrospective for the BLE001 audit."
    ),
    "app/mcp_server/server.py:100": (
        "BY-DESIGN: broad ``except Exception`` at the MCP server boundary "
        "performs uniform translation into the JSON-RPC error envelope; the "
        "inline comment already states ``uniform translation``."
    ),
    "app/logging.py:82": (
        "BY-DESIGN: local import of ``get_correlation_id`` inside the log "
        "filter avoids a top-level circular import (logging is imported "
        "during settings/app boot before the middleware module is ready); "
        "``WPS433`` (nested-import) is the expected suppression."
    ),
    "app/services/exceptions.py:33": (
        "BY-DESIGN: ``\"datetime\"`` is a stringified forward reference for "
        "``datetime.datetime`` imported only under ``TYPE_CHECKING``; "
        "``F821`` (undefined name) is the expected suppression at runtime."
    ),
    "app/services/tickets.py:417": (
        "BY-DESIGN: local import of ``User`` inside the function body breaks "
        "a circular import; inline comment already states ``local import``; "
        "``WPS433`` is the expected suppression."
    ),
    "app/routes/health.py:33": (
        "BY-DESIGN: broad ``except Exception`` in a health probe — by "
        "definition the probe must report ANY failure mode as unhealthy "
        "rather than crash the process; ``BLE001`` suppressed intentionally."
    ),
    "app/routes/health.py:57": (
        "BY-DESIGN: same as :33 — the second health probe (cache/db check) "
        "also catches broadly so a single dependency failure cannot mask the "
        "rest of the probe."
    ),
    "app/routes/admin/__init__.py:17": (
        "BY-DESIGN: late import of admin subroutes after ``admin_router`` "
        "is constructed so each subrouter can attach via ``include_router``; "
        "``E402`` (module-level import not at top) and ``F401`` "
        "(imported-but-unused) are both expected here."
    ),
}


def _iter_app_py_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in iter_source_files(_APP_DIR):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        files.append(path)
    return files


def _scan_lines(source: str) -> list[tuple[int, str]]:
    """Return ``(lineno, kind)`` for every line in ``source`` containing
    a ``# type: ignore`` or ``# noqa`` pragma.

    ``kind`` is ``'type-ignore'`` or ``'noqa'``. A line that matches BOTH
    yields two entries (same lineno, different kinds) — the allow-list
    keys on lineno only, so both share one entry. No such site exists
    today; emitted-as-tuple is for diagnostic clarity if it ever does.
    """
    hits: list[tuple[int, str]] = []
    for idx, line in enumerate(source.splitlines(), start=1):
        if _TYPE_IGNORE_RE.search(line):
            hits.append((idx, "type-ignore"))
        if _NOQA_RE.search(line):
            hits.append((idx, "noqa"))
    return hits


def _scan_path(path: pathlib.Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
        return []
    return _scan_lines(source)


# -----------------------------------------------------------------------------
# Main lint
# -----------------------------------------------------------------------------


def test_no_type_ignore_or_noqa_outside_allowlist():
    """Every ``# type: ignore`` and ``# noqa`` directive in ``app/**/*.py``
    appears in ``_OFFENDER_ALLOWLIST`` keyed by ``path:line``.

    Failure modes:
    - A new offender (no allow-list entry) — fix the underlying type /
      lint issue, or add a paired allow-list entry with a clear
      ``BY-DESIGN:`` / ``LEGACY:`` justification.
    - A stale allow-list entry (file or line no longer has the pragma)
      — remove the entry. The lint fails loud to force the deletion so
      the allow-list cannot drift past the real code.
    """
    offenders: list[tuple[str, int, str]] = []
    seen_keys: set[str] = set()

    for path in _iter_app_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for lineno, kind in _scan_path(path):
            key = f"{rel}:{lineno}"
            if key in _OFFENDER_ALLOWLIST:
                seen_keys.add(key)
                continue
            offenders.append((rel, lineno, kind))

    stale_keys = sorted(set(_OFFENDER_ALLOWLIST) - seen_keys)

    msgs: list[str] = []
    if offenders:
        body = "\n".join(
            f"  {rel}:{ln} ({kind}) — add an _OFFENDER_ALLOWLIST entry "
            f"with a BY-DESIGN: or LEGACY: justification, or fix the "
            f"underlying issue"
            for rel, ln, kind in offenders
        )
        msgs.append(
            "New ``# type: ignore`` / ``# noqa`` directives in app/ "
            "without an _OFFENDER_ALLOWLIST entry:\n" + body
        )
    if stale_keys:
        body = "\n".join(f"  {k}" for k in stale_keys)
        msgs.append(
            "Stale ``_OFFENDER_ALLOWLIST`` entries (path:line no longer "
            "contains a # type: ignore / # noqa pragma — please remove):\n"
            + body
        )
    if msgs:
        pytest.fail("\n\n".join(msgs))


# -----------------------------------------------------------------------------
# Self-tests: prove the scanner actually flags / clears the patterns.
# -----------------------------------------------------------------------------


def test_scanner_flags_synthetic_bare_type_ignore(tmp_path: pathlib.Path):
    """Synthetic ``# type: ignore`` (no code suffix) — must be flagged."""
    f = tmp_path / "bad_type_ignore.py"
    f.write_text(
        "def foo(x):\n"
        "    return x.bar  # type: ignore\n"
    )
    hits = _scan_path(f)
    assert any(kind == "type-ignore" for _, kind in hits), (
        f"scanner must flag bare ``# type: ignore``; got: {hits!r}"
    )


def test_scanner_flags_synthetic_type_ignore_with_code(tmp_path: pathlib.Path):
    """Synthetic ``# type: ignore[arg-type]`` — code-suffix variant must be flagged."""
    f = tmp_path / "bad_type_ignore_code.py"
    f.write_text(
        "def foo(x: int) -> None:\n"
        "    foo('not an int')  # type: ignore[arg-type]\n"
    )
    hits = _scan_path(f)
    assert any(kind == "type-ignore" for _, kind in hits), (
        f"scanner must flag ``# type: ignore[arg-type]``; got: {hits!r}"
    )


def test_scanner_flags_synthetic_noqa(tmp_path: pathlib.Path):
    """Synthetic ``# noqa: F401`` — must be flagged."""
    f = tmp_path / "bad_noqa.py"
    f.write_text(
        "import os  # noqa: F401\n"
    )
    hits = _scan_path(f)
    assert any(kind == "noqa" for _, kind in hits), (
        f"scanner must flag ``# noqa: F401``; got: {hits!r}"
    )


def test_scanner_does_not_flag_clean_line(tmp_path: pathlib.Path):
    """Synthetic clean Python — no comment pragmas — must NOT be flagged.

    Also verifies the scanner does not produce false positives on the
    bare words ``type`` or ``noqa`` appearing inside ordinary code or
    docstrings without the leading ``#`` comment marker.
    """
    f = tmp_path / "clean.py"
    f.write_text(
        '"""A docstring mentioning the word noqa and type but not as pragmas."""\n'
        "def kind(t):\n"
        "    # ordinary comment about types\n"
        "    return type(t).__name__\n"
    )
    hits = _scan_path(f)
    assert not hits, f"scanner must not flag clean source; got: {hits!r}"
