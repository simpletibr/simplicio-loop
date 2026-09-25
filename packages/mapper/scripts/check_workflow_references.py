#!/usr/bin/env python3
"""Fail closed when the quality workflow points at missing gate files/config."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
REQUIRED_FILES = (
    ROOT / "scripts" / "critical_coverage_gate.py",
    ROOT / "scripts" / "coverage.js",
)
REQUIRED_TEXT = (
    "critical_coverage_gate.py",
    "coverage.js",
    "--global-min 85",
    "--critical-min 90",
)


def main() -> int:
    failures: list[str] = []
    if not WORKFLOW.is_file():
        failures.append(f"missing workflow: {WORKFLOW.relative_to(ROOT)}")
        workflow_text = ""
    else:
        workflow_text = WORKFLOW.read_text(encoding="utf-8")

    for path in REQUIRED_FILES:
        if not path.is_file():
            failures.append(f"missing gate file: {path.relative_to(ROOT)}")
    for marker in REQUIRED_TEXT:
        if marker not in workflow_text:
            failures.append(f"workflow is missing required reference: {marker}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("Workflow reference self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
