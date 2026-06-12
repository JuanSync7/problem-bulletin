"""v2.16-WP02 (Z1) — SyntaxWarning regression lint for ``app/``.

Background
----------
v2.15-WP01 baseline surfaced a ``SyntaxWarning: invalid escape sequence '\\)'``
at ``app/services/search_multi.py:119`` — a docstring containing ``\\)`` inside
a non-raw string literal. Python 3.12+ emits a SyntaxWarning at compile time
for unrecognised escape sequences; Python 3.13+ promotes this to SyntaxError
under ``-W error::SyntaxWarning``. Test runs that capture output (CI, tox)
get noisy stderr; future Python versions break import outright.

Scope
-----
- ``test_app_import_under_werror`` — subprocess-imports ``app`` under
  ``-W error::SyntaxWarning``. RED before fix, GREEN after.
- ``test_all_app_submodules_import_under_werror`` — walks every submodule
  under ``app.`` via ``pkgutil.walk_packages`` and imports each, still under
  ``-W error::SyntaxWarning``. Catches escape issues in lazily-imported leaves.
- ``test_helper_catches_synthetic_bad_module`` — self-test: writes ``\\)``
  into a tmp module file, runs the same werror-import recipe, asserts the
  helper detects it. Guards against the regression test silently passing.

Lessons-pin
-----------
This is the v2.16-WP02 regression-lint surface. Pairs with the production
fix at ``app/services/search_multi.py``; together they enforce that no
docstring or string literal in ``app/`` carries an invalid escape sequence.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _run_werror_import(code: str, extra_path: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``code`` under ``python -W error::SyntaxWarning`` in a subprocess.

    Kept lean — single short subprocess call, no heavy imports beyond what
    the code snippet itself triggers.
    """
    env_path = extra_path
    cmd = [sys.executable, "-W", "error::SyntaxWarning", "-c", code]
    cwd = env_path if env_path else None
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


def test_app_import_under_werror() -> None:
    """``import app`` must not emit SyntaxWarning."""
    result = _run_werror_import("import app")
    assert result.returncode == 0, (
        f"`import app` raised SyntaxWarning under -W error::SyntaxWarning.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_all_app_submodules_import_under_werror() -> None:
    """Every submodule under ``app.`` must import cleanly under -W error::SyntaxWarning.

    Uses ``pkgutil.walk_packages`` to enumerate. Skips modules that raise
    ImportError for unrelated reasons (missing optional deps) but FAILS
    loudly on any SyntaxWarning/SyntaxError.
    """
    code = textwrap.dedent(
        """
        import pkgutil
        import importlib
        import sys
        import warnings

        warnings.simplefilter('error', SyntaxWarning)

        import app
        failures = []
        for mod in pkgutil.walk_packages(app.__path__, prefix='app.'):
            try:
                importlib.import_module(mod.name)
            except SyntaxWarning as e:
                failures.append(f'{mod.name}: SyntaxWarning: {e}')
            except SyntaxError as e:
                # -W error promotes SyntaxWarning to SyntaxError at compile
                if 'invalid escape sequence' in str(e):
                    failures.append(f'{mod.name}: {e}')
                # other SyntaxErrors are real bugs — surface them too
                else:
                    failures.append(f'{mod.name}: SyntaxError: {e}')
            except Exception:
                # unrelated import failures (missing optional dep, etc.) — skip
                pass

        if failures:
            print('SYNTAXWARNING_FAILURES:')
            for f in failures:
                print(f)
            sys.exit(1)
        """
    )
    result = _run_werror_import(code)
    assert result.returncode == 0, (
        f"SyntaxWarning detected walking app.* submodules.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_helper_catches_synthetic_bad_module(tmp_path: Path) -> None:
    """Self-test: a module with ``\\)`` in a docstring MUST be caught.

    Writes a tiny package to ``tmp_path``, runs the same werror-import
    recipe, asserts it surfaces as failure. Guards against the regression
    test silently passing if the recipe regresses.
    """
    pkg = tmp_path / "bad_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    # Deliberately use a docstring with an invalid escape '\)'.
    (pkg / "bad_mod.py").write_text('"""bad escape (\\) here."""\n')

    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(tmp_path)!r})
        import warnings
        warnings.simplefilter('error', SyntaxWarning)
        try:
            import bad_pkg.bad_mod  # noqa: F401
        except (SyntaxWarning, SyntaxError) as e:
            if 'invalid escape sequence' in str(e):
                print('CAUGHT')
                sys.exit(0)
            raise
        sys.exit(2)  # not caught — recipe is broken
        """
    )
    result = _run_werror_import(code)
    assert result.returncode == 0 and "CAUGHT" in result.stdout, (
        f"Self-test failed — helper did NOT catch synthetic bad escape.\n"
        f"returncode={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
