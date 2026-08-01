#!/usr/bin/env python3
"""Run the quality-gate pytest lane with an isolated temporary directory."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix="simplicio-quality-pytest-") as raw_basetemp:
        command = [
            sys.executable,
            "-m",
            "pytest",
            "--timeout=30",
            "--basetemp",
            raw_basetemp,
            "--cov=simplicio",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
        ]
        if shutil.which("simplicio-mapper") is None or shutil.which("simplicio-dev-cli") is None:
            command.extend(
                [
                    "--ignore=tests/contracts/test_real_cli_mapper_e2e.py",
                    "--ignore=tests/contracts/test_real_cli_project_scenarios_e2e.py",
                ]
            )
        return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
