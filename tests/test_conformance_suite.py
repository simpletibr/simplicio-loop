"""Issue #432 — stage-agent conformance suite: prove the 12 canonical roles
materialize and produce equivalent receipts on every supported runtime.

Run: python3 -m pytest tests/test_conformance_suite.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUITE = REPO / "scripts" / "conformance_suite.py"


def _run(args):
    return subprocess.run(
        [sys.executable, str(SUITE), *args],
        cwd=str(REPO), capture_output=True, text=True, timeout=30,
    )


def test_suite_runs_portable_validation_without_claiming_runtime_execution():
    """The core is a portable contract gate, not a 14-runtime execution claim (DeepSeek is a provider, not a runtime)."""
    proc = _run([])
    assert proc.returncode == 0, proc.stderr
    assert "portable conformance: 0/14 runtimes executed; gate=pass" in proc.stdout, proc.stdout


def test_json_report_has_canonical_roles_and_results(tmp_path):
    out = tmp_path / "conformance-report.json"
    proc = _run(["--json", str(out)])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "simplicio.conformance/v1"
    assert data["issue"] == 432
    # All 12 canonical roles must be present.
    assert len(data["roles_canonical"]) == 12
    # Every runtime produces a result entry (14: DeepSeek is a provider, not a runtime).
    assert len(data["results"]) == 14
    assert "deepseek" not in {row["runtime"] for row in data["results"]}
    portable = data["portable_validation"]
    assert portable["passed"] is True
    # A README and declared capabilities are not evidence of a runnable runtime.
    sa = next(r for r in data["results"] if r["runtime"] == "simplicio_agent")
    assert sa["available"] is False
    assert sa["external_lane"] == "unavailable"
    assert sa["sandbox_passed"] is False
    assert sa["receipt_equivalent"] is False
    assert "runtime binary" in sa["external_reason"]


def test_unknown_runtime_is_rejected():
    proc = _run(["not_a_runtime"])
    assert proc.returncode == 2
    assert "unknown runtime" in proc.stderr
