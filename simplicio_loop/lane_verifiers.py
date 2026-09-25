"""Build quality-matrix.json by measuring the task file's per-lane verifiers.

A task declares one command per quality lane in its task file::

    Unit verifier: `pytest -q tests/unit`
    Integration verifier: `pytest -q tests/integration`
    System verifier: `python -m app --smoke`
    Regression verifier: `pytest -q tests/regression`
    Benchmark verifier: `python bench.py`
    Coverage verifier: `pytest --cov=app -q`

The loop runs each command in the target repository and records what it
measured. Nothing is inferred: a lane without a command fails and names the
line to add; implementation is proven by the applied Dev CLI receipts.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, Mapping

from .quality_matrix import DEFAULT_COVERAGE_THRESHOLD, RECEIPT_FILENAME, SCHEMA

MEASURED_LANES = ("unit", "integration", "system", "regression", "benchmark")
_LINE = re.compile(
    r"^\s*(unit|integration|system|regression|benchmark|coverage)\s+verifier:\s*`([^`]+)`",
    re.IGNORECASE | re.MULTILINE,
)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")
LANE_TIMEOUT_SECONDS = 900


def parse_lane_verifiers(task_text: str) -> Dict[str, str]:
    """Return ``{lane: command}`` for every ``<Lane> verifier: `cmd``` line."""
    return {m.group(1).lower(): m.group(2).strip() for m in _LINE.finditer(task_text or "")}


def _missing(lane: str) -> Dict[str, str]:
    return {"status": "missing", "proof_ref": "",
            "detail": f"declare `{lane.capitalize()} verifier: `<command>`` in the task file"}


def _run(command: str, repo: Path, log: Path) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, shell=True, cwd=str(repo), capture_output=True, text=True,
                              timeout=LANE_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        output, ok = (done.stdout or "") + (done.stderr or ""), done.returncode == 0
        header = f"$ {command}\nexit={done.returncode}\n"
    except subprocess.TimeoutExpired:
        output, ok, header = "", False, f"$ {command}\ntimeout={LANE_TIMEOUT_SECONDS}s\n"
    log.write_text(header + output, encoding="utf-8")
    return ok, output


def missing_or_unapplied_tasks(run_dir: Path, task_count: int) -> list[int]:
    """Return the 1-based task indices with no ``operator-receipt-<N>.json`` on disk,
    or one that exists but is not ``applied`` -- one per task, not one per file found.

    A dead-lettered task (e.g. rejected before the operator ever ran) never writes
    its own ``operator-receipt-<N>.json`` at all: counting *found* files (instead of
    every index the run itself scheduled) is exactly how a run with 9 dead-lettered
    tasks out of 10 could still read "implementation: pass" from the one receipt task
    1 left behind.
    """
    missing: list[int] = []
    for index in range(1, task_count + 1):
        path = run_dir / f"operator-receipt-{index}.json"
        if not path.is_file():
            missing.append(index)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            missing.append(index)
            continue
        if payload.get("execution_state") != "applied":
            missing.append(index)
    return missing


def build_quality_matrix(repo: Path, run_dir: Path, task_texts: Iterable[str]) -> Dict[str, object]:
    """Measure every declared lane in ``repo`` and write ``run_dir/quality-matrix.json``."""
    repo, run_dir = Path(repo), Path(run_dir)
    task_texts = list(task_texts)
    lanes: Dict[str, str] = {}
    for text in task_texts:
        for lane, command in parse_lane_verifiers(text).items():
            lanes.setdefault(lane, command)
    logs = run_dir / "lanes"
    logs.mkdir(parents=True, exist_ok=True)

    task_count = len(task_texts)
    missing = missing_or_unapplied_tasks(run_dir, task_count)
    applied = task_count > 0 and not missing
    receipts = sorted(run_dir.glob("operator-receipt-*.json"))
    requirements: Dict[str, Mapping[str, object]] = {
        "implementation": {
            "status": "pass" if applied else "fail",
            "proof_ref": ",".join(str(p) for p in receipts),
            "missing_task_indices": missing,
            "detail": "every Dev CLI operator receipt is applied" if applied
            else f"task index(es) {missing} have no applied operator receipt "
                 f"(expected one per task, {task_count} task(s) total)",
        }
    }
    for lane in MEASURED_LANES:
        if lane not in lanes:
            requirements[lane] = _missing(lane)
            continue
        log = logs / f"{lane}.log"
        ok, _ = _run(lanes[lane], repo, log)
        requirements[lane] = {"status": "pass" if ok else "fail", "proof_ref": str(log),
                              "command": lanes[lane],
                              "detail": f"`{lanes[lane]}` exited {'0' if ok else 'non-zero'}"}

    coverage: Dict[str, object] = {"measured": None}
    if "coverage" in lanes:
        log = logs / "coverage.log"
        ok, output = _run(lanes["coverage"], repo, log)
        found = _PERCENT.findall(output)
        if ok and found:
            coverage = {"measured": float(found[-1]), "proof_ref": str(log), "command": lanes["coverage"]}

    receipt = {
        "schema": SCHEMA,
        "coverage_threshold": DEFAULT_COVERAGE_THRESHOLD,
        "requirements": requirements,
        "coverage": coverage,
        "source": "lane_verifiers",
    }
    (run_dir / RECEIPT_FILENAME).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def reverify(receipt: Mapping[str, object], repo: Path, logs: Path) -> list[Dict[str, str]]:
    """Independently re-run every passing lane's own command in the target repo."""
    checks: list[Dict[str, str]] = []
    logs.mkdir(parents=True, exist_ok=True)
    requirements = receipt.get("requirements") if isinstance(receipt.get("requirements"), dict) else {}
    for lane in MEASURED_LANES:
        entry = requirements.get(lane) if isinstance(requirements, dict) else None
        if not isinstance(entry, dict) or entry.get("status") != "pass" or not entry.get("command"):
            continue
        ok, _ = _run(str(entry["command"]), repo, logs / f"reverify-{lane}.log")
        checks.append({"name": lane, "status": "pass" if ok else "fail",
                       "reason_code": f"quality_{lane}_reverify_{'verified' if ok else 'mismatch'}",
                       "detail": f"independent re-run of `{entry['command']}` {'passed' if ok else 'now fails'}"})
    coverage = receipt.get("coverage")
    if isinstance(coverage, dict) and coverage.get("command") and isinstance(coverage.get("measured"), (int, float)):
        ok, output = _run(str(coverage["command"]), repo, logs / "reverify-coverage.log")
        found = _PERCENT.findall(output)
        measured = float(found[-1]) if ok and found else None
        drift = measured is None or float(coverage["measured"]) > measured + 0.01
        checks.append({"name": "coverage", "status": "fail" if drift else "pass",
                       "reason_code": "quality_coverage_drift" if drift else "quality_coverage_reverify_verified",
                       "detail": f"claimed {coverage['measured']}%, re-measured {measured}%"})
    return checks
