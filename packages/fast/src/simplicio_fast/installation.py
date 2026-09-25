"""Offline installation diagnostics for packaging/rollback (Python-only)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from typing import Any

from . import __version__


SCHEMA = "simplicio.fast.installation/v1"
SMOKE_SCHEMA = "simplicio.fast.python-smoke/v1"


def report() -> dict[str, Any]:
    checks = [
        {"name": "python_package", "status": "pass", "version": __version__},
        {"name": "python_only_path", "status": "pass", "detail": "supported"},
        {
            "name": "offline_resolution",
            "status": "pass",
            "detail": "no download performed",
        },
    ]
    return {
        "schema": SCHEMA,
        "status": "ready",
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "package": {"name": "simplicio-fast", "version": __version__},
        "resolution": {
            "selected_engine": "python",
            "reason_code": "python_only",
            "offline": True,
        },
        "checks": checks,
        "rollback": {
            "supported": False,
            "reason": "packaging_matrix_not_yet_published",
        },
    }


def _smoke_launcher(environment: dict[str, str]) -> tuple[list[str], str, str | None]:
    candidate = shutil.which("simplicio-fast")
    if candidate:
        try:
            version = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                env=environment,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            version = None
        if (
            version is not None
            and version.returncode == 0
            and __version__ in version.stdout
        ):
            return [candidate], "installed-cli", None
        reason = "installed_cli_version_mismatch"
    else:
        reason = "installed_cli_missing"
    return [sys.executable, "-m", "simplicio_fast.cli"], "python-module", reason


def _smoke_step(
    launcher: list[str],
    arguments: list[str],
    *,
    root: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    command = [*launcher, *arguments]
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        # Windows can intermittently reject process startup during dense
        # test/release bursts (including WinError 6). Retry once without
        # handle inheritance; a persistent error remains fail-closed.
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                close_fds=False,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as retry_error:
            error = retry_error
        else:
            error = None
        if error is not None:
            return {
                "status": "fail",
                "command": command,
                "reason_code": type(error).__name__,
                "error": str(error),
                "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
            }
    except subprocess.TimeoutExpired as error:
        return {
            "status": "fail",
            "command": command,
            "reason_code": type(error).__name__,
            "error": str(error),
            "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
        }
    raw = completed.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "command": command,
            "returncode": completed.returncode,
            "reason_code": "invalid_json",
            "stderr": completed.stderr[-1_000:],
            "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
        }
    status = (
        "pass" if completed.returncode == 0 and isinstance(payload, dict) else "fail"
    )
    return {
        "status": status,
        "command": command,
        "returncode": completed.returncode,
        "schema": payload.get("schema") if isinstance(payload, dict) else None,
        "payload": payload,
        "stderr": completed.stderr[-1_000:],
        "reason_code": None if status == "pass" else "cli_nonzero",
        "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
    }


def python_smoke() -> dict[str, Any]:
    """Exercise the installed Python CLI on a disposable fixture."""
    environment = os.environ.copy()
    # Run an installed console entry point against this exact package tree.
    # This prevents a stale globally installed CLI from invalidating a source
    # checkout or a just-built wheel during the release gate.
    source_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source_root + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    launcher, launcher_kind, launcher_reason = _smoke_launcher(environment)
    steps: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="simplicio-fast-python-smoke-"
    ) as directory:
        root = Path(directory)
        source = root / "greetings.py"
        source.write_text(
            "def greeting(name: str) -> str:\n    return f'hello {name}'\n",
            encoding="utf-8",
        )
        snapshot = root / "project.sfast"
        environment = environment.copy()

        steps.append(
            _smoke_step(launcher, ["capabilities"], root=root, environment=environment)
        )
        steps.append(
            _smoke_step(
                launcher,
                ["build", ".", "--output", str(snapshot), "--mapper-mode", "bootstrap"],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                ["query", "greeting", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                ["context", "greeting", "--root", ".", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                [
                    "plan",
                    "review greeting",
                    "--root",
                    ".",
                    "--snapshot",
                    str(snapshot),
                    "--mapper-mode",
                    "bootstrap",
                ],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                [
                    "delivery",
                    "review greeting",
                    "--root",
                    ".",
                    "--snapshot",
                    str(snapshot),
                    "--profile",
                    "loop-standalone",
                    "--mapper-mode",
                    "bootstrap",
                ],
                root=root,
                environment=environment,
            )
        )
        source.write_text(
            "def greeting(name: str) -> str:\n    return f'hello {name}'\n\ndef farewell(name: str) -> str:\n    return f'bye {name}'\n",
            encoding="utf-8",
        )
        steps.append(
            _smoke_step(
                launcher,
                [
                    "refresh",
                    ".",
                    "--output",
                    str(snapshot),
                    "--mapper-mode",
                    "bootstrap",
                ],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                ["query", "farewell", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )

    failed = [step for step in steps if step["status"] != "pass"]
    all_checks_pass = not failed
    status = (
        "pass"
        if all_checks_pass and launcher_kind == "installed-cli"
        else "partial"
        if all_checks_pass
        else "fail"
    )
    reason_codes = []
    if launcher_reason:
        reason_codes.append(launcher_reason)
    if failed:
        reason_codes.append("python_cli_smoke_failed")
    return {
        "schema": SMOKE_SCHEMA,
        "status": status,
        "launcher": {"kind": launcher_kind, "reason_code": launcher_reason},
        "steps": steps,
        "reason_codes": reason_codes,
        "checks": {
            "build_refresh_query_context_plan_delivery": not failed,
        },
    }
