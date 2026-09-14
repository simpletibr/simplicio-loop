from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
DUPLICATE_TEST_PATHS = (
    "tests/python/test_execution_planner_calibration_434.py",
    "tests/python/unit/test_execution_planner_calibration_434.py",
    "tests/python/test_mapper_perf_gate.py",
    "tests/python/unit/test_mapper_perf_gate.py",
)


def test_pytest_collects_duplicate_basename_files_together() -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(fragment in name.upper() for fragment in ("OPENROUTER", "API_KEY", "API_TOKEN", "ACCESS_TOKEN"))
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *DUPLICATE_TEST_PATHS, "-q", "--collect-only"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for path in DUPLICATE_TEST_PATHS:
        assert path in output
