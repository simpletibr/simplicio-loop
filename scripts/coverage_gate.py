#!/usr/bin/env python3
"""simplicio-loop — CI Quality Gate: coverage gate (#277).

Runs the test suite under `coverage.py` and enforces two thresholds:

  - global line coverage   >= `--global-threshold`   (default 85%, per issue #277)
  - critical-path coverage >= `--critical-threshold`  (default 90%, per issue #277)

"Critical" modules are the convergence/drain/loop-contract surfaces this issue is about --
the ones where a silent regression means an infinite loop, a stall, or a stuck queue in
production (see `CRITICAL_MODULES` below; kept in sync with
`docs/SCRIPTS_INVENTORY.md`'s core-script table).

Requires the `coverage` package (`pip install coverage`) -- NOT a hard dependency of the shipped
package (see pyproject.toml's `dev` extra), only of this CI gate, mirroring how `pytest` itself is
already dev-only. Fails closed: if `coverage` isn't importable, this exits 1 rather than silently
skipping the gate.

On failure, writes the full HTML + XML coverage report under `--diagnostics-dir` (default
`.simplicio-loop/quality-gate/coverage/`) so a CI failure ships a reviewable per-line report as an
artifact, not just a percentage.

Usage:
    python3 scripts/coverage_gate.py
    python3 scripts/coverage_gate.py --global-threshold 85 --critical-threshold 90
    python3 scripts/coverage_gate.py --diagnostics-dir .simplicio-loop/quality-gate/coverage
    python3 scripts/coverage_gate.py --emit-json coverage-report.json

#283: `--emit-json PATH` unconditionally (pass or fail) writes the measured percentages plus the
report paths as a plain dict, so `scripts/quality_matrix.py populate` (and any independent
re-verifier) can read the exact number this run measured instead of a hand-typed
`coverage.measured` value.

Exit codes: 0 = both thresholds met, 1 = a threshold missed (or coverage unavailable).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Convergence / stability critical path (issue #277's "convergência, estabilidade"): the modules
# whose regression risk is an infinite loop, a stalled drain, or a corrupted run-journal.
CRITICAL_MODULES = [
    "scripts/loop_journal.py",
    "scripts/task_anchor.py",
    "scripts/watcher_verify.py",
    "scripts/hierarchical_planner.py",
    "scripts/completion_oracle.py",
    "scripts/run_state.py",
    "scripts/fan_out.py",
]


def _coverage_available():
    try:
        import coverage  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--global-threshold", type=float, default=85.0)
    parser.add_argument("--critical-threshold", type=float, default=90.0)
    parser.add_argument("--diagnostics-dir", default=None)
    parser.add_argument("--emit-json", default=None,
                        help="#283: unconditionally write the measured percentages/report paths here")
    parser.add_argument("--tests-path", action="append", default=None,
                        help="#283: scope the instrumented pytest run to these path(s) instead of the "
                             "whole tests/ tree (repeatable). Used to measure a defined, fast, "
                             "reliable subset -- e.g. quality/coverage-baseline.json's Fase A baseline "
                             "-- instead of the full suite, which includes slow/live/e2e tests. Default "
                             "(omitted) preserves the original full-suite behavior.")
    args = parser.parse_args()

    if not _coverage_available():
        print(
            "[coverage-gate] FAILED: the `coverage` package is not installed "
            "(`pip install coverage`). Fail-closed: not skipping the gate.",
            file=sys.stderr,
        )
        if args.emit_json:
            with open(args.emit_json, "w", encoding="utf-8") as fh:
                json.dump({
                    "schema": "simplicio.coverage-gate/v1", "ok": False,
                    "global_pct": None, "critical_pct": None,
                    "detail": "coverage package not installed",
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, fh, indent=2, sort_keys=True)
                fh.write("\n")
        return 1

    diagnostics_dir = args.diagnostics_dir or os.path.join(REPO, ".simplicio-loop", "quality-gate", "coverage")
    os.makedirs(diagnostics_dir, exist_ok=True)
    data_file = os.path.join(diagnostics_dir, ".coverage")

    tests_path = args.tests_path or ["tests/"]
    with tempfile.TemporaryDirectory(prefix="simplicio-loop-coverage-") as pytest_basetemp:
        run = subprocess.run(
            [
                sys.executable, "-m", "coverage", "run",
                f"--data-file={data_file}",
                "--source=simplicio_loop,engine,scripts",
                "-m", "pytest", "-q", "--basetemp", pytest_basetemp, *tests_path,
            ],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
        )
    if run.returncode != 0:
        print("[coverage-gate] FAILED: test suite did not pass under coverage instrumentation.", file=sys.stderr)
        # Still emit a report for whatever coverage data exists, for diagnosis.

    from coverage import Coverage

    cov = Coverage(data_file=data_file)
    cov.load()

    xml_path = os.path.join(diagnostics_dir, "coverage.xml")
    html_dir = os.path.join(diagnostics_dir, "html")
    try:
        global_pct = cov.xml_report(outfile=xml_path)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[coverage-gate] warning: xml report failed: {exc}", file=sys.stderr)
        global_pct = cov.report()
    try:
        cov.html_report(directory=html_dir)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[coverage-gate] warning: html report failed: {exc}", file=sys.stderr)

    data = cov.get_data()
    measured_files = {os.path.relpath(f, REPO).replace("\\", "/") for f in data.measured_files()}

    critical_present = [m for m in CRITICAL_MODULES if m in measured_files]
    critical_missing = [m for m in CRITICAL_MODULES if m not in measured_files]

    if critical_present:
        total_stmts = 0
        total_missing = 0
        for rel_path in critical_present:
            abs_path = os.path.join(REPO, rel_path)
            # #283: `Coverage.analysis2` is the PUBLIC API for per-file statement/missing-line
            # counts (`filename, statements, excluded, missing, missing_formatted`). The private
            # `cov._analyze(cov._get_file_reporter(...))` pair this replaced broke outright on
            # coverage.py 7.15.x/Python 3.14 (`PythonFileReporter` became unhashable, so
            # `_analyze`'s internal dict-keyed cache raised `TypeError` -- this crashed the gate
            # on every invocation, before any threshold was even checked).
            _, statements, _excluded, missing, _formatted = cov.analysis2(abs_path)
            total_stmts += len(statements)
            total_missing += len(missing)
        critical_pct = (
            100.0 * (total_stmts - total_missing) / total_stmts if total_stmts else 100.0
        )
    else:
        critical_pct = 0.0

    print(f"[coverage-gate] global coverage:   {global_pct:.2f}% (threshold {args.global_threshold:.2f}%)")
    print(f"[coverage-gate] critical coverage: {critical_pct:.2f}% (threshold {args.critical_threshold:.2f}%)")
    if critical_missing:
        print(f"[coverage-gate] note: critical modules not exercised by any test: {critical_missing}", file=sys.stderr)

    failures = []
    if run.returncode != 0:
        failures.append("test suite failed under coverage")
    if global_pct < args.global_threshold:
        failures.append(f"global coverage {global_pct:.2f}% < {args.global_threshold:.2f}%")
    if critical_pct < args.critical_threshold:
        failures.append(f"critical coverage {critical_pct:.2f}% < {args.critical_threshold:.2f}%")

    if args.emit_json:
        with open(args.emit_json, "w", encoding="utf-8") as fh:
            json.dump({
                "schema": "simplicio.coverage-gate/v1",
                "ok": not failures,
                "tests_scope": tests_path,
                "global_pct": round(global_pct, 4),
                "critical_pct": round(critical_pct, 4),
                "global_threshold": args.global_threshold,
                "critical_threshold": args.critical_threshold,
                "critical_present": critical_present,
                "critical_missing": critical_missing,
                "xml_report": xml_path,
                "html_report": html_dir,
                "test_suite_returncode": run.returncode,
                "failures": failures,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, fh, indent=2, sort_keys=True)
            fh.write("\n")

    if failures:
        print("\n[coverage-gate] FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"[coverage-gate] diagnostic report: {xml_path}, {html_dir}", file=sys.stderr)
        return 1

    print("[coverage-gate] OK: both thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
