#!/usr/bin/env python3
"""Run the real installed Dev CLI/Loop consumer boundary against a Mapper wheel.

This harness is intentionally opt-in and requires sibling source checkouts.  It
does not use an in-tree Python import as a substitute for the installed
consumer: every command runs from a temporary system-site-packages venv with
the Mapper wheel installed first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.installed-consumer-e2e/v1"
ROOT = Path(__file__).resolve().parents[1]


def _run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, check=False, env=env)


def _python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _script(venv: Path, name: str) -> Path:
    return venv / (f"Scripts/{name}.exe" if os.name == "nt" else f"bin/{name}")


def _last_json_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("consumer output did not contain a JSON object")


def _mapper_version(py: Path) -> str:
    return _package_version(py, "simplicio-mapper")


def _package_version(py: Path, package: str) -> str:
    probe = _run(
        [str(py), "-c", f"from importlib.metadata import version; print(version({package!r}))"],
        cwd=ROOT,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or f"could not read installed package version: {package}")
    return probe.stdout.strip()


def _loop_probe_code(root: Path, run_root: Path) -> str:
    return (
        "from pathlib import Path; "
        "from simplicio_loop.runner import _run_mapper; "
        f"payload=_run_mapper(Path({str(root)!r}), Path({str(run_root)!r}), "
        "goal='inspect the installed Mapper consumer fixture', "
        "target_hint='src/app.py', task_fingerprint='installed-loop-e2e'); "
        "import json; "
        "print(json.dumps({'schema': payload.get('schema'), "
        "'handoff_schema': ((payload.get('handoff') or {}).get('stdout') or {}).get('schema')}))"
    )


def run(
    *,
    wheel: Path,
    dev_cli_root: Path,
    loop_root: Path,
    out: Path,
    venv: Path,
    repo_root: Path | None = None,
    dev_cli_wheel: Path | None = None,
    loop_wheel: Path | None = None,
) -> dict[str, Any]:
    for path, label in ((wheel, "wheel"), (dev_cli_root, "Dev CLI checkout"), (loop_root, "Loop checkout")):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    if venv.exists():
        shutil.rmtree(venv)
    create = _run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], cwd=ROOT)
    if create.returncode != 0:
        raise RuntimeError(create.stdout + create.stderr)
    py = _python(venv)
    install_mapper = _run([str(py), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], cwd=ROOT)
    if install_mapper.returncode != 0:
        raise RuntimeError(install_mapper.stdout + install_mapper.stderr)
    dev_cli_source = str(dev_cli_wheel or dev_cli_root)
    install_dev_cli = _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--no-deps",
            *([] if dev_cli_wheel else ["--no-build-isolation"]),
            dev_cli_source,
        ],
        cwd=ROOT,
    )
    if install_dev_cli.returncode != 0:
        raise RuntimeError(install_dev_cli.stdout + install_dev_cli.stderr)
    loop_source = str(loop_wheel or loop_root)
    install_loop = _run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--no-deps",
            *([] if loop_wheel else ["--no-build-isolation"]),
            loop_source,
        ],
        cwd=ROOT,
    )
    if install_loop.returncode != 0:
        raise RuntimeError(install_loop.stdout + install_loop.stderr)

    if repo_root is None:
        repo_root = Path(tempfile.mkdtemp(prefix="mapper-consumer-repo-"))
        source = repo_root / "src" / "app.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def greet(name: str) -> str:\n    return f'hello {name}'\n", encoding="utf-8")
    repo_root = repo_root.resolve()
    dev_cli = _script(venv, "simplicio-dev-cli")
    inspect = _run(
        [
            str(dev_cli),
            "inspect",
            "src/app.py",
            "--root",
            str(repo_root),
            "--goal",
            "inspect the installed Mapper consumer fixture",
            "--json",
        ],
        cwd=venv,
    )
    dev_payload = _last_json_line(inspect.stdout) if inspect.returncode == 0 else {}

    run_root = Path(tempfile.mkdtemp(prefix="mapper-installed-loop-"))
    loop_probe = _run([str(py), "-c", _loop_probe_code(repo_root, run_root)], cwd=venv)
    loop_payload = _last_json_line(loop_probe.stdout) if loop_probe.returncode == 0 else {}

    receipt = {
        "schema": SCHEMA,
        "status": "pass" if inspect.returncode == 0 and loop_probe.returncode == 0 else "fail",
        "mapper_version": _mapper_version(py),
        "measurement_status": "MEASURED",
        "consumer_repo": "temporary-fixture" if repo_root.name.startswith("mapper-consumer-repo-") else str(repo_root),
        "dev_cli": {
            "version": _package_version(py, "simplicio-cli"),
            "returncode": inspect.returncode,
            "schema": dev_payload.get("schema"),
            "target": dev_payload.get("target"),
            "stdout_json": bool(dev_payload),
        },
        "loop": {
            "version": _package_version(py, "simplicio-loop"),
            "returncode": loop_probe.returncode,
            "mapper_context_exists": (run_root / "mapper-context.json").exists(),
            "schema": loop_payload.get("schema"),
            "handoff_schema": loop_payload.get("handoff_schema"),
        },
        "commands": {
            "dev_cli": "simplicio-dev-cli inspect <target> --root <mapper-root> --goal <goal> --json",
            "loop": "simplicio_loop.runner._run_mapper(<mapper-root>, <run-root>, target_hint=<target>)",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--dev-cli-root", type=Path, required=True)
    parser.add_argument("--loop-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--dev-cli-wheel", type=Path)
    parser.add_argument("--loop-wheel", type=Path)
    args = parser.parse_args(argv)
    receipt = run(
        wheel=args.wheel.resolve(),
        dev_cli_root=args.dev_cli_root.resolve(),
        loop_root=args.loop_root.resolve(),
        out=args.out.resolve(),
        venv=args.venv.resolve(),
        repo_root=args.repo_root.resolve() if args.repo_root else None,
        dev_cli_wheel=args.dev_cli_wheel.resolve() if args.dev_cli_wheel else None,
        loop_wheel=args.loop_wheel.resolve() if args.loop_wheel else None,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
