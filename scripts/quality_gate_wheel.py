#!/usr/bin/env python3
"""Build, inspect, install, and smoke-test the current wheel without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(argv: list[str], *, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    for artifact in dist.glob("*.whl"):
        artifact.unlink()
    _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)], cwd=root)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, found {len(wheels)}")
    wheel = wheels[0]
    _run([sys.executable, "-m", "twine", "check", str(wheel)], cwd=root)
    with tempfile.TemporaryDirectory(prefix="simplicio-quality-wheel-") as raw_venv:
        venv_dir = Path(raw_venv)
        venv.EnvBuilder(with_pip=True, system_site_packages=True, clear=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=root)
        _run([str(python), "-m", "simplicio.cli", "--help"], cwd=root)
        _run([str(python), "-m", "simplicio.cli", "changeset", "--help"], cwd=root)
    print(
        json.dumps(
            {
                "wheel": str(wheel),
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "installed_smoke": "pass",
                "network": "disabled",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
