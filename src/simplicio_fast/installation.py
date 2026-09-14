"""Offline installation and artifact diagnostics for packaging/rollback."""

from __future__ import annotations

import hashlib
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
ENGINE_MANIFEST_SCHEMA = "simplicio.fast.engine-manifest/v1"
SMOKE_SCHEMA = "simplicio.fast.python-smoke/v1"


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rust_candidate() -> Path | None:
    configured = os.environ.get("SIMPLICIO_FAST_RUST")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_file() else None
    found = shutil.which("simplicio-fast-rs")
    return Path(found) if found else None


def _manifest(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        result = subprocess.run(
            [str(path), "--version", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, type(error).__name__
    if result.returncode != 0:
        return None, f"returncode:{result.returncode}"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "manifest_not_object"
    if value.get("schema") != ENGINE_MANIFEST_SCHEMA:
        return None, "manifest_schema_mismatch"
    if value.get("engine") != "rust":
        return None, "manifest_engine_mismatch"
    if value.get("status") != "available":
        return None, "manifest_not_available"
    version = value.get("version")
    if not isinstance(version, str) or not version.strip():
        return None, "manifest_version_missing"
    if version != __version__:
        return None, "manifest_version_mismatch"
    return value, None


def report() -> dict[str, Any]:
    rust = _rust_candidate()
    rust_manifest = None
    rust_reason = "artifact_missing"
    if rust:
        rust_manifest, rust_reason = _manifest(rust)
        if rust_manifest is not None:
            rust_reason = None
    rust_status = "pass" if rust_manifest else ("info" if rust is None else "fail")
    overall_status = "ready" if rust_status != "fail" else "degraded"
    if rust_manifest is not None:
        selected_engine = "rust"
        resolution_reason = "rust_manifest_available"
    elif rust is None:
        selected_engine = "python"
        resolution_reason = "rust_artifact_missing"
    else:
        selected_engine = "python"
        resolution_reason = f"rust_artifact_unusable:{rust_reason}"
    checks = [
        {"name": "python_package", "status": "pass", "version": __version__},
        {"name": "python_only_path", "status": "pass", "detail": "supported"},
        {
            "name": "rust_artifact",
            "status": rust_status,
            "path": str(rust) if rust else None,
            "sha256": _digest(rust) if rust else None,
            "manifest": rust_manifest,
            "reason": rust_reason,
        },
        {
            "name": "offline_resolution",
            "status": "pass",
            "detail": "no download performed",
        },
    ]
    return {
        "schema": SCHEMA,
        "status": overall_status,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "package": {"name": "simplicio-fast", "version": __version__},
        "resolution": {
            "requested_engine": "auto",
            "selected_engine": selected_engine,
            "reason_code": resolution_reason,
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
    engine: str,
    arguments: list[str],
    *,
    root: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    command = [*launcher, "--fast-engine", engine, *arguments]
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
                "engine": engine,
                "command": command,
                "reason_code": type(error).__name__,
                "error": str(error),
                "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
            }
    except subprocess.TimeoutExpired as error:
        return {
            "status": "fail",
            "engine": engine,
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
            "engine": engine,
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
        "engine": engine,
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
        environment["SIMPLICIO_FAST_RUST"] = str(root / "missing-rust-engine.exe")

        for engine in ("auto", "python", "off"):
            steps.append(
                _smoke_step(
                    launcher,
                    engine,
                    ["capabilities"],
                    root=root,
                    environment=environment,
                )
            )
        steps.append(
            _smoke_step(
                launcher,
                "auto",
                ["build", ".", "--output", str(snapshot), "--mapper-mode", "bootstrap"],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                "python",
                ["query", "greeting", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                "python",
                ["context", "greeting", "--root", ".", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )
        steps.append(
            _smoke_step(
                launcher,
                "python",
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
                "python",
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
                "python",
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
                "off",
                ["query", "farewell", "--snapshot", str(snapshot)],
                root=root,
                environment=environment,
            )
        )

    expected_selection = {"auto": "python", "python": "python", "off": "off"}
    capability_steps = steps[:3]
    observed_selection: dict[str, str | None] = {}
    for requested, step in zip(expected_selection, capability_steps):
        payload = step.get("payload")
        receipt = payload.get("engine") if isinstance(payload, dict) else None
        observed_selection[requested] = (
            receipt.get("selected") if isinstance(receipt, dict) else None
        )
    selection_ok = observed_selection == expected_selection
    failed = [step for step in steps if step["status"] != "pass"]
    all_checks_pass = not failed and selection_ok
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
    if not selection_ok:
        reason_codes.append("engine_selection_contract_failed")
    return {
        "schema": SMOKE_SCHEMA,
        "status": status,
        "launcher": {"kind": launcher_kind, "reason_code": launcher_reason},
        "engines": ["auto", "python", "off"],
        "engine_selection": observed_selection,
        "rust_probe": {
            "forced_unavailable": True,
            "reason_code": "rust_artifact_missing",
        },
        "steps": steps,
        "reason_codes": reason_codes,
        "checks": {
            "build_refresh_query_context_plan_delivery": not failed,
            "python_fallback": selection_ok,
            "rust_not_loaded": selection_ok
            and all(value != "rust" for value in observed_selection.values()),
        },
    }
