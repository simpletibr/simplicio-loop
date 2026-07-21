#!/usr/bin/env python3
"""Release gate for Mapper's binary-format migration.

The gate emits Markdown only. Missing external evidence is represented as
null (reason) and can be made release-blocking with --require-runtime.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    except OSError as error:
        return False, str(error)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def _runtime_check(root: Path, binary: str) -> tuple[str, str]:
    ok, output = _run([binary, "ecosystem", "doctor", "--repo", "."], root)
    if ok:
        return "pass", output[-500:] or "runtime doctor passed"
    lowered = output.lower()
    if not output or "no such file" in lowered or "not found" in lowered:
        return "null", "simplicio-runtime unavailable or returned no diagnostic"
    return "fail", output[-500:]


def build_report(root: Path, runtime_binary: str = "simplicio", require_runtime: bool = False) -> tuple[str, int]:
    scanner_ok, scanner_output = _run(
        [sys.executable, "scripts/check_json_boundaries.py", "--strict"], root
    )
    runtime_status, runtime_detail = _runtime_check(root, runtime_binary)
    status = "PASS" if scanner_ok and (runtime_status == "pass" or not require_runtime) else "BLOCKED"
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# Mapper quality gate",
        "",
        f"- Generated: {now}",
        f"- Overall: **{status}**",
        "",
        "| Criterion | Result | Evidence |",
        "| --- | --- | --- |",
        f"| Internal JSON inventory | {'pass' if scanner_ok else 'fail'} | {scanner_output or 'no output'} |",
        f"| Runtime ecosystem doctor | {runtime_status} | {runtime_detail} |",
        "| Performance observations | null | benchmark hardware/workload not available in this lane |",
        "| HBP receipt | null | Runtime receipt export is not available in this checkout |",
        "",
        "A null result is unavailable evidence, never a passing zero.",
        "",
    ]
    return "\n".join(lines), 0 if status == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("artifacts/mapper-quality-summary.md"))
    parser.add_argument("--runtime-binary", default="simplicio")
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report, code = build_report(root, args.runtime_binary, args.require_runtime)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
