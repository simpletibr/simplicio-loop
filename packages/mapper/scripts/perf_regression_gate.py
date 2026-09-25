#!/usr/bin/env python3
"""Precision / contract / performance regression gate (issue #222).

Runs the repo's existing measurement harnesses fresh, then diffs the result
against the committed baselines under ``docs/evidence/`` with *documented*
tolerances. This is the "regression above the documented limit is flagged"
half of the CI quality gate; the golden-file and schema checks (already
wired via ``scripts/toon_contract_runner.py`` and
``scripts/regen_contract_fixtures.py``) cover the other two acceptance
criteria.

Two harnesses feed this gate:

* ``scripts/evaluation_scorecard.py`` - precision (mean_precision_at_k,
  recall metrics, task_success), latency, and artifact/context-pack size on
  the small deterministic evaluation corpus. Fast enough to run on every PR.
* ``scripts/runtime_scale_benchmark.py`` - indexed-vs-legacy retrieval
  throughput and byte/RAM proxies on a synthetic ~5000-file tree. Slower;
  gated on the *relative* speedup ratio rather than absolute milliseconds,
  because absolute wall-clock numbers are not comparable across CI runners
  with different hardware (this is a documented, deliberate choice - see
  README section this script's docstring is quoted from).

Tolerances (documented here, the single source of truth for this gate):

  * precision / recall / success metrics (0..1 scale): fail if a metric
    drops by more than ``--precision-tolerance`` (default 0.02, i.e. 2
    percentage points) below its baseline value.
  * latency metrics (ms): fail if they increase by more than
    ``--latency-tolerance`` (default 0.25 = 25%) relative to baseline.
  * artifact/context-pack/token size metrics: fail if they increase by more
    than ``--size-tolerance`` (default 0.20 = 20%) relative to baseline
    (guards against silent output bloat).
  * runtime-scale indexed-vs-legacy speedup ratio: fail if it drops by more
    than ``--speedup-tolerance`` (default 0.20 = 20%) relative to baseline.

Usage:
  python scripts/perf_regression_gate.py --json > quality-gate-report.json
  python scripts/perf_regression_gate.py --skip-runtime-scale   # fast path
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

BEHAVIORAL_BASELINE = ROOT / "docs" / "evidence" / "behavioral-scorecard.json"
RUNTIME_SCALE_BASELINE = ROOT / "docs" / "evidence" / "runtime-scale-benchmark.json"

# metric name -> comparison kind
PRECISION_METRICS = [
    "mean_precision_at_k",
    "task_success",
    "sufficiency",
    "determinism",
    "abstention_accuracy",
    "budget_fit_rate",
    "required_language_recall",
    "required_layer_recall",
    "required_span_recall",
    "target_recall_at_k",
    "test_recall_at_k",
]
LATENCY_METRICS = ["mean_latency_ms", "max_latency_ms"]
SIZE_METRICS = ["mean_artifact_output_bytes", "mean_context_pack_bytes", "estimated_tokens_mean"]


def _run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command {' '.join(cmd)} exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def _load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"baseline {path} is missing - seed it once with the harness's --write-json flag "
            "and commit it before this gate can run"
        )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _check_precision(
    fresh: dict[str, Any], baseline: dict[str, Any], tolerance: float
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for metric in PRECISION_METRICS:
        fresh_v = fresh.get(metric)
        base_v = baseline.get(metric)
        if fresh_v is None or base_v is None:
            continue
        delta = fresh_v - base_v
        ok = delta >= -tolerance
        checks.append(
            {
                "metric": metric,
                "kind": "precision",
                "baseline": base_v,
                "measured": fresh_v,
                "delta": round(delta, 6),
                "tolerance": -tolerance,
                "status": "pass" if ok else "fail",
            }
        )
    return checks


def _check_relative(
    fresh: dict[str, Any], baseline: dict[str, Any], metrics: list[str], tolerance: float, *, higher_is_bad: bool
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for metric in metrics:
        fresh_v = fresh.get(metric)
        base_v = baseline.get(metric)
        if fresh_v is None or base_v is None or base_v == 0:
            continue
        ratio = fresh_v / base_v
        if higher_is_bad:
            ok = ratio <= 1.0 + tolerance
        else:
            ok = ratio >= 1.0 - tolerance
        checks.append(
            {
                "metric": metric,
                "kind": "relative",
                "baseline": base_v,
                "measured": fresh_v,
                "ratio": round(ratio, 6),
                "tolerance": tolerance,
                "higher_is_bad": higher_is_bad,
                "status": "pass" if ok else "fail",
            }
        )
    return checks


def run_behavioral_gate(precision_tolerance: float, latency_tolerance: float, size_tolerance: float) -> dict[str, Any]:
    baseline_doc = _load_baseline(BEHAVIORAL_BASELINE)
    baseline = baseline_doc.get("measurements", baseline_doc)
    fresh_doc = _run_json([sys.executable, "scripts/evaluation_scorecard.py", "--json"])
    fresh = fresh_doc.get("measurements", fresh_doc)

    checks = (
        _check_precision(fresh, baseline, precision_tolerance)
        + _check_relative(fresh, baseline, LATENCY_METRICS, latency_tolerance, higher_is_bad=True)
        + _check_relative(fresh, baseline, SIZE_METRICS, size_tolerance, higher_is_bad=True)
    )
    return {"name": "behavioral-scorecard", "baseline_path": str(BEHAVIORAL_BASELINE), "checks": checks, "fresh": fresh}


def run_runtime_scale_gate(speedup_tolerance: float) -> dict[str, Any]:
    baseline_doc = _load_baseline(RUNTIME_SCALE_BASELINE)
    baseline_calibration = baseline_doc.get("calibration", {})
    fresh_doc = _run_json([sys.executable, "scripts/runtime_scale_benchmark.py", "--json"])
    fresh_calibration = fresh_doc.get("calibration", {})

    checks = _check_relative(
        fresh_calibration,
        baseline_calibration,
        ["indexed_vs_legacy_speedup_ratio"],
        speedup_tolerance,
        higher_is_bad=False,
    )
    return {
        "name": "runtime-scale-benchmark",
        "baseline_path": str(RUNTIME_SCALE_BASELINE),
        "checks": checks,
        "fresh": fresh_calibration,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--precision-tolerance", type=float, default=0.02)
    parser.add_argument("--latency-tolerance", type=float, default=0.25)
    parser.add_argument("--size-tolerance", type=float, default=0.20)
    parser.add_argument("--speedup-tolerance", type=float, default=0.20)
    parser.add_argument("--skip-runtime-scale", action="store_true", help="Skip the slower ~5000-file benchmark.")
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report to stdout.")
    parser.add_argument("--report-out", type=Path, help="Optional path to also write the JSON report to.")
    args = parser.parse_args(argv)

    sections: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        sections.append(run_behavioral_gate(args.precision_tolerance, args.latency_tolerance, args.size_tolerance))
    except Exception as error:  # noqa: BLE001 - surfaced as a gate failure, not a crash
        errors.append(f"behavioral-scorecard gate errored: {error}")

    if not args.skip_runtime_scale:
        try:
            sections.append(run_runtime_scale_gate(args.speedup_tolerance))
        except Exception as error:  # noqa: BLE001
            errors.append(f"runtime-scale-benchmark gate errored: {error}")

    all_checks = [check for section in sections for check in section["checks"]]
    failed_checks = [check for check in all_checks if check["status"] == "fail"]

    report = {
        "schema": "simplicio.quality-gate-perf/v1",
        "tolerances": {
            "precision_tolerance": args.precision_tolerance,
            "latency_tolerance": args.latency_tolerance,
            "size_tolerance": args.size_tolerance,
            "speedup_tolerance": args.speedup_tolerance,
        },
        "sections": sections,
        "errors": errors,
        "failed_checks": failed_checks,
        "status": "fail" if (errors or failed_checks) else "pass",
    }

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for section in sections:
            print(f"[{section['name']}] baseline={section['baseline_path']}")
            for check in section["checks"]:
                marker = "OK" if check["status"] == "pass" else "REGRESSION"
                print(f"  - {marker}: {check['metric']} baseline={check['baseline']} measured={check['measured']}")
        for error in errors:
            print(f"ERROR: {error}")

    if report["status"] == "fail":
        print(f"Performance/precision regression gate FAILED "
              f"({len(failed_checks)} regression(s), {len(errors)} error(s))", file=sys.stderr)
        return 1
    print("Performance/precision regression gate PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
