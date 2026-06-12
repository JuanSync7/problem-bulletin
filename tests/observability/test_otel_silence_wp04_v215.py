"""v2.15-WP04 (C3): OTel test-mode noise regression test.

Baseline noise observed before this WP (verbatim patterns):

* ``ValueError: I/O operation on closed file`` — emitted by
  ``ConsoleMetricExporter.export`` via ``PeriodicExportingMetricReader``'s
  ticker thread firing after pytest has closed the captured stdout stream.
* ``failed to connect to all addresses ... localhost:4317 ... Connection
  refused`` — emitted by ``OTLPMetricExporter`` retrying against a
  non-existent collector when ``test_setup_otel_uses_otlp_when_endpoint_set``
  configures ``OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317``.

Both originate in the **metric** exporter's background thread (the span
exporter is batch-only and silent absent emitted spans). The fix swaps
``PeriodicExportingMetricReader`` for ``InMemoryMetricReader`` when running
under pytest (detected via ``PYTEST_CURRENT_TEST``), eliminating the
background thread and all metric-side I/O.

This regression test subprocess-invokes a small slice of the observability
tests that previously emitted the noise and asserts the patterns are absent
from captured stderr.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


_NOISE_PATTERNS = (
    "localhost:4317",
    "ConnectionRefused",
    "Connection refused",
    "I/O operation on closed",
)


def test_otel_setup_emits_no_stderr_noise_under_pytest():
    """Run the observability test module in a subprocess and assert stderr is clean.

    We invoke ``tests/observability/test_otel_init.py`` because that suite is
    the canonical surface that exercises both code paths (empty endpoint →
    Console; ``localhost:4317`` endpoint → OTLP) and is therefore the source
    of the v2.14/v2.15 baseline noise.
    """
    env = os.environ.copy()
    # Strip any inherited PYTEST_CURRENT_TEST so the child detects itself fresh.
    env.pop("PYTEST_CURRENT_TEST", None)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/observability/test_otel_init.py",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    combined = proc.stdout + "\n" + proc.stderr

    # Child must have passed — if it failed, the noise check is meaningless.
    assert proc.returncode == 0, (
        f"child pytest failed (rc={proc.returncode})\nstdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )

    found = [pat for pat in _NOISE_PATTERNS if pat in combined]
    assert not found, (
        f"OTel test-mode noise patterns leaked into stderr: {found}\n"
        f"--- combined output ---\n{combined}"
    )
