#!/usr/bin/env python3
"""Run and persist the local, SHA-bound quality gate (issue #421).

The receipt is deliberately boring: every command has an exit code, duration,
and bounded output digest. A dirty checkout, missing command, or failed step is
never converted into a green result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.dev-cli.quality-gate-receipt/v1"
DEFAULT_RECEIPT = Path(".simplicio/quality-gate-receipt.json")
QUALITY_GATE_ENV_EXCLUSIONS = ("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY",)
QUALITY_GATE_ENV_EXCLUSION_PREFIXES = ("SIMPLICIO_",)
QUALITY_GATE_ENV_OVERRIDES: dict[str, str] = {}
EXTERNAL_E2E_REPORT_ENV = "SIMPLICIO_QUALITY_GATE_E2E_REPORT"
_SECRET_OUTPUT_PATTERNS = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*([^\s,;]+)"),
        r"\1=[REDACTED]",
    ),
)


def _quality_gate_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in QUALITY_GATE_ENV_EXCLUSIONS
        and not any(key.startswith(prefix) for prefix in QUALITY_GATE_ENV_EXCLUSION_PREFIXES)
    }
    path_entries = []
    for entry in env.get("PATH", "").split(os.pathsep):
        directory = Path(entry)
        native_names = ("simplicio.exe", "simplicio.cmd", "simplicio")
        if any((directory / name).is_file() for name in native_names):
            continue
        path_entries.append(entry)
    env["PATH"] = os.pathsep.join(path_entries)
    env.update(QUALITY_GATE_ENV_OVERRIDES)
    return env


def _tool_argv(name: str, *args: str) -> list[str]:
    """Prefer the installed tool entry point over an unrelated Python runtime."""
    executable = shutil.which(name)
    if executable is not None:
        return [executable, *args]
    return [sys.executable, "-m", name, *args]


DEFAULT_COMMANDS = (
    (
        "json-boundaries",
        [sys.executable, "scripts/check_json_boundaries.py", "--strict"],
    ),
    ("ruff", _tool_argv("ruff", "check", "simplicio")),
    ("ruff-format", _tool_argv("ruff", "format", "--check", "simplicio", "tests")),
    ("mypy", _tool_argv("mypy", "simplicio")),
    (
        "pytest",
        [
            sys.executable,
            "scripts/quality_gate_pytest.py",
            "--root",
            ".",
        ],
    ),
    ("coverage-gate", [sys.executable, "scripts/coverage_gate.py"]),
    (
        "token-budget",
        [sys.executable, "scripts/token_budget.py", "--check"],
    ),
    (
        "generated-docs",
        [sys.executable, "scripts/gen_package_interdependence.py", "--check"],
    ),
    (
        "wheel-and-installed-smoke",
        [sys.executable, "scripts/quality_gate_wheel.py", "--root", "."],
    ),
    (
        "mapper-installed-matrix",
        [sys.executable, "scripts/quality_gate_mapper_matrix.py", "--root", "."],
    ),
    ("cli-help", [sys.executable, "-m", "simplicio.cli", "--help"]),
    ("changeset-help", [sys.executable, "-m", "simplicio.cli", "changeset", "--help"]),
)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _redact_output(text: str) -> str:
    """Remove common credential-shaped values while retaining diagnostics."""

    redacted = text
    for pattern, replacement in _SECRET_OUTPUT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _redact_argv(command: list[str]) -> list[str]:
    return [_redact_output(argument) for argument in command]


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in ("simplicio-dev-cli", "pytest", "ruff", "mypy", "coverage", "build", "twine"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def _external_lane_matrix(root: Path, commit_sha: str | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Represent lanes not owned by this local gate without fake metrics."""
    lanes = {
        "windows": {
            "status": "UNVERIFIED" if platform.system() == "Windows" else "UNAVAILABLE",
            "value": None,
            "reason": (
                "windows_locked_file_external_e2e_requires_installed_evidence"
                if platform.system() == "Windows"
                else "windows_lane_requires_a_real_Windows_host"
            ),
        },
        "runtime": {
            "status": "UNVERIFIED",
            "value": None,
            "reason": "runtime_backed_E2E_requires_a_compatible_installed_capability",
        },
        "fast": {
            "status": "UNVERIFIED",
            "value": None,
            "reason": "Fast_Rust_Python_external_lanes_require_installed_producer_artifacts",
        },
    }
    report_value = os.environ.get(EXTERNAL_E2E_REPORT_ENV, "").strip()
    if not report_value:
        return lanes, None
    report = Path(report_value)
    if not report.is_absolute():
        report = root / report
    report_digest = None
    try:
        raw = report.read_bytes()
        report_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        reason = f"external_e2e_report_unreadable: {type(exc).__name__}"
        for lane in lanes.values():
            lane.update({"status": "FAIL", "value": False, "reason": reason})
        return lanes, report_digest
    if not isinstance(payload, dict) or payload.get("schema") != "simplicio.dev-cli.issue-422-evidence/v1":
        reason = "external_e2e_report_schema_invalid"
        for lane in lanes.values():
            lane.update({"status": "FAIL", "value": False, "reason": reason})
        return lanes, report_digest
    if not commit_sha or payload.get("commit_sha") != commit_sha:
        reason = "external_e2e_report_sha_stale"
        for lane in lanes.values():
            lane.update({"status": "FAIL", "value": False, "reason": reason})
        return lanes, report_digest
    scenarios = {
        row.get("scenario"): row
        for row in payload.get("scenarios", [])
        if isinstance(row, dict) and isinstance(row.get("scenario"), str)
    }
    mapping = {
        "windows": "windows_locked_file",
        "runtime": "runtime_backed",
        "fast": "fast_rust",
    }
    for lane_name, scenario_name in mapping.items():
        row = scenarios.get(scenario_name)
        if row is None:
            lanes[lane_name].update(
                {"status": "FAIL", "value": False, "reason": f"external_scenario_missing:{scenario_name}"}
            )
            continue
        status = row.get("status")
        if status == "PASS":
            lanes[lane_name].update({"status": "PASS", "value": True, "reason": None})
        elif status == "UNAVAILABLE":
            lanes[lane_name].update({"status": "UNAVAILABLE", "value": None, "reason": row.get("reason")})
        elif status in {"UNVERIFIED", "AVAILABLE_NOT_E2E"}:
            lanes[lane_name].update({"status": "UNVERIFIED", "value": None, "reason": row.get("reason")})
        else:
            lanes[lane_name].update({"status": "FAIL", "value": False, "reason": row.get("reason")})
    return lanes, report_digest


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        if callable(killpg) and callable(getpgid):
            killpg(getpgid(process.pid), sigkill)
        else:
            process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def _command_result(root: Path, name: str, command: list[str], *, timeout_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    try:
        launch: dict[str, Any] = {
            "cwd": root,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": _quality_gate_environment(),
            "close_fds": True,
        }
        if os.name == "nt":
            launch["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            launch["start_new_session"] = True
        process = subprocess.Popen(command, **launch)
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
            exit_code = process.returncode
            output = (stdout + stderr)[-32_768:]
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process)
            partial_stdout = exc.stdout or ""
            partial_stderr = exc.stderr or ""
            if isinstance(partial_stdout, bytes):
                partial_stdout = partial_stdout.decode(errors="replace")
            if isinstance(partial_stderr, bytes):
                partial_stderr = partial_stderr.decode(errors="replace")
            exit_code = 124
            output = (partial_stdout + partial_stderr)[-32_768:]
            error = f"TimeoutExpired: command exceeded {timeout_s:g}s; process tree terminated"
            return {
                "name": name,
                "argv": _redact_argv(command),
                "exit_code": exit_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "output_digest": _digest(output),
                "output_tail": _redact_output(output),
                "error": error,
            }
    except (OSError, subprocess.SubprocessError) as exc:
        exit_code = 127
        output = ""
        error = f"{type(exc).__name__}: {exc}"
    return {
        "name": name,
        "argv": _redact_argv(command),
        "exit_code": exit_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "output_digest": _digest(output),
        "output_tail": _redact_output(output),
        "error": error,
    }


def run_gate(
    root: Path,
    *,
    commands: list[tuple[str, list[str]]] | None = None,
    timeout_s: float = 800.0,
) -> dict[str, Any]:
    root = root.resolve()
    sha = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain")
    steps = [
        _command_result(root, name, argv, timeout_s=timeout_s) for name, argv in commands or DEFAULT_COMMANDS
    ]
    limitations: list[str] = []
    if platform.system() != "Windows":
        limitations.append("windows_lane_not_run_on_non_windows_host")
    else:
        limitations.append("runtime_and_fast_external_lanes_require_installed_capabilities")
    wheel_sha256 = None
    for step in steps:
        if step["name"] == "wheel-and-installed-smoke" and step["exit_code"] == 0:
            try:
                wheel_sha256 = json.loads(step["output_tail"].splitlines()[-1]).get("wheel_sha256")
            except (IndexError, json.JSONDecodeError, AttributeError):
                wheel_sha256 = None
    external_lanes, external_report_digest = _external_lane_matrix(root, sha)
    passed = (
        bool(sha)
        and not bool(dirty)
        and all(step["exit_code"] == 0 for step in steps)
        and not any(lane.get("status") == "FAIL" for lane in external_lanes.values())
    )
    return {
        "schema": SCHEMA,
        "receipt_version": 1,
        "passed": passed,
        "commit_sha": sha,
        "dirty": bool(dirty),
        "dirty_digest": _digest(dirty or ""),
        "root": str(root),
        "platform": platform.platform(),
        "python": sys.version,
        "dependencies": _versions(),
        "environment": {
            "excluded": list(QUALITY_GATE_ENV_EXCLUSIONS),
            "excluded_prefixes": list(QUALITY_GATE_ENV_EXCLUSION_PREFIXES),
            "overrides": dict(QUALITY_GATE_ENV_OVERRIDES),
        },
        "commands": steps,
        "limitations": limitations,
        "external_lanes": external_lanes,
        "external_e2e_report": external_report_digest,
        "artifacts": {
            "coverage_json": str(root / "coverage.json") if (root / "coverage.json").is_file() else None,
            "wheel_sha256": wheel_sha256,
        },
    }


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    output = dict(payload)
    output["receipt_digest"] = _digest(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_receipt(path: Path, root: Path) -> tuple[bool, str]:
    """Reject edited, truncated, stale, dirty, or failed receipts."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, "receipt_unreadable"
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return False, "receipt_schema_invalid"
    supplied = payload.get("receipt_digest")
    unsigned = dict(payload)
    unsigned.pop("receipt_digest", None)
    if not isinstance(supplied, str) or supplied != _digest(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
    ):
        return False, "receipt_digest_invalid"
    current_sha = _git(root.resolve(), "rev-parse", "HEAD")
    if not current_sha or current_sha != payload.get("commit_sha"):
        return False, "receipt_sha_stale"
    if payload.get("dirty") or _git(root.resolve(), "status", "--porcelain"):
        return False, "checkout_dirty"
    commands = payload.get("commands", [])
    external_lanes = payload.get("external_lanes", {})
    if not isinstance(commands, list) or any(
        not isinstance(step, dict) or step.get("exit_code") != 0 for step in commands
    ):
        return False, "gate_failed"
    if not isinstance(external_lanes, dict) or any(
        isinstance(lane, dict) and lane.get("status") == "FAIL" for lane in external_lanes.values()
    ):
        return False, "external_lane_failed"
    if payload.get("passed") is not True:
        return False, "gate_failed"
    return True, "verified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument(
        "--verify", action="store_true", help="verify an existing receipt against the current checkout"
    )
    parser.add_argument("--timeout", type=float, default=800.0, help="per-command timeout in seconds")
    parser.add_argument(
        "--command",
        action="append",
        metavar="NAME=ARGV",
        help="replace the default commands for deterministic harness tests; ARGV uses shell-like splitting",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    receipt_path = args.receipt if args.receipt.is_absolute() else args.root / args.receipt
    if args.verify:
        ok, reason = verify_receipt(receipt_path, args.root)
        print(json.dumps({"verified": ok, "reason": reason}, sort_keys=True))
        return 0 if ok else 1
    commands = None
    if args.command:
        commands = []
        for item in args.command:
            name, separator, raw = item.partition("=")
            if not separator or not name or not raw:
                parser.error("--command must use NAME=ARGV")
            commands.append((name, shlex.split(raw, posix=False)))
    receipt = run_gate(args.root, commands=commands, timeout_s=args.timeout)
    _write_receipt(receipt_path, receipt)
    print(
        json.dumps({key: receipt[key] for key in ("schema", "passed", "commit_sha", "dirty")}, sort_keys=True)
    )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
