#!/usr/bin/env python3
"""Coverage quality gate (issue #222): global + critical-path thresholds.

`pytest --cov-report=json` already produces a per-file coverage breakdown.
This script is the *gate* on top of that report: it fails the build when

  * global (repo-wide) line coverage drops below ``--global-min`` (default
    85%, per issue #222's acceptance criteria), or
  * the average line coverage across the CRITICAL_MODULES set (the modules
    that back precision/contract-sensitive behavior: the TOON codec, the
    contract validator, the retrieval index, and the query/drift engines)
    drops below ``--critical-min`` (default 90%).

Usage:
  python -m pytest tests/python -q --cov=simplicio_mapper --cov-report=json:coverage.json
  python scripts/critical_coverage_gate.py --coverage-json coverage.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Modules whose regressions directly threaten precision/contract guarantees
# this gate exists to protect (TOON-CONTRACT round-tripping, mapper-artifacts
# schema validation, retrieval ranking, drift/query correctness). Held to a
# higher bar (--critical-min) than the repo-wide floor.
CRITICAL_MODULES = [
    "simplicio_mapper/toon.py",
    "simplicio_mapper/contract.py",
    "simplicio_mapper/ecosystem_contract.py",
    "simplicio_mapper/retrieval_index.py",
    "simplicio_mapper/query.py",
    "simplicio_mapper/drift.py",
    "simplicio_mapper/context_cache.py",
    "simplicio_mapper/incremental.py",
]


def _file_percent(files: dict, rel_path: str) -> float | None:
    # coverage.py json report keys files by the path it discovered them at,
    # which can be relative or absolute depending on invocation directory.
    for key, payload in files.items():
        normalized = key.replace("\\", "/")
        if normalized == rel_path or normalized.endswith("/" + rel_path):
            return float(payload["summary"]["percent_covered"])
    return None


def evaluate(coverage_json: Path, global_min: float, critical_min: float) -> dict:
    with open(coverage_json, encoding="utf-8") as handle:
        report = json.load(handle)

    files = report.get("files", {})
    global_percent = float(report["totals"]["percent_covered"])

    critical_percents: dict[str, float | None] = {
        module: _file_percent(files, module) for module in CRITICAL_MODULES
    }
    measured = [v for v in critical_percents.values() if v is not None]
    critical_percent = round(sum(measured) / len(measured), 3) if measured else None

    missing = [module for module, v in critical_percents.items() if v is None]

    failures: list[str] = []
    if global_percent < global_min:
        failures.append(
            f"global coverage {global_percent:.2f}% is below the required floor {global_min:.2f}%"
        )
    if critical_percent is None:
        failures.append(
            "no critical-module coverage data found (checked: "
            + ", ".join(CRITICAL_MODULES)
            + ") - coverage.json may not include these modules"
        )
    elif critical_percent < critical_min:
        failures.append(
            f"critical-path coverage {critical_percent:.2f}% is below the required floor {critical_min:.2f}%"
        )

    return {
        "schema": "simplicio.coverage-gate/v1",
        "global_percent": round(global_percent, 3),
        "global_min": global_min,
        "critical_percent": critical_percent,
        "critical_min": critical_min,
        "critical_modules": critical_percents,
        "critical_modules_missing_from_report": missing,
        "failures": failures,
        "status": "fail" if failures else "pass",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, default=ROOT / "coverage.json")
    parser.add_argument("--global-min", type=float, default=85.0)
    parser.add_argument("--critical-min", type=float, default=90.0)
    parser.add_argument("--report-out", type=Path, help="Optional path to write the JSON report.")
    args = parser.parse_args(argv)

    if not args.coverage_json.exists():
        print(
            f"coverage gate: {args.coverage_json} not found - run pytest with "
            "--cov-report=json:<path> first",
            file=sys.stderr,
        )
        return 2

    result = evaluate(args.coverage_json, args.global_min, args.critical_min)

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Coverage gate: global={result['global_percent']}% (min {args.global_min}%), "
          f"critical={result['critical_percent']}% (min {args.critical_min}%)")
    for module, percent in result["critical_modules"].items():
        print(f"  - {module}: {percent if percent is not None else 'MISSING'}%")

    if result["failures"]:
        print("Coverage gate FAILED:")
        for failure in result["failures"]:
            print(f"  - {failure}")
        return 1

    print("Coverage gate PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
