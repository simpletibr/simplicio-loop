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
    parser.add_argument(
        "--pytest-timeout",
        type=int,
        default=120,
        help="per-test timeout in seconds; benchmark lanes need more than the historical 30s",
    )
    args = parser.parse_args(argv)
    if args.pytest_timeout <= 0:
        parser.error("--pytest-timeout must be positive")
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix="simplicio-quality-pytest-") as raw_basetemp:
        pytest_executable = shutil.which("pytest")
        command = [
            pytest_executable if pytest_executable is not None else sys.executable,
            *([] if pytest_executable is not None else ["-m"]),
            *([] if pytest_executable is not None else ["pytest"]),
            "--basetemp",
            raw_basetemp,
            "--cov=simplicio",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
        ]
        if pytest_executable is None:
            command.insert(3, f"--timeout={args.pytest_timeout}")
        else:
            probe = subprocess.run(
                [pytest_executable, "--help"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            if "--timeout" in probe.stdout:
                command.insert(1, f"--timeout={args.pytest_timeout}")
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
