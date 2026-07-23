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

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 uses the optional backport
    import tomli as tomllib  # type: ignore[no-redef]


_REQUIRED_RELEASE_EVIDENCE = {
    "cross_repository_e2e": "adjacent released packages were not exercised",
    "performance": "benchmark workload and hardware were not recorded",
    "hbp_receipt": "a conformant HBP execution receipt was not recorded",
    "hbi_conformance": "Runtime HBI conformance was not recorded",
}
_EVIDENCE_LABELS = {
    "cross_repository_e2e": "Cross-repository E2E",
    "performance": "Performance",
    "hbp_receipt": "HBP receipt",
    "hbi_conformance": "HBI conformance",
}


def _run(
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return False, str(error)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _status(
    command: list[str],
    root: Path,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    ok, output = _run(command, root, env=env)
    if ok:
        return "pass", output[-500:] or "command passed"
    lowered = output.lower()
    if not output or "no such file" in lowered or "not found" in lowered:
        return "null", "required local tool is unavailable"
    return "fail", output[-500:]


def _runtime_check(root: Path, binary: str) -> tuple[str, str]:
    return _status([binary, "ecosystem", "doctor", "--repo", "."], root)


def _release_evidence(path: Path | None) -> list[tuple[str, str, str]]:
    """Load explicit release observations without inventing unavailable results."""
    document: dict = {}
    load_error: str | None = None
    if path is not None:
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            load_error = f"evidence file unavailable or invalid: {error}"

    evidence = document.get("evidence", {})
    checks: list[tuple[str, str, str]] = []
    for key, unavailable_reason in _REQUIRED_RELEASE_EVIDENCE.items():
        entry = evidence.get(key, {}) if isinstance(evidence, dict) else {}
        observed = entry.get("observed") if isinstance(entry, dict) else None
        detail = entry.get("detail") if isinstance(entry, dict) else None
        if observed is True and isinstance(detail, str) and detail.strip():
            checks.append((key, "pass", detail.strip()))
        elif observed is False and isinstance(detail, str) and detail.strip():
            checks.append((key, "fail", detail.strip()))
        else:
            checks.append((key, "null", load_error or unavailable_reason))
    return checks


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def build_report(
    root: Path,
    runtime_binary: str = "simplicio",
    require_runtime: bool = False,
    full: bool = False,
    require_tools: bool = False,
    release: bool = False,
    evidence_path: Path | None = None,
) -> tuple[str, int]:
    checks: list[tuple[str, str, str]] = []

    scanner_ok, scanner_output = _run(
        [
            sys.executable,
            "scripts/check_json_boundaries.py",
            "--mode",
            "strict" if release else "baseline",
        ], root
    )
    checks.append(("Internal JSON inventory", "pass" if scanner_ok else "fail", scanner_output or "no output"))

    runtime_status, runtime_detail = _runtime_check(root, runtime_binary)
    checks.append(("Runtime ecosystem doctor", runtime_status, runtime_detail))

    if full:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        test_env = os.environ.copy()
        existing_pythonpath = test_env.get("PYTHONPATH")
        test_env["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(root), existing_pythonpath) if value
        )
        for name, command, env in (
            # Fixture projects have their own `src` roots and are exercised by
            # their dedicated contract/E2E tests. Collecting them from the
            # repository root makes pytest resolve the wrong import root.
            ("Python tests", [sys.executable, "-m", "pytest", "-q", "tests/python"], test_env),
            ("Node unit tests", [npm, "test"], None),
            ("Package contents", [npm, "pack", "--dry-run"], None),
        ):
            checks.append((name, *_status(command, root, env=env)))

    release_checks = _release_evidence(evidence_path)
    checks.extend(
        (_EVIDENCE_LABELS[name], result, detail)
        for name, result, detail in release_checks
    )

    hard_fail = any(result == "fail" for _, result, _ in checks)
    missing_required = any(result == "null" for _, result, _ in checks if require_tools)
    if require_runtime and runtime_status != "pass":
        missing_required = True

    unavailable_evidence = release and (
        runtime_status != "pass"
        or not full
        or any(result != "pass" for _, result, _ in release_checks)
    )
    overall = "PASS" if not hard_fail and not missing_required and not unavailable_evidence else "BLOCKED"
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
    lines.extend(
        f"| {_table_cell(name)} | {result} | {_table_cell(detail)} |"
        for name, result, detail in checks
    )
    lines.extend(["", "A null result is unavailable evidence, never a passing zero.", ""])
    return "\n".join(lines), 0 if overall == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("artifacts/mapper-quality-summary.md"))
    parser.add_argument("--runtime-binary", default="simplicio")
    parser.add_argument("--require-runtime", action="store_true")
    parser.add_argument("--full", action="store_true", help="also run Python, Node and package checks")
    parser.add_argument("--require-tools", action="store_true", help="block when local tools are unavailable")
    parser.add_argument("--release", action="store_true", help="fail closed on legacy JSON or unavailable evidence")
    parser.add_argument("--evidence", type=Path, help="TOML file containing observed release evidence")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report, code = build_report(
        root,
        args.runtime_binary,
        args.require_runtime,
        args.full,
        args.require_tools,
        args.release,
        args.evidence,
    )
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
