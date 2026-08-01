#!/usr/bin/env python3
"""Run the quality-gate pytest lane with an isolated temporary directory."""

from __future__ import annotations

import argparse
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
            "--basetemp",
            raw_basetemp,
            "--cov=simplicio",
            "--cov-report=json:coverage.json",
            "--cov-report=term-missing",
        ]
        return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
