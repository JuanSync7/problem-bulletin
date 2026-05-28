r"""v2.19-WP02 -- mypy typecheck PIN for ``app/``.

Background
----------
WP01 confirmed that mypy 1.20.1 is already wired in ``pyproject.toml``
under ``[project.optional-dependencies].dev``. With the new
``[tool.mypy]`` block (also landed in WP02) the sniff yields a finite
offender set. This file PINs that set so future regressions fail loud:

* Every ``path:line:errcode`` triple emitted by ``mypy app`` must appear
  in ``_OFFENDER_ALLOWLIST`` with a one-line ``BY-DESIGN:`` /
  ``LEGACY:`` justification.
* Bidirectional stale-entry detection (v2.18 forward rule (s)) -- an
  allow-list entry that no longer corresponds to a live offender also
  fails the lint so the dict cannot drift past the real code.

Pairs with
----------
* ``tests/test_type_ignore_lint_wp03_v217.py`` -- the ``# type: ignore`` /
  ``# noqa`` allow-list lint (canonical shape we mirror here).
* ``tests/test_create_app_factory_lint_wp09.py`` -- structural-lint
  template.
* ``pyproject.toml [tool.mypy]`` -- the mypy config this test validates.
* ``.claude/lessons-learned/v2.19-wp02-diagnosis.md`` -- recon + final
  numbers + BY-DESIGN-vs-LEGACY classification summary.

Performance
-----------
mypy on the 134-file ``app/`` tree takes ~25-45s cold, ~5-15s warm via
``.mypy_cache/``. Test runs subprocess-isolated so the cache survives
between invocations. If the cache is missing on CI the first run pays
the cold cost once.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP_DIR = _REPO_ROOT / "app"


# Mypy emits one error per line in the form:
#   ``app/path/to/file.py:LINE: error: <message>  [<code>]``
# We capture (path, line, errcode). Lines like ``: note:`` are skipped.
_MYPY_LINE_RE = re.compile(
    r"^(?P<path>app/[^:]+):(?P<line>\d+):\s*error:\s.*\[(?P<code>[a-z][a-z0-9_-]*)\]\s*$"
)


# -----------------------------------------------------------------------------
# Offender allow-list -- ``path:line:errcode`` -> BY-DESIGN / LEGACY rationale.
#
# Classification rules (per v2.19-WP02 prompt):
#   * BY-DESIGN: framework typing limit forcing the pattern -- SQLAlchemy
#     ``Column[T]`` leakage past the ORM boundary, Pydantic v2 ``model_config
#     extra='allow'`` shape variants, runtime-injected attrs, Starlette /
#     FastAPI ASGI mount signature variance, etc. The code is correct;
#     mypy cannot model it without a plugin.
#   * LEGACY: genuine debt the project should eventually fix. A future WP
#     can tighten the offender (and the bidirectional stale-detection will
#     force the deletion).
# -----------------------------------------------------------------------------
_OFFENDER_ALLOWLIST: dict[str, str] = {
    "app/main.py:321:arg-type": (
        "BY-DESIGN: Starlette/FastAPI handler callable variance -- the "
        "FastAPI exception-handler / ASGI mount signature is broader at "
        "runtime than mypy's stub. Framework typing limit."
    ),
    "app/mcp_server/server.py:145:arg-type": (
        "BY-DESIGN: Starlette/FastAPI handler callable variance -- the "
        "FastAPI exception-handler / ASGI mount signature is broader at "
        "runtime than mypy's stub. Framework typing limit."
    ),
    "app/routes/comments.py:119:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/routes/comments.py:146:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/routes/comments.py:167:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/routes/comments.py:57:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/routes/comments.py:71:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/audit_log_archive.py:221:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/audit_log_retention.py:163:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/audit_log_retention.py:180:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/audit_log_retention.py:189:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/categories.py:124:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/context.py:81:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/due_soon_scanner.py:158:assignment": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `assignment` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/due_soon_scanner.py:206:arg-type": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `arg-type` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/exceptions.py:33:name-defined": (
        "BY-DESIGN: `datetime` is imported only under TYPE_CHECKING; the "
        "stringified forward reference is resolvable at static-analysis "
        "time; paired with v2.17-WP03 `# noqa: F821` allow-list entry."
    ),
    "app/services/feed.py:35:dict-item": (
        "BY-DESIGN: collection-item-type variance at the response-DTO "
        "boundary -- runtime validation coerces."
    ),
    "app/services/feed.py:54:assignment": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `assignment` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/problems.py:150:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/problems.py:160:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/problems.py:161:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/problems.py:164:return-value": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `return-value` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/problems.py:252:operator": (
        "BY-DESIGN: operator applied across an Optional pair where the "
        "None branch is excluded by a prior guard mypy cannot see "
        "(typically a conditional return)."
    ),
    "app/services/ticket_notifications.py:1125:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
    "app/services/tickets.py:1195:arg-type": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `arg-type` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/tickets.py:1196:arg-type": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `arg-type` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/tickets.py:698:assignment": (
        "BY-DESIGN: SQLAlchemy Column[T] / Mapped[T] vs T variance at the "
        "ORM boundary -- `assignment` is the artefact of the missing "
        "SQLAlchemy mypy plugin; runtime descriptor returns T correctly."
    ),
    "app/services/watches.py:72:attr-defined": (
        "BY-DESIGN: attribute access against a SQLAlchemy descriptor / "
        "lazy-loaded relationship; `attr-defined` artefact of the missing "
        "SQLAlchemy plugin."
    ),
}



def _run_mypy() -> tuple[int, str]:
    """Run ``mypy app`` via the venv's mypy and return ``(returncode, stdout)``.

    Mypy writes errors to stdout (not stderr) by default. The cache lives
    in ``.mypy_cache/`` at the repo root and survives between invocations.
    """
    env = os.environ.copy()
    # Pass --no-color so error lines parse cleanly regardless of TTY.
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "app", "--no-color-output"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _parse_mypy_output(output: str) -> list[tuple[str, int, str]]:
    """Parse mypy output into ``(path, line, errcode)`` tuples.

    Lines that don't match the error pattern (notes, summary, etc.) are
    skipped silently. Returns a deterministic-order list.
    """
    hits: list[tuple[str, int, str]] = []
    for raw in output.splitlines():
        m = _MYPY_LINE_RE.match(raw)
        if not m:
            continue
        hits.append((m.group("path"), int(m.group("line")), m.group("code")))
    return hits


# -----------------------------------------------------------------------------
# Main lint
# -----------------------------------------------------------------------------

# Marked ``slow`` so a future WP can gate it (pytest -m "not slow") if the
# subprocess invocation becomes the long pole on CI. Currently runs in
# ~5-45s depending on cache state -- acceptable for a P1 typecheck gate.
@pytest.mark.slow
def test_mypy_offenders_match_allowlist():
    """Every mypy error in ``app/`` is pinned in ``_OFFENDER_ALLOWLIST``.

    Failure modes (bidirectional, per v2.18 forward rule (s)):
      * NEW offender -- not in allow-list. Fix the underlying type issue
        or add an entry with a BY-DESIGN / LEGACY justification.
      * STALE allow-list entry -- no longer present in mypy output. Remove
        the entry so the dict cannot drift past the real code.
    """
    returncode, output = _run_mypy()
    hits = _parse_mypy_output(output)

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
            f"NEW mypy offenders ({len(new_offenders)}) not in "
            "_OFFENDER_ALLOWLIST -- fix the underlying type issue OR "
            "add an entry with a BY-DESIGN: / LEGACY: justification:\n"
            + body
        )
    if stale_keys:
        body = "\n".join(f"  {k}" for k in stale_keys)
        msgs.append(
            f"STALE _OFFENDER_ALLOWLIST entries ({len(stale_keys)}) "
            "-- mypy no longer reports this path:line:errcode. Remove "
            "the entry so the allow-list cannot drift past real code:\n"
            + body
        )
    if msgs:
        # Surface the mypy summary line for context.
        summary = ""
        for line in output.splitlines():
            if line.startswith("Found ") or line.startswith("Success:"):
                summary = line
                break
        if summary:
            msgs.insert(0, f"mypy summary: {summary}")
        msgs.append(f"mypy exit code: {returncode}")
        pytest.fail("\n\n".join(msgs))


# -----------------------------------------------------------------------------
# Self-tests -- prove the parser actually flags / clears the patterns.
# -----------------------------------------------------------------------------


def test_parser_extracts_single_error():
    """Synthetic mypy line -- parser must extract ``(path, line, errcode)``."""
    output = (
        "app/services/tickets.py:42: error: Some message here  [arg-type]\n"
        "Found 1 error in 1 file (checked 1 source file)\n"
    )
    assert _parse_mypy_output(output) == [
        ("app/services/tickets.py", 42, "arg-type"),
    ]


def test_parser_extracts_multiple_errors_and_codes():
    """Multiple distinct error codes -- parser must extract all."""
    output = (
        "app/foo.py:1: error: Bad arg  [arg-type]\n"
        "app/bar.py:7: error: Cannot assign  [assignment]\n"
        "app/baz.py:99: error: Missing attr  [attr-defined]\n"
    )
    assert _parse_mypy_output(output) == [
        ("app/foo.py", 1, "arg-type"),
        ("app/bar.py", 7, "assignment"),
        ("app/baz.py", 99, "attr-defined"),
    ]


def test_parser_skips_notes_and_summary():
    """``note:`` lines and summary lines must NOT be parsed as errors."""
    output = (
        "app/svc.py:10: error: Real error  [arg-type]\n"
        "app/svc.py:10: note: This is a hint, not an error\n"
        "app/svc.py:11: note:     Possible overload variants:\n"
        "Found 1 error in 1 file (checked 134 source files)\n"
        "Success: no issues found in 0 source files\n"
    )
    assert _parse_mypy_output(output) == [
        ("app/svc.py", 10, "arg-type"),
    ]


def test_parser_handles_error_code_with_hyphens():
    """Mypy codes use hyphenated names (arg-type, attr-defined, etc.)."""
    output = (
        "app/x.py:1: error: m  [attr-defined]\n"
        "app/x.py:2: error: m  [call-arg]\n"
        "app/x.py:3: error: m  [import-untyped]\n"
        "app/x.py:4: error: m  [valid-type]\n"
    )
    codes = [c for _, _, c in _parse_mypy_output(output)]
    assert codes == ["attr-defined", "call-arg", "import-untyped", "valid-type"]


def test_parser_returns_empty_on_clean_output():
    """No errors -- parser returns empty list."""
    output = (
        "Success: no issues found in 134 source files\n"
    )
    assert _parse_mypy_output(output) == []


# -----------------------------------------------------------------------------
# End-to-end self-test -- prove mypy actually catches a synthetic bad file.
# Skipped by default (it would dirty .mypy_cache); enabled via env var for
# manual verification.
# -----------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_MYPY_SELFTEST") != "1",
    reason="Heavy self-test -- set RUN_MYPY_SELFTEST=1 to enable.",
)
def test_mypy_subprocess_flags_synthetic_bad_file(tmp_path: pathlib.Path):
    """Synthetic broken file -- mypy must produce a parseable error.

    Mirrors the v2.17-WP02 / WP03 synthetic-bad case pattern. Runs mypy
    as a subprocess against an ad-hoc file; not part of the main gate
    because it would pollute the production-tree cache.
    """
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def f(x: int) -> int:\n"
        "    return x + 'not-an-int'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-color-output", str(bad)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    # mypy must flag the bad operator -- the error line shape is the same
    # as the production-tree gate.
    assert "error:" in proc.stdout, (
        f"mypy must flag synthetic-bad file; got stdout={proc.stdout!r}"
    )
