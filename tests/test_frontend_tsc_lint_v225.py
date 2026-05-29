r"""v2.25-WP03 -- tsc --noEmit typecheck PIN for ``frontend/``.

Background
----------
WP02 swept the frontend tsc-noEmit channel from 76 errors down to 1
(across Categories A/B/C/E/F/G), and WP03a fixed the final real bug at
``frontend/src/pages/ProblemDetail.tsx:1052``. The cold-floor is now
**0 tsc errors**. This file PINs that floor so any future regression
fails loud on CI.

Why this pin exists (forward rule (yy))
---------------------------------------
``tsc --noEmit`` is a SEPARABLE type channel from vitest. vitest runs
the project's transpile pipeline (Vite / esbuild) which intentionally
strips types without checking them -- a malformed handler signature can
slip through vitest green and still ship a runtime bug. The mypy PIN at
``tests/test_typecheck_lint_v219_wp02.py`` already enforces the Python
side; this is the TypeScript mirror.

Pairs with
----------
* ``tests/test_typecheck_lint_v219_wp02.py`` -- the canonical mypy PIN
  shape this test mirrors (bidirectional stale-detection, BY-DESIGN /
  LEGACY rationale strings, parser self-tests, opt-in synthetic-bad).
* ``.claude/lessons-learned/v2.25-wp01-diagnosis.md`` -- WP01 recon.
* ``.claude/lessons-learned/v2.25-wp02-diagnosis.md`` -- WP02 sweep
  (76 → 1).
* ``.claude/lessons-learned/v2.25-wp03-diagnosis.md`` -- WP03a fix +
  this PIN.

Running
-------
Marked ``@pytest.mark.slow`` because ``npx tsc --noEmit`` shells out and
takes ~10-30s. Dev runs that filter with ``-m "not slow"`` will skip it;
CI runs the full suite and therefore enforces the floor. To run just
this file::

    .venv/bin/python -m pytest tests/test_frontend_tsc_lint_v225.py -v

To enable the opt-in subprocess synthetic-bad self-test::

    RUN_TSC_SELFTEST=1 .venv/bin/python -m pytest \
        tests/test_frontend_tsc_lint_v225.py::test_tsc_subprocess_flags_synthetic_bad_file
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend"


# tsc --noEmit emits one error per line in the form:
#   ``src/path/to/file.tsx(LINE,COL): error TSXXXX: message``
# We capture (path, line, errcode). Continuation lines (indented detail
# of multi-line messages) do NOT match and are silently skipped, which is
# exactly what we want -- the top-level (line, file, code) triple is the
# stable identity for the bidirectional dict.
_TSC_LINE_RE = re.compile(
    r"^(?P<path>[^\s()][^()]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"error\s+(?P<code>TS\d+):\s.*$"
)


# -----------------------------------------------------------------------------
# Offender allow-list -- ``path:line:errcode`` -> BY-DESIGN rationale.
#
# Initial state: EMPTY. WP02 + WP03a brought the floor to 0 errors, so
# the pin enforces the 0-floor. Any future drift surfaces as a NEW
# offender. If a regression turns out to be BY-DESIGN (framework typing
# limit), add an entry here with the rationale; otherwise fix the code.
# -----------------------------------------------------------------------------
_OFFENDER_ALLOWLIST: dict[str, str] = {}


def _run_tsc() -> tuple[int, str]:
    """Run ``npx tsc --noEmit`` from ``frontend/`` and return ``(rc, output)``.

    tsc writes errors to stdout. We invoke from ``frontend/`` because the
    project's ``tsconfig.json`` lives there and the emitted paths are
    relative to that cwd (``src/pages/ProblemDetail.tsx(1052,57): ...``).
    Invoking from the repo root would prefix every path with ``frontend/``
    and the parser regex would have to be relaxed.
    """
    npx = shutil.which("npx")
    if npx is None:
        pytest.skip("npx not on PATH -- cannot run tsc PIN.")
    proc = subprocess.run(
        [npx, "tsc", "--noEmit"],
        cwd=str(_FRONTEND_DIR),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _parse_tsc_output(output: str) -> list[tuple[str, int, str]]:
    """Parse tsc output into ``(path, line, errcode)`` tuples.

    Multi-line error messages: tsc emits a header line matching
    ``_TSC_LINE_RE`` and zero-or-more indented continuation lines that
    detail the type mismatch. Continuation lines do not match the regex
    and are skipped, leaving exactly one tuple per distinct error site.
    Returns a deterministic-order list (input order preserved).
    """
    hits: list[tuple[str, int, str]] = []
    for raw in output.splitlines():
        m = _TSC_LINE_RE.match(raw)
        if not m:
            continue
        hits.append((m.group("path"), int(m.group("line")), m.group("code")))
    return hits


# -----------------------------------------------------------------------------
# Main lint
# -----------------------------------------------------------------------------


@pytest.mark.slow
def test_tsc_offenders_match_allowlist():
    """Every tsc-noEmit error in ``frontend/`` is pinned in ``_OFFENDER_ALLOWLIST``.

    Failure modes (bidirectional, per v2.18 forward rule (s)):
      * NEW offender -- not in allow-list. Fix the underlying type issue
        or add an entry with a BY-DESIGN: justification.
      * STALE allow-list entry -- no longer present in tsc output. Remove
        the entry so the dict cannot drift past the real code.

    Initial floor is 0 errors (WP02 + WP03a). The allow-list is empty,
    so any non-empty tsc output fails this test.
    """
    returncode, output = _run_tsc()
    hits = _parse_tsc_output(output)

    seen_keys: set[str] = set()
    new_offenders: list[tuple[str, int, str]] = []
    for path, line, code in hits:
        key = f"{path}:{line}:{code}"
        if key in _OFFENDER_ALLOWLIST:
            seen_keys.add(key)
            continue
        new_offenders.append((path, line, code))

    stale_keys = sorted(set(_OFFENDER_ALLOWLIST) - seen_keys)

    msgs: list[str] = []
    if new_offenders:
        body = "\n".join(
            f"  {p}:{ln}:{c}"
            for p, ln, c in sorted(new_offenders)
        )
        msgs.append(
            f"NEW tsc offenders ({len(new_offenders)}) not in "
            "_OFFENDER_ALLOWLIST -- fix the underlying type issue OR "
            "add an entry with a BY-DESIGN: justification:\n"
            + body
        )
    if stale_keys:
        body = "\n".join(f"  {k}" for k in stale_keys)
        msgs.append(
            f"STALE _OFFENDER_ALLOWLIST entries ({len(stale_keys)}) "
            "-- tsc no longer reports this path:line:errcode. Remove "
            "the entry so the allow-list cannot drift past real code:\n"
            + body
        )
    if msgs:
        msgs.append(f"tsc exit code: {returncode}")
        pytest.fail("\n\n".join(msgs))


# -----------------------------------------------------------------------------
# Self-tests -- prove the parser actually flags / clears the patterns.
# -----------------------------------------------------------------------------


def test_parser_extracts_single_error():
    """Synthetic tsc line -- parser must extract ``(path, line, errcode)``."""
    output = (
        "src/pages/ProblemDetail.tsx(1052,57): error TS2322: Type 'X' is not assignable to type 'Y'.\n"
    )
    assert _parse_tsc_output(output) == [
        ("src/pages/ProblemDetail.tsx", 1052, "TS2322"),
    ]


def test_parser_extracts_multiple_errors_and_codes():
    """Multiple distinct error codes -- parser must extract all in order."""
    output = (
        "src/foo.tsx(1,1): error TS2322: bad assign\n"
        "src/bar.ts(7,3): error TS2345: bad arg\n"
        "src/baz.tsx(99,12): error TS2769: no overload matches\n"
    )
    assert _parse_tsc_output(output) == [
        ("src/foo.tsx", 1, "TS2322"),
        ("src/bar.ts", 7, "TS2345"),
        ("src/baz.tsx", 99, "TS2769"),
    ]


def test_parser_skips_multiline_continuation():
    """Indented continuation lines of a multi-line tsc error must NOT match."""
    output = (
        "src/pages/ProblemDetail.tsx(1052,57): error TS2322: Type 'A' is not assignable to type 'B'.\n"
        "  Types of parameters 'showLoading' and 'event' are incompatible.\n"
        "    Type 'MouseEvent<HTMLButtonElement, MouseEvent>' is not assignable to type 'boolean | undefined'.\n"
    )
    assert _parse_tsc_output(output) == [
        ("src/pages/ProblemDetail.tsx", 1052, "TS2322"),
    ]


def test_parser_returns_empty_on_clean_output():
    """No errors -- parser returns empty list (the 0-floor case)."""
    assert _parse_tsc_output("") == []
    assert _parse_tsc_output("\n\n") == []


def test_parser_handles_paths_with_subdirs():
    """Nested src paths must parse cleanly."""
    output = (
        "src/components/__tests__/Foo.test.tsx(10,5): error TS7006: implicit any\n"
        "src/pages/Kanban/KanbanBoard.tsx(200,1): error TS2304: cannot find name\n"
    )
    assert _parse_tsc_output(output) == [
        ("src/components/__tests__/Foo.test.tsx", 10, "TS7006"),
        ("src/pages/Kanban/KanbanBoard.tsx", 200, "TS2304"),
    ]


# -----------------------------------------------------------------------------
# End-to-end self-test -- prove tsc actually catches a synthetic bad file.
# Skipped by default; enabled via env var for manual verification.
# -----------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_TSC_SELFTEST") != "1",
    reason="Heavy self-test -- set RUN_TSC_SELFTEST=1 to enable.",
)
def test_tsc_subprocess_flags_synthetic_bad_file():
    """Synthetic broken TSX file -- tsc must produce a parseable error.

    Writes a deliberately bad file into ``frontend/src/`` (so it is
    included by tsconfig), runs the PIN's tsc invocation, asserts that
    _parse_tsc_output extracts at least one offender pointing at the
    bad file. ALWAYS deletes the scratch file in a finally block --
    even on assertion failure -- so the workspace stays clean.

    Mirrors ``test_mypy_subprocess_flags_synthetic_bad_file`` from the
    mypy PIN. Proves the pin has teeth: drop a real type error in the
    tree, the PIN flags it.
    """
    scratch = _FRONTEND_DIR / "src" / "__tsc_pin_selftest__.ts"
    scratch.write_text(
        "// v2.25-WP03 PIN self-test scratch file -- safe to delete.\n"
        "const n: number = 'not-a-number';\n"
        "export default n;\n"
    )
    try:
        _, output = _run_tsc()
        hits = _parse_tsc_output(output)
        bad_hits = [
            (p, ln, c) for p, ln, c in hits
            if p.endswith("__tsc_pin_selftest__.ts")
        ]
        assert bad_hits, (
            "tsc must flag the synthetic-bad file -- got output:\n"
            + output[:2000]
        )
    finally:
        scratch.unlink(missing_ok=True)
