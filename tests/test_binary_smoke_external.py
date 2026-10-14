"""Slow smoke test of a built standalone binary, outside the source tree (issue #1576).

Not part of the gate: it needs a binary that takes minutes to build. Build it, then run::

    SIMPLICIO_BINARY=dist/binary/simplicio-loop-v<version>-linux-x86_64 \\
    SIMPLICIO_BINARY_WHEEL=dist/simplicio_loop-<version>-py3-none-any.whl \\
    SIMPLICIO_BINARY_REFERENCE_BIN=/tmp/slb/bin \\
    python3 -m pytest tests/test_binary_smoke_external.py -p no:cacheprovider

The last two variables are optional. They add the comparison with the wheel install.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import smoke_binary  # noqa: E402


@pytest.mark.external_integration
def test_binary_runs_every_smoke_check_outside_the_source_tree(tmp_path):
    binary = os.environ.get("SIMPLICIO_BINARY")
    if not binary:
        pytest.skip("set SIMPLICIO_BINARY to a built binary")
    wheel = os.environ.get("SIMPLICIO_BINARY_WHEEL")
    reference = os.environ.get("SIMPLICIO_BINARY_REFERENCE_BIN")
    smoke = smoke_binary.Smoke(
        Path(binary).resolve(), tmp_path, Path(reference) if reference else None,
        Path(wheel) if wheel else None, None,
    )
    results = smoke.run_all()
    failed = [item for item in results if not item["ok"]]
    assert not failed, failed
