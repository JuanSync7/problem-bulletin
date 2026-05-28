"""
v2.11-WP12 / D3 — regression pin: the v1 deferral mechanism stays gone.

v2.10-WP07 deleted ``tests/_v1_deferred.py`` along with the
``pytest_collection_modifyitems`` skip-hook that consumed it. This file
pins three invariants so a future contributor cannot quietly revive
either half of the mechanism:

1. ``tests/_v1_deferred.py`` does not exist.
2. ``tests/conftest.py`` does not define ``pytest_collection_modifyitems``
   (confirmed both by source-substring check and by AST walk so a renamed
   import or aliased definition cannot slip past).
3. No ``conftest.py`` under ``tests/`` references the deleted module.

Future per-test deferral uses plain ``@pytest.mark.skip`` /
``@pytest.mark.xfail`` with an explicit ``reason=``. See
``.claude/lessons-learned/v2.11-wp12-diagnosis.md`` and the policy
statement appended to ``.claude/lessons-learned/ticketing-v2.11.md``.

Self-test (synthetic-bad case): the AST helper
``_defines_collection_modifyitems`` is exercised below against a synthetic
source string that DOES define the hook, to prove the detector is not
silently green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"


def _defines_collection_modifyitems(source: str) -> bool:
    """AST walk: True iff *source* defines a top-level or nested
    ``def pytest_collection_modifyitems(...)`` (sync or async)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "pytest_collection_modifyitems":
                return True
    return False


def test_v1_deferred_file_absent():
    """``tests/_v1_deferred.py`` must not exist (v2.10-WP07 deletion holds)."""
    path = _TESTS_DIR / "_v1_deferred.py"
    assert not path.exists(), (
        f"{path} reappeared; the v1 deferral manifest was deleted in "
        "v2.10-WP07 and must not be revived. Use @pytest.mark.skip / "
        "@pytest.mark.xfail with an explicit reason= for per-test deferral."
    )


def test_root_conftest_has_no_collection_modifyitems_hook():
    """``tests/conftest.py`` must not define ``pytest_collection_modifyitems``.

    Substring check covers the obvious case; the AST walk also catches
    nested or otherwise-formatted definitions that grep on the literal
    ``def pytest_collection_modifyitems`` would miss.
    """
    conftest = _TESTS_DIR / "conftest.py"
    assert conftest.exists(), "tests/conftest.py missing — repo layout changed"
    source = conftest.read_text()
    # The string can still appear inside a comment (it does — explaining the
    # v2.10-WP07 deletion). The load-bearing check is the AST one below.
    assert not _defines_collection_modifyitems(source), (
        "tests/conftest.py now defines pytest_collection_modifyitems; the "
        "v1 deselect-hook mechanism was removed in v2.10-WP07 and must not "
        "be revived. Use @pytest.mark.skip / @pytest.mark.xfail instead."
    )


def test_no_conftest_references_v1_deferred_module():
    """No conftest under ``tests/`` may import or reference the deleted module."""
    offenders: list[tuple[Path, int, str]] = []
    for conftest in _TESTS_DIR.rglob("conftest.py"):
        for lineno, line in enumerate(conftest.read_text().splitlines(), start=1):
            # Skip historical-context comment lines (allowed: explain the deletion).
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "_v1_deferred" in line:
                offenders.append((conftest, lineno, line.rstrip()))
    assert not offenders, (
        "conftest references to the deleted ``_v1_deferred`` module found "
        f"(non-comment lines): {offenders}"
    )


def test_ast_detector_self_test_synthetic_bad_case():
    """Synthetic-bad case: a source string that DOES define the hook must
    be detected. Guards the real assertion above against silent regression
    of the detector itself."""
    bad_source = (
        "import pytest\n"
        "def pytest_collection_modifyitems(config, items):\n"
        "    for item in items:\n"
        "        item.add_marker(pytest.mark.skip(reason='legacy'))\n"
    )
    assert _defines_collection_modifyitems(bad_source) is True

    good_source = (
        "import pytest\n"
        "# pytest_collection_modifyitems was removed in v2.10-WP07.\n"
        "def some_other_hook():\n"
        "    pass\n"
    )
    assert _defines_collection_modifyitems(good_source) is False


@pytest.mark.parametrize(
    "source,expected",
    [
        ("async def pytest_collection_modifyitems(): ...\n", True),
        (
            "class _NS:\n"
            "    def pytest_collection_modifyitems(self): ...\n",
            True,
        ),
        ("def some_unrelated_name(): ...\n", False),
    ],
)
def test_ast_detector_edge_cases(source: str, expected: bool):
    """Async-def and nested-def variants are caught; unrelated names are not."""
    assert _defines_collection_modifyitems(source) is expected
