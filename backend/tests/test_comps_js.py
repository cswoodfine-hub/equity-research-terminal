"""The Comps valuation view's JavaScript tests, run from pytest so ``make verify`` gates them.

``core.js`` decides every number and sentence the view shows, and its tests live beside
their fixtures in ``frontend/tests/compsval`` (outside the served component folder). They
run under ``node --test``; this shim runs them from the repository root and fails with
node's own report. A machine without node skips it rather than failing the suite.

The path is a glob string, not a bare directory: ``node --test dir/`` fails in Node 24,
while a quoted glob is expanded by node itself.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
TESTS = "frontend/tests/compsval/*.test.js"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_compsval_core_js():
    assert list(ROOT.glob(TESTS)), f"no JavaScript tests match {TESTS}"
    result = subprocess.run([NODE, "--test", TESTS], cwd=ROOT, capture_output=True,
                            text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
