#!/usr/bin/env python3
"""simplicio-dev-cli -- Coverage Quality Gate (issue #202).

Enforces the two coverage floors from the CI Quality Gate epic:

  - 85% overall line coverage across `simplicio/` (the same number as
    `[tool.coverage.report].fail_under` in pyproject.toml -- this script is
    the stricter, second check that also breaks out per-module numbers).
  - 90% coverage on the "critical" modules declared in
    `[tool.coverage.simplicio_critical]` in pyproject.toml: the CLI
    entrypoint, the pipeline/mechanical-edit/mapper core, and the
    doctor/execution-contract gates that run on every `task`/`run` call.

Input is a `coverage.json` report (produced by `coverage json` or
`pytest --cov=simplicio --cov-report=json`), never coverage.py's internal
SQLite `.coverage` database directly, so this script has no dependency on
coverage.py itself and can run in any environment that already has the JSON
file on disk.

Usage:
    pytest --cov=simplicio --cov-report=json:coverage.json
    python3 scripts/coverage_gate.py                       # reads ./coverage.json
    python3 scripts/coverage_gate.py --report path/to.json  # explicit path
    python3 scripts/coverage_gate.py --self-test            # synthetic gate proof, no pytest needed

Exit codes: 0 = both floors met (or self-test passed), 1 = a floor was
missed, a critical module has zero coverage data, or the report is missing/
malformed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PYPROJECT = os.path.join(REPO, "pyproject.toml")
DEFAULT_REPORT = os.path.join(REPO, "coverage.json")


def _load_config() -> tuple[float, float, list[str]]:
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    tool = data.get("tool", {})
    global_floor = float(tool.get("coverage", {}).get("report", {}).get("fail_under", 85))
    critical_cfg = tool.get("coverage", {}).get("simplicio_critical", {})
    critical_floor = float(critical_cfg.get("threshold", 90))
    critical_modules = list(critical_cfg.get("modules", []))
    return global_floor, critical_floor, critical_modules


def _percent_covered(file_entry: dict) -> float:
    summary = file_entry.get("summary", {})
    pct = summary.get("percent_covered")
    if pct is not None:
        return float(pct)
    covered = summary.get("covered_lines", 0)
    num = summary.get("num_statements", 0)
    return 100.0 if num == 0 else (covered / num) * 100.0


def evaluate(report: dict, global_floor: float, critical_floor: float, critical_modules: list[str]):
    """Returns (ok: bool, lines: list[str])."""
    lines: list[str] = []
    ok = True

    totals = report.get("totals", {})
    overall_pct = totals.get("percent_covered")
    if overall_pct is None:
        lines.append("::error::coverage.json has no top-level 'totals.percent_covered'")
        return False, lines
    overall_pct = float(overall_pct)

    if overall_pct + 1e-9 >= global_floor:
        lines.append(f"OK   overall coverage {overall_pct:.2f}% >= floor {global_floor:.2f}%")
    else:
        ok = False
        lines.append(f"::error::overall coverage {overall_pct:.2f}% < required floor {global_floor:.2f}%")

    files = report.get("files", {})
    # coverage.json keys files by path as recorded by coverage.py, which is
    # relative to the run's cwd (repo root in CI) -- normalize separators so
    # this also works when the report was produced on Windows.
    normalized = {k.replace("\\", "/"): v for k, v in files.items()}

    for module in critical_modules:
        entry = normalized.get(module)
        if entry is None:
            ok = False
            lines.append(
                f"::error::critical module '{module}' has no entry in coverage.json "
                "(not imported by any test, or path mismatch)"
            )
            continue
        pct = _percent_covered(entry)
        if pct + 1e-9 >= critical_floor:
            lines.append(f"OK   {module}: {pct:.2f}% >= critical floor {critical_floor:.2f}%")
        else:
            ok = False
            lines.append(
                f"::error::critical module {module}: {pct:.2f}% < required critical floor {critical_floor:.2f}%"
            )

    return ok, lines


def _self_test() -> int:
    """Synthetic proof the gate actually catches a regression, without
    needing a real pytest run or coverage.json on disk."""
    passing_report = {
        "totals": {"percent_covered": 90.0},
        "files": {
            "simplicio/cli.py": {"summary": {"percent_covered": 95.0}},
        },
    }
    failing_report = {
        "totals": {"percent_covered": 70.0},
        "files": {
            "simplicio/cli.py": {"summary": {"percent_covered": 40.0}},
        },
    }
    modules = ["simplicio/cli.py"]

    ok, _ = evaluate(passing_report, 85.0, 90.0, modules)
    if not ok:
        print("SELF-TEST FAILED: passing fixture was rejected by the gate")
        return 1

    ok, _ = evaluate(failing_report, 85.0, 90.0, modules)
    if ok:
        print("SELF-TEST FAILED: failing fixture was accepted by the gate")
        return 1

    missing_module_report = {
        "totals": {"percent_covered": 95.0},
        "files": {},
    }
    ok, _ = evaluate(missing_module_report, 85.0, 90.0, modules)
    if ok:
        print("SELF-TEST FAILED: missing critical-module entry was accepted by the gate")
        return 1

    print("SELF-TEST OK: coverage_gate.py correctly accepts/rejects synthetic reports")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help="Path to a coverage.json report (default: ./coverage.json)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the gate against synthetic fixtures and exit (no pytest/coverage.json needed)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    global_floor, critical_floor, critical_modules = _load_config()

    if not os.path.isfile(args.report):
        print(
            f"::error::coverage report not found at {args.report!r}. "
            "Run `pytest --cov=simplicio --cov-report=json:coverage.json` first.",
            file=sys.stderr,
        )
        return 1

    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)

    ok, lines = evaluate(report, global_floor, critical_floor, critical_modules)
    print("\n".join(lines))

    if ok:
        print(f"\nCoverage gate PASSED (global >= {global_floor:.0f}%, critical >= {critical_floor:.0f}%).")
        return 0

    print(
        f"\nCoverage gate FAILED. Required: global >= {global_floor:.0f}%, "
        f"critical modules >= {critical_floor:.0f}% "
        f"({', '.join(critical_modules)})."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
