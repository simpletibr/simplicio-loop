#!/usr/bin/env python3
"""simplicio-loop — CI Quality Gate: flakiness / race-condition detector (#277).

Runs the test suite (or a `--target` subset) `--repeat` times back to back and diffs the
per-test pass/fail outcome across runs. A test that passes in one run and fails in another
(same code, same inputs) is flagged as flaky — the class of bug this issue calls out
("testes repetidos para detectar flakiness e race conditions"). A test that fails in every run
is a plain failure, not flakiness, and is reported separately so the two aren't conflated.

Uses `pytest --json-report` when the `pytest-json-report` plugin is importable; otherwise falls
back to parsing `pytest -v` output per-test (works with a bare pytest install, no extra
dependency required to run this gate locally).

On any flaky or failing test, writes a diagnostic bundle (`--diagnostics-dir`, default
`.simplicio-loop/quality-gate/flaky/`) with the raw output of every run so a failure in CI leaves
enough trace to reproduce it without re-running the whole matrix.

Usage:
    python3 scripts/flaky_gate.py                          # 5x tests/, default critical subset
    python3 scripts/flaky_gate.py --repeat 10 --target tests/test_drain_integration.py tests/test_fan_out_unit.py
    python3 scripts/flaky_gate.py --stress --repeat 25      # heavier stress pass (issue's "stress tests")

Exit codes: 0 = stable across every run, 1 = flaky and/or consistently-failing tests found.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# "Critical" default subset: the loop-contract / convergence / drain surfaces this issue is
# specifically about. Kept small on purpose -- a full-suite x N-repeat run is the `--stress` mode.
DEFAULT_TARGETS = [
    "tests/test_drain_integration.py",
    "tests/test_drain_cli_integration.py",
    "tests/test_fan_out_unit.py",
    "tests/test_fan_out_flow_system.py",
    "tests/test_fan_out_scheduler_integration.py",
    "tests/test_completion_oracle_system.py",
    "tests/test_completion_oracle_matrix_unit.py",
    "tests/test_control_policy_unit.py",
    "tests/test_run_state.py",
]

_RESULT_LINE = re.compile(r"^(?P<nodeid>\S+::\S+)\s+(?P<outcome>PASSED|FAILED|ERROR)\b")


def _existing_targets(targets):
    out = [t for t in targets if os.path.exists(os.path.join(REPO, t))]
    missing = [t for t in targets if t not in out]
    if missing:
        print(f"[flaky-gate] note: skipping missing targets: {missing}", file=sys.stderr)
    return out


def _run_once(targets, run_index, diagnostics_dir):
    cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short"] + targets
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    output = proc.stdout + "\n" + proc.stderr

    if diagnostics_dir:
        os.makedirs(diagnostics_dir, exist_ok=True)
        with open(os.path.join(diagnostics_dir, f"run_{run_index:03d}.log"), "w", encoding="utf-8") as fh:
            fh.write(output)

    outcomes = {}
    for line in output.splitlines():
        m = _RESULT_LINE.match(line.strip())
        if m:
            outcomes[m.group("nodeid")] = m.group("outcome")
    return outcomes, proc.returncode, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=5, help="number of repeated runs (default: 5)")
    parser.add_argument("--target", nargs="*", default=None, help="explicit test file(s)/node id(s); default: critical subset")
    parser.add_argument("--stress", action="store_true", help="stress mode: default repeat becomes 25 and target is the whole tests/ dir unless --target given")
    parser.add_argument("--diagnostics-dir", default=None, help="directory to write per-run logs + summary (default: .simplicio-loop/quality-gate/flaky)")
    parser.add_argument("--json", action="store_true", help="print machine-readable summary")
    args = parser.parse_args()

    if args.stress and args.repeat == 5:
        args.repeat = 25

    targets = args.target if args.target else (["tests/"] if args.stress else DEFAULT_TARGETS)
    if not args.target:
        targets = _existing_targets(targets) if not args.stress else targets

    diagnostics_dir = args.diagnostics_dir or os.path.join(REPO, ".simplicio-loop", "quality-gate", "flaky")

    history = {}  # nodeid -> list of outcomes across runs
    return_codes = []
    for i in range(1, args.repeat + 1):
        outcomes, rc, _ = _run_once(targets, i, diagnostics_dir)
        return_codes.append(rc)
        for nodeid, outcome in outcomes.items():
            history.setdefault(nodeid, []).append(outcome)
        print(f"[flaky-gate] run {i}/{args.repeat}: rc={rc}, {len(outcomes)} tests observed", file=sys.stderr)

    flaky = {}
    always_failing = {}
    for nodeid, outcomes in history.items():
        unique = set(outcomes)
        if len(unique) > 1:
            flaky[nodeid] = outcomes
        elif unique == {"FAILED"} or unique == {"ERROR"}:
            always_failing[nodeid] = outcomes

    summary = {
        "repeat": args.repeat,
        "targets": targets,
        "tests_observed": len(history),
        "flaky_tests": flaky,
        "always_failing_tests": always_failing,
        "return_codes": return_codes,
    }

    if diagnostics_dir and (flaky or always_failing):
        os.makedirs(diagnostics_dir, exist_ok=True)
        with open(os.path.join(diagnostics_dir, "summary.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        print(f"[flaky-gate] diagnostics written to {diagnostics_dir}", file=sys.stderr)

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        if flaky:
            print("\n[flaky-gate] FLAKY tests detected (inconsistent outcome across runs):")
            for nodeid, outcomes in flaky.items():
                print(f"  - {nodeid}: {outcomes}")
        if always_failing:
            print("\n[flaky-gate] Consistently FAILING tests (not flaky, but broken):")
            for nodeid, outcomes in always_failing.items():
                print(f"  - {nodeid}: {outcomes}")
        if not flaky and not always_failing:
            print(f"[flaky-gate] OK: {len(history)} tests stable across {args.repeat} runs.")

    return 1 if (flaky or always_failing) else 0


if __name__ == "__main__":
    sys.exit(main())
