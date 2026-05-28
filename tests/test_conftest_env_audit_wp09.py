"""v2.11-WP09 (C6) — conftest ambient-environment audit lint.

Background
----------
``os.environ.setdefault("KEY", "value")`` at module scope in
``conftest.py`` sets a default for the WHOLE pytest session, *before*
any test imports the app. If a test later asserts on
"default-from-model" behaviour (i.e. that ``Settings()`` uses its
declared default for ``KEY``), the assertion silently sees the
conftest's value instead. v2.10-WP05 surfaced this exact bug class
for ``ENVIRONMENT`` / ``DEV_AUTH_BYPASS``.

Policy
------
Every ``os.environ.setdefault(...)`` under ``tests/conftest.py`` (and
any sub-conftests) must carry a same-line ``# load-bearing: <reason>``
comment. The annotation forces the author to explicitly classify why
the default is intentional — either:

- "no model default" — Settings has no fallback; conftest must supply
  one or app import crashes.
- "matches model default; <reason to pin>" — the value equals the
  Settings declared default but is asserted-on by tests that need it
  pinned regardless of what the model declares.
- "distinct from model default" — chosen for diagnostic value (e.g.
  surface ambient-env leakage).

If a future contributor adds a setdefault without the annotation, this
lint fails LOUD with ``file:line``. If a key's annotation needs to
change, that's a code-review conversation, not an automation one.

Lessons-pin
-----------
v2.11-WP09 (C6) regression-lint surface. Pairs with the diagnosis
table in ``.claude/lessons-learned/v2.11-wp09-diagnosis.md``.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.helpers.source_lint import (
    iter_calls,
    iter_source_files,
    parse_module,
)


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

# Same-line marker — case-insensitive substring match on the trailing
# comment is sufficient; the diagnosis table is the source of truth for
# the rationale, this lint only asserts an annotation exists.
_LOAD_BEARING_RE = re.compile(r"#\s*load-bearing\s*:", re.IGNORECASE)


def _iter_conftests() -> list[pathlib.Path]:
    # ``suffix="conftest.py"`` makes the helper glob ``*conftest.py``,
    # which under tests/ resolves to every conftest.py file.
    return list(iter_source_files(_TESTS_DIR, suffix="conftest.py"))


def _scan(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return ``(lineno, source_line)`` for every
    ``os.environ.setdefault(...)`` call missing a same-line
    ``# load-bearing: <reason>`` annotation.
    """
    offenders: list[tuple[int, str]] = []
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return offenders
    tree = parse_module(path)
    if tree is None:
        return offenders

    source_lines = source.splitlines()
    for node in iter_calls(tree, dotted_name="os.environ.setdefault"):
        # AST end_lineno gives us the closing-paren line; the annotation
        # convention is on that final line (single-line setdefault calls
        # are typical).
        end_line = node.end_lineno or node.lineno
        idx = end_line - 1
        if 0 <= idx < len(source_lines):
            line_text = source_lines[idx]
            if _LOAD_BEARING_RE.search(line_text):
                continue
        offenders.append((node.lineno, source_lines[node.lineno - 1] if 0 <= node.lineno - 1 < len(source_lines) else ""))
    return offenders


def test_conftest_env_setdefaults_are_annotated():
    """Every ``os.environ.setdefault(...)`` in a conftest file carries
    a same-line ``# load-bearing: <reason>`` annotation.

    Failure mode: a future PR adds an unjustified setdefault, masking
    a Settings model default and risking a v2.10-WP05-style silent-pass.
    """
    all_offenders: list[tuple[pathlib.Path, int, str]] = []
    for path in _iter_conftests():
        for ln, text in _scan(path):
            all_offenders.append((path, ln, text))

    if all_offenders:
        body = "\n".join(
            f"  {p.relative_to(_REPO_ROOT)}:{ln}: {text.strip()!r}"
            for p, ln, text in all_offenders
        )
        pytest.fail(
            "``os.environ.setdefault(...)`` in conftest missing same-line "
            "``# load-bearing: <reason>`` annotation. These ambient defaults "
            "mask Settings model defaults across the whole pytest session; "
            "annotate the rationale or remove the setdefault:\n" + body
        )


def test_conftest_env_audit_lint_detects_synthetic_bad(tmp_path: pathlib.Path):
    """Self-test: the scanner flags an un-annotated setdefault and
    accepts an annotated one.
    """
    bad = tmp_path / "conftest.py"
    bad.write_text(
        "import os\n"
        "os.environ.setdefault('FOO', 'bar')\n"
    )
    assert _scan(bad), "scanner should detect un-annotated setdefault"

    good = tmp_path / "good_conftest.py"
    good.write_text(
        "import os\n"
        "os.environ.setdefault('FOO', 'bar')  # load-bearing: needed for X\n"
    )
    assert not _scan(good), "scanner must accept annotated setdefault"

    # Different mechanism — patch.dict-style env writes use a context
    # manager and are scoped, so they must NOT be flagged. The scanner
    # only targets module-scope setdefault.
    other = tmp_path / "other_conftest.py"
    other.write_text(
        "import os\n"
        "def fixture():\n"
        "    os.environ['X'] = 'y'  # not a setdefault\n"
    )
    assert not _scan(other), (
        "scanner must only flag setdefault, not assignment"
    )
