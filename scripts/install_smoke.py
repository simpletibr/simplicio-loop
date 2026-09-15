#!/usr/bin/env python3
"""Local, clean-room install smoke for the built wheel (#292 Fase 7, partial).

Scope and honest limits
------------------------
Issue #292 Fase 7 wants a clean-room install smoke against the REAL PyPI index, the REAL npm
registry, and a REAL GitHub Release download, each in an isolated environment with no repo
checkout on `PYTHONPATH`. That requires an actual publish step. This repo does not currently
publish anywhere from this environment: `.github/workflows/` was removed in PR #311 (GitHub
Actions billing lockout) and no OIDC-capable CI substrate has replaced it (see
docs/SUPPLY_CHAIN.md). Faking a "PyPI install smoke" against an index this run never published to
would be exactly the kind of fabricated proof issue #292 itself is complaining about, so this
script does not attempt it.

What this script DOES do, for real:

  * builds a real wheel locally (`python -m build --wheel --no-isolation`, no network required
    beyond what's already installed);
  * creates a fresh, disposable virtualenv with `venv` (nothing inherited from the repo's
    `sys.path`/`PYTHONPATH`);
  * installs ONLY that wheel into it with `--no-deps` (this repo's runtime dependencies,
    including `simplicio-cli` and `simplicio-mapper`, are not vendored/available offline;
    `--no-deps` is
    called out explicitly in the receipt so nobody mistakes this for a full dependency-closure
    smoke);
  * inside that clean venv, confirms `importlib.metadata.version("simplicio-loop")` matches the
    expected version and that the installed module file lives under the venv's site-packages
    (not the repo checkout);
  * runs the `simplicio-loop` console-script entrypoint and records its exit code;
  * writes a JSON receipt: command, exit code, python/venv path, artifact digest, version
    observed, and a `scope` field stating plainly this is a *local build* smoke, not a
    *registry* smoke.

This is the honest, currently-achievable subset of Fase 7. The registry-specific parts (PyPI,
npm, GitHub Release clean installs) remain blocked until a publish pipeline exists again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "simplicio.install-smoke/v1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_wheel(repo: Path, dist_dir: Path) -> Dict[str, Any]:
    dist_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist_dir)]
    result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    wheels = sorted(dist_dir.glob("*.whl"))
    return {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stderr_tail": result.stderr.strip().splitlines()[-10:] if result.stderr else [],
        "wheel": str(wheels[-1]) if wheels else None,
        "ok": result.returncode == 0 and bool(wheels),
    }


def run_smoke(
    repo: Path,
    *,
    expected_version: Optional[str],
    keep: bool,
    wheel_path: Optional[Path] = None,
) -> Dict[str, Any]:
    repo = repo.resolve()
    workdir = Path(tempfile.mkdtemp(prefix="simplicio-install-smoke-"))
    receipt: Dict[str, Any] = {
        "schema": SCHEMA,
        "scope": "local-build-only (no PyPI/npm/GitHub-Release publish exists to smoke against; "
                 "see docs/SUPPLY_CHAIN.md)",
        "workdir": str(workdir),
    }
    try:
        if wheel_path is not None:
            resolved_wheel = Path(wheel_path).resolve()
            receipt["build"] = {"wheel": str(resolved_wheel), "ok": True, "reused_prebuilt_wheel": True}
            wheel_path_to_install = resolved_wheel
        else:
            dist_dir = workdir / "dist"
            build = build_wheel(repo, dist_dir)
            receipt["build"] = build
            if not build["ok"]:
                receipt["ok"] = False
                receipt["reason_code"] = "build_failed"
                return receipt
            wheel_path_to_install = Path(build["wheel"])
        receipt["artifact"] = {
            "name": wheel_path_to_install.name,
            "sha256": _sha256(wheel_path_to_install),
            "size": wheel_path_to_install.stat().st_size,
        }
        wheel_path = wheel_path_to_install

        venv_dir = workdir / "venv"
        # Deliberately shell out to `python -m venv` (with an explicit stdin=DEVNULL) rather than
        # call `venv.EnvBuilder(...).create()` in-process: the latter internally spawns its own
        # subprocess for `ensurepip` and inherits this process's stdin handle, which can be
        # invalid/broken under some captured test-runner environments (observed under pytest on
        # Windows) and crashes with WinError 6 — a test-harness artifact unrelated to the smoke
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        venv_cmd = [sys.executable, "-m", "venv", "--clear", str(venv_dir)]
        venv_result = subprocess.run(venv_cmd, capture_output=True, text=True, cwd=str(workdir), env=env, stdin=subprocess.DEVNULL)
        receipt["venv_create"] = {"command": " ".join(venv_cmd), "returncode": venv_result.returncode,
                                   "stderr_tail": venv_result.stderr.strip().splitlines()[-10:] if venv_result.stderr else []}
        if venv_result.returncode != 0:
            receipt["ok"] = False
            receipt["reason_code"] = "venv_create_failed"
            return receipt
        venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        install_cmd = [str(venv_python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel_path)]
        install = subprocess.run(install_cmd, capture_output=True, text=True, cwd=str(workdir), env=env, stdin=subprocess.DEVNULL)
        receipt["install"] = {
            "command": " ".join(install_cmd),
            "returncode": install.returncode,
            "stderr_tail": install.stderr.strip().splitlines()[-10:] if install.stderr else [],
            "ok": install.returncode == 0,
            "no_deps": True,
        }
        if install.returncode != 0:
            receipt["ok"] = False
            receipt["reason_code"] = "install_failed"
            return receipt

        # Clean-room provenance check: importlib.metadata.version + module file location, run
        # with no repo path on PYTHONPATH so it cannot silently import the checkout instead.
        probe_script = (
            "import importlib.metadata as m, simplicio_loop, json, sys\n"
            "print(json.dumps({"
            "'version': m.version('simplicio-loop'), "
            "'module_file': simplicio_loop.__file__"
            "}))"
        )
        probe = subprocess.run([str(venv_python), "-c", probe_script], capture_output=True, text=True,
                                cwd=str(workdir), env=env, stdin=subprocess.DEVNULL)
        receipt["probe"] = {
            "returncode": probe.returncode,
            "stdout": probe.stdout.strip(),
            "stderr_tail": probe.stderr.strip().splitlines()[-10:] if probe.stderr else [],
        }
        if probe.returncode != 0:
            receipt["ok"] = False
            receipt["reason_code"] = "probe_failed"
            return receipt
        probe_data = json.loads(probe.stdout.strip())
        observed_version = probe_data.get("version")
        module_file = probe_data.get("module_file", "")
        from_repo = str(repo) in module_file
        version_ok = expected_version is None or observed_version == expected_version
        receipt["observed_version"] = observed_version
        receipt["module_file"] = module_file
        receipt["module_from_repo_checkout"] = from_repo

        # Actually RUN the installed `simplicio-loop` console-script entrypoint (not just import
        # the module) so `--help` is real, asserted output from the clean-room install — #293 §6
        # ("executar simplicio-loop --help"), not a parse-only or import-only proxy for it.
        console_script = venv_dir / ("Scripts/simplicio-loop.exe" if os.name == "nt"
                                     else "bin/simplicio-loop")
        if console_script.exists():
            help_run = subprocess.run([str(console_script), "--help"], capture_output=True,
                                      text=True, cwd=str(workdir), env=env,
                                      stdin=subprocess.DEVNULL, timeout=30)
            receipt["cli_help"] = {
                "command": "%s --help" % console_script.name,
                "returncode": help_run.returncode,
                "stdout_tail": help_run.stdout.strip().splitlines()[-15:] if help_run.stdout else [],
                "ok": help_run.returncode == 0 and "usage" in help_run.stdout.lower(),
            }
        else:
            receipt["cli_help"] = {"ok": False, "reason": "console_script_not_found",
                                   "expected_path": str(console_script)}

        isolation_and_version_ok = (not from_repo) and version_ok
        receipt["ok"] = isolation_and_version_ok and receipt["cli_help"]["ok"]
        if not receipt["ok"]:
            receipt["reason_code"] = ("version_or_isolation_mismatch" if not isolation_and_version_ok
                                      else "cli_help_failed")
        return receipt
    finally:
        if keep:
            receipt["kept_workdir"] = True
        else:
            shutil.rmtree(workdir, ignore_errors=True)
            receipt.pop("workdir", None)


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_smoke(Path(args.repo), expected_version=args.expected_version, keep=args.keep)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=None if args.json else 2))
    return 0 if result.get("ok") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="install_smoke", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="build a wheel locally and clean-room install-smoke it")
    p_run.add_argument("--repo", default=".")
    p_run.add_argument("--expected-version", default=None)
    p_run.add_argument("--keep", action="store_true", help="keep the temp workdir for inspection")
    p_run.add_argument("--json", action="store_true")
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
