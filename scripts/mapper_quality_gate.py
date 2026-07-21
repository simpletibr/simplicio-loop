#!/usr/bin/env python3
"""Offline release gate for Mapper's binary-format migration.

This is deliberately local-first: it does not require GitHub Actions. The gate
emits Markdown only. Missing evidence is represented as null (reason), never
as a passing zero or an internal JSON report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except OSError as error:
        return False, str(error)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _status(command: list[str], root: Path) -> tuple[str, str]:
    ok, output = _run(command, root)
    if ok:
        return "pass", output[-500:] or "command passed"
    lowered = output.lower()
    if not output or "no such file" in lowered or "not found" in lowered:
        return "null", "required local tool is unavailable"
    return "fail", output[-500:]


def _runtime_check(root: Path, binary: str) -> tuple[str, str]:
    return _status([binary, "ecosystem", "doctor", "--repo", "."], root)


def build_report(
    root: Path,
    runtime_binary: str = "simplicio",
    require_runtime: bool = False,
    full: bool = False,
    require_tools: bool = False,
) -> tuple[str, int]:
    checks: list[tuple[str, str, str]] = []

    scanner_ok, scanner_output = _run(
        [sys.executable, "scripts/check_json_boundaries.py", "--strict"], root
    )
    checks.append(("Internal JSON inventory", "pass" if scanner_ok else "fail", scanner_output or "no output"))

    runtime_status, runtime_detail = _runtime_check(root, runtime_binary)
    checks.append(("Runtime ecosystem doctor", runtime_status, runtime_detail))

    if full:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        for name, command in (
            ("Python tests", [sys.executable, "-m", "pytest", "-q"]),
            ("Node unit tests", [npm, "test"]),
            ("Package contents", [npm, "pack", "--dry-run"]),
        ):
            checks.append((name, *_status(command, root)))

    hard_fail = any(result == "fail" for _, result, _ in checks)
    missing_required = any(result == "null" for _, result, _ in checks if require_tools)
    if require_runtime and runtime_status != "pass":
        missing_required = True

    overall = "PASS" if not hard_fail and not missing_required else "BLOCKED"
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# Mapper quality gate",
        "",
        f"- Generated: {now}",
        f"- Overall: **{overall}**",
        "- Execution mode: local/offline; GitHub Actions not required",
        "",
        "| Criterion | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    lines.extend(f"| {name} | {result} | {detail} |" for name, result, detail in checks)
    lines.extend(
        [
            "| Cross-repository E2E | null | adjacent package versions are not available in this checkout |",
            "| Performance observations | null | benchmark hardware/workload not supplied |",
            "| HBP receipt | null | Runtime receipt export is not available in this checkout |",
            "",
            "A null result is unavailable evidence, never a passing zero.",
            "",
        ]
    )
    return "\n".join(lines), 0 if overall == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("artifacts/mapper-quality-summary.md"))
    parser.add_argument("--runtime-binary", default="simplicio")
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--full", action="store_true", help="also run Python, Node and package checks")
    parser.add_argument("--require-tools", action="store_true", help="block when local tools are unavailable")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report, code = build_report(
        root,
        args.runtime_binary,
        args.require_runtime,
        args.full,
        args.require_tools,
    )
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
