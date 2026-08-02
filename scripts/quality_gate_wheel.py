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


def _run_capture(argv: list[str], *, cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"installed command failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}"
        )
    return result.stdout


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
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)],
            cwd=root,
        )
        with tempfile.TemporaryDirectory(prefix="simplicio-quality-installed-") as raw_smoke:
            smoke_root = Path(raw_smoke)
            module_path = _run_capture(
                [str(python), "-c", "import simplicio; print(simplicio.__file__)"], cwd=smoke_root
            ).strip()
            if root.as_posix().lower() in Path(module_path).resolve().as_posix().lower():
                raise RuntimeError(f"installed smoke imported checkout instead of wheel: {module_path}")
            _run([str(python), "-m", "simplicio.cli", "--help"], cwd=smoke_root)
            _run([str(python), "-m", "simplicio.cli", "changeset", "--help"], cwd=smoke_root)
            plan = smoke_root / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "schema": "simplicio.fast.changeset/v2",
                        "changeset_id": "installed-quality-gate",
                        "correlation_id": "installed-quality-gate",
                        "generation": "installed-generation",
                        "allowlist": ["installed.txt"],
                        "operations": [
                            {"kind": "create", "path": "installed.txt", "content": "installed-smoke\n"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            command = [
                str(python),
                "-m",
                "simplicio.cli",
                "changeset",
                "--root",
                str(smoke_root),
                "--plan",
                str(plan),
                "--apply",
                "--json",
            ]
            first = json.loads(_run_capture(command, cwd=smoke_root))
            try:
                replay = json.loads(_run_capture(command, cwd=smoke_root))
            except RuntimeError as exc:
                raise RuntimeError(
                    f"installed replay smoke failed after first receipt {first}: {exc}"
                ) from exc
            if first.get("status") != "ok" or first.get("applied") is not True:
                raise RuntimeError(f"installed standalone smoke failed: {first}")
            if replay.get("status") != "ok" or replay.get("replayed") is not True:
                raise RuntimeError(f"installed replay smoke failed: {replay}")
            if (smoke_root / "installed.txt").read_text(encoding="utf-8") != "installed-smoke\n":
                raise RuntimeError("installed standalone smoke wrote unexpected content")
            memory_root = smoke_root / "memory"
            memory_backup = smoke_root / "memory-backup"
            restored_memory = smoke_root / "memory-restored"
            memory_command = [str(python), "-m", "simplicio.cli", "memory"]
            _run_capture(
                [*memory_command, "init", "--dir", str(memory_root), "--json"], cwd=smoke_root
            )
            _run_capture(
                [
                    *memory_command,
                    "store",
                    "installed-memory",
                    "installed-memory-smoke",
                    "--dir",
                    str(memory_root),
                    "--json",
                ],
                cwd=smoke_root,
            )
            memory_validation = json.loads(
                _run_capture(
                    [*memory_command, "validate", "--dir", str(memory_root), "--json"], cwd=smoke_root
                )
            )
            if memory_validation.get("ok") is not True:
                raise RuntimeError(f"installed memory validation failed: {memory_validation}")
            _run_capture(
                [
                    *memory_command,
                    "backup",
                    "--dir",
                    str(memory_root),
                    "--output",
                    str(memory_backup),
                    "--json",
                ],
                cwd=smoke_root,
            )
            restore = json.loads(
                _run_capture(
                    [
                        *memory_command,
                        "restore",
                        "--dir",
                        str(restored_memory),
                        "--backup",
                        str(memory_backup),
                        "--apply",
                        "--json",
                    ],
                    cwd=smoke_root,
                )
            )
            if restore.get("status") != "ok":
                raise RuntimeError(f"installed memory restore failed: {restore}")
    print(
        json.dumps(
            {
                "wheel": str(wheel),
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "installed_smoke": "pass",
                "installed_module": module_path,
                "installed_standalone": "pass",
                "installed_replay": "pass",
                "installed_memory": "pass",
                "network": "disabled",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
