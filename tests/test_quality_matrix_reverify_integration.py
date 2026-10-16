"""#283: independent re-verification of the quality-matrix -- re-derives a lane's verdict
from RAW evidence (exit codes, commit shas, freshly re-executed gate output) instead of trusting
the receipt's self-reported ``status`` string. Covers both the TDD structural re-check
(`independent_reverify_tdd_lane`) and the full pass (`independent_reverify_quality_matrix`), plus
the `scripts/quality_matrix.py populate`/`tdd-red`/`tdd-green`/`reverify` CLI surface.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from simplicio_loop import quality_matrix as qm
from simplicio_loop.quality_matrix import (
    independent_reverify_quality_matrix,
    independent_reverify_tdd_lane,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- independent_reverify_tdd_lane: structural re-check, not a status re-parse -----------------


def test_tdd_lane_not_claimed_is_a_non_blocking_noop(tmp_path):
    gate = independent_reverify_tdd_lane(str(tmp_path), {"status": "unset"})
    assert gate["status"] == "pass"
    assert gate["reason_code"] == "quality_tdd_reverify_not_claimed"


def test_tdd_lane_claim_without_backing_receipts_is_rejected(tmp_path):
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "fail"
    assert gate["reason_code"] == "quality_tdd_reverify_receipt_missing"


def test_tdd_lane_genuine_red_green_receipts_pass(tmp_path):
    _write_json(tmp_path / "tdd-red-receipt.json", {"test_id": "t", "exit_code": 1, "commit_sha": "aaa111"})
    _write_json(tmp_path / "tdd-green-receipt.json", {"test_id": "t", "exit_code": 0, "commit_sha": "bbb222"})
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "pass", gate


def test_tdd_lane_rejects_red_receipt_that_did_not_actually_fail(tmp_path):
    # A self-reported "pass" whose RED receipt shows exit_code 0 is a lie about the raw evidence.
    _write_json(tmp_path / "tdd-red-receipt.json", {"test_id": "t", "exit_code": 0, "commit_sha": "aaa111"})
    _write_json(tmp_path / "tdd-green-receipt.json", {"test_id": "t", "exit_code": 0, "commit_sha": "bbb222"})
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "fail"
    assert gate["reason_code"] == "quality_tdd_reverify_red_not_failing"


def test_tdd_lane_rejects_green_receipt_that_did_not_actually_pass(tmp_path):
    _write_json(tmp_path / "tdd-red-receipt.json", {"test_id": "t", "exit_code": 1, "commit_sha": "aaa111"})
    _write_json(tmp_path / "tdd-green-receipt.json", {"test_id": "t", "exit_code": 1, "commit_sha": "bbb222"})
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "fail"
    assert gate["reason_code"] == "quality_tdd_reverify_green_not_passing"


def test_tdd_lane_rejects_mismatched_test_ids(tmp_path):
    _write_json(tmp_path / "tdd-red-receipt.json", {"test_id": "t1", "exit_code": 1, "commit_sha": "aaa111"})
    _write_json(tmp_path / "tdd-green-receipt.json", {"test_id": "t2", "exit_code": 0, "commit_sha": "bbb222"})
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "fail"
    assert gate["reason_code"] == "quality_tdd_reverify_test_id_mismatch"


def test_tdd_lane_rejects_identical_commits_between_red_and_green(tmp_path):
    # Same commit for both => nothing proven to have changed between the failing and passing run.
    _write_json(tmp_path / "tdd-red-receipt.json", {"test_id": "t", "exit_code": 1, "commit_sha": "aaa111"})
    _write_json(tmp_path / "tdd-green-receipt.json", {"test_id": "t", "exit_code": 0, "commit_sha": "aaa111"})
    entry = {"status": "pass", "red_proof_ref": "tdd-red-receipt.json", "green_proof_ref": "tdd-green-receipt.json"}
    gate = independent_reverify_tdd_lane(str(tmp_path), entry)
    assert gate["status"] == "fail"
    assert gate["reason_code"] == "quality_tdd_reverify_no_commit_delta"


# --- independent_reverify_quality_matrix: whole-receipt independent pass ------------------------


def _base_receipt(**overrides):
    receipt = {
        "schema": "simplicio.quality-matrix/v1",
        "coverage_threshold": 85,
        "requirements": {
            name: {"status": "pass", "proof_ref": f"tests/{name}"}
            for name in ("implementation", "unit", "integration", "system")
        },
        "coverage": {"measured": 90.0},
    }
    receipt.update(overrides)
    return receipt


def test_reverify_agrees_when_self_reported_ready_and_no_rerun_requested(tmp_path):
    # "regression" is not NOT_APPLICABLE-eligible (only "benchmark" is, per the issue text
    # verbatim) -- so both lanes here are claimed "pass". `rerun=False` isolates the aggregate
    # agreement logic from environment-dependent live gate re-execution (covered separately by
    # the CLI-level populate/reverify tests, which exercise a real subprocess re-run).
    receipt = _base_receipt(policy={"allow_justified_not_applicable": True})
    receipt["requirements"]["regression"] = {"status": "pass", "proof_ref": "tests/regression"}
    receipt["requirements"]["benchmark"] = {"status": "not_applicable", "justification": "no perf-sensitive path"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=False)
    assert verdict["ready"] is True, verdict
    assert verdict["self_reported"]["ready"] is True


def test_reverify_catches_a_self_reported_pass_with_no_tdd_evidence_backing(tmp_path):
    receipt = _base_receipt(policy={"tdd_required": True, "allow_justified_not_applicable": True})
    receipt["requirements"]["tdd"] = {
        "status": "pass", "red_proof_ref": "nonexistent-red.json", "green_proof_ref": "nonexistent-green.json",
    }
    receipt["requirements"]["regression"] = {"status": "pass", "proof_ref": "tests/regression"}
    receipt["requirements"]["benchmark"] = {"status": "not_applicable", "justification": "no perf-sensitive path"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    # Self-reported evaluator alone is satisfied (two distinct non-empty string refs)...
    from simplicio_loop.quality_matrix import evaluate_quality_matrix
    assert evaluate_quality_matrix(str(tmp_path))["ready"] is True
    # ...but independent re-verification catches that the refs don't resolve to real evidence.
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=False)
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_tdd_reverify_receipt_missing"


def test_reverify_missing_receipt_is_not_ready(tmp_path):
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=False)
    assert verdict["ready"] is False
    assert verdict["self_reported"]["reason_code"] == "quality_matrix_missing"


# --- coverage drift: a receipt claiming MORE than a fresh coverage_gate.py re-run measures -------


def test_reverify_catches_coverage_drift(tmp_path, monkeypatch):
    """A receipt claiming 95% coverage when an independent, fresh re-run of coverage_gate.py
    just measured 70% must be refused -- the receipt is never trusted over a live probe."""
    receipt = _base_receipt()
    receipt["requirements"]["regression"] = {"status": "pass", "proof_ref": "tests/regression"}
    receipt["requirements"]["benchmark"] = {"status": "pass", "proof_ref": "tests/benchmark"}
    receipt["coverage"] = {"measured": 95.0}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")

    monkeypatch.setattr(qm, "_rerun_coverage_gate", lambda repo: 70.0)
    monkeypatch.setattr(qm, "_rerun_gate_script", lambda script, argv, repo: (True, "stubbed pass"))
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=True)
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_coverage_drift"


def test_reverify_accepts_coverage_within_measured_bounds(tmp_path, monkeypatch):
    """A claimed coverage at/below what the fresh probe measures is not drift."""
    receipt = _base_receipt()
    receipt["requirements"]["regression"] = {"status": "pass", "proof_ref": "tests/regression"}
    receipt["requirements"]["benchmark"] = {"status": "pass", "proof_ref": "tests/benchmark"}
    receipt["coverage"] = {"measured": 88.0}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")

    monkeypatch.setattr(qm, "_rerun_coverage_gate", lambda repo: 90.0)
    monkeypatch.setattr(qm, "_rerun_gate_script", lambda script, argv, repo: (True, "stubbed pass"))
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=True)
    assert verdict["ready"] is True, verdict
    coverage_checks = [c for c in verdict["lane_checks"] if c["name"] == "coverage"]
    assert coverage_checks and coverage_checks[0]["status"] == "pass"
    assert coverage_checks[0]["reason_code"] == "quality_coverage_reverify_verified"


def test_reverify_skips_drift_check_when_coverage_unmeasurable(tmp_path, monkeypatch):
    """If the independent probe can't produce a number (script missing/broken env), the drift
    check is skipped rather than fabricating a pass or fail."""
    receipt = _base_receipt()
    receipt["requirements"]["regression"] = {"status": "pass", "proof_ref": "tests/regression"}
    receipt["requirements"]["benchmark"] = {"status": "pass", "proof_ref": "tests/benchmark"}
    receipt["coverage"] = {"measured": 95.0}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")

    monkeypatch.setattr(qm, "_rerun_coverage_gate", lambda repo: None)
    monkeypatch.setattr(qm, "_rerun_gate_script", lambda script, argv, repo: (True, "stubbed pass"))
    verdict = independent_reverify_quality_matrix(str(tmp_path), repo=REPO, rerun=True)
    assert verdict["ready"] is True, verdict
    coverage_checks = [c for c in verdict["lane_checks"] if c["name"] == "coverage"]
    assert coverage_checks and coverage_checks[0]["reason_code"] == "quality_coverage_reverify_unmeasurable"


def test_rerun_coverage_gate_returns_none_when_script_missing(tmp_path):
    assert qm._rerun_coverage_gate(str(tmp_path)) is None


# --- CLI: populate / tdd-red / tdd-green / reverify ---------------------------------------------


def test_cli_populate_fills_regression_and_justified_na_benchmark(tmp_path):
    # #283: unit/integration/system are now ALSO auto-filled by populate (via
    # scripts/test_categories.py) -- explicitly skipped here since this test targets
    # regression/benchmark only and those three lanes take much longer to actually execute
    # (see test_cli_populate_fills_unit_and_system_categories below for that coverage).
    proc = subprocess.run(
        [PY, os.path.join(REPO, "scripts", "quality_matrix.py"), "populate",
         "--run-dir", str(tmp_path), "--base", "HEAD", "--benchmark-na", "smoke test, no perf path touched",
         "--skip-coverage", "--skip-unit", "--skip-integration", "--skip-system"],
        cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert proc.returncode in (0, 1), proc.stderr  # 1 is expected: implementation/unit/etc still unset
    receipt = json.loads((tmp_path / "quality-matrix.json").read_text(encoding="utf-8"))
    assert receipt["requirements"]["regression"]["status"] in ("pass", "fail")
    assert (tmp_path / "regression-gate-report.json").exists()
    assert receipt["requirements"]["benchmark"] == {
        "status": "not_applicable", "justification": "smoke test, no perf path touched",
    }
    assert receipt["policy"]["allow_justified_not_applicable"] is True


@pytest.mark.external_integration
def test_cli_populate_fills_unit_and_system_categories(tmp_path):
    # #283: the per-category test-runner split (scripts/test_categories.py) auto-fills unit and
    # system the same way regression/benchmark/coverage were already auto-filled -- `system` is
    # the fast lane (one file) so this stays cheap; `unit` legitimately takes tens of seconds
    # (346 real tests), hence the wider timeout. populate has no knob that shrinks the unit tier, so the
    # budget is the tier's real cost on a loaded 2-CPU host (measured: over 180 s there, which failed it).
    proc = subprocess.run(
        [PY, os.path.join(REPO, "scripts", "quality_matrix.py"), "populate",
         "--run-dir", str(tmp_path), "--base", "HEAD",
         "--skip-coverage", "--skip-integration", "--skip-regression", "--skip-benchmark"],
        cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=1500,
    )
    assert proc.returncode in (0, 1), proc.stderr
    receipt = json.loads((tmp_path / "quality-matrix.json").read_text(encoding="utf-8"))
    assert receipt["requirements"]["unit"]["status"] == "pass", receipt["requirements"]["unit"]
    assert receipt["requirements"]["system"]["status"] == "pass", receipt["requirements"]["system"]
    assert (tmp_path / "unit-test-gate-report.json").exists()
    assert (tmp_path / "system-test-gate-report.json").exists()


def test_cli_tdd_red_rejects_a_test_that_is_already_passing(tmp_path):
    # A trivially-true test (e.g. `assert True`) can't be captured as a genuine RED. The probe
    # test file must live inside the repo's own tests/ tree -- tdd-red runs pytest with cwd=REPO,
    # and this repo's pytest rootdir/conftest is not set up to collect a file from an unrelated
    # external directory (e.g. a pytest tmp_path from the *outer* test run).
    probe = None
    try:
        probe = os.path.join(REPO, "tests", "_tmp_tdd_probe_always_true.py")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("def test_probe_always_true():\n    assert True\n")
        proc = subprocess.run(
            [PY, os.path.join(REPO, "scripts", "quality_matrix.py"), "tdd-red",
             "--run-dir", str(tmp_path), "--test-id", "tests/_tmp_tdd_probe_always_true.py::test_probe_always_true"],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
        )
        assert proc.returncode == 1, proc.stdout + proc.stderr
        receipt = json.loads((tmp_path / "tdd-red-receipt.json").read_text(encoding="utf-8"))
        assert receipt["exit_code"] == 0
    finally:
        if probe and os.path.exists(probe):
            os.remove(probe)


def test_cli_tdd_green_requires_a_prior_red_receipt(tmp_path):
    proc = subprocess.run(
        [PY, os.path.join(REPO, "scripts", "quality_matrix.py"), "tdd-green",
         "--run-dir", str(tmp_path), "--test-id", "tests/test_quality_matrix_unit.py::test_default_threshold_is_eighty_five"],
        cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert proc.returncode == 1
    assert "run tdd-red first" in (proc.stdout + proc.stderr)


def test_cli_reverify_reports_ready_false_json(tmp_path):
    (tmp_path / "quality-matrix.json").write_text(json.dumps({
        "schema": "simplicio.quality-matrix/v1", "coverage_threshold": 85, "requirements": {},
        "coverage": {"measured": None},
    }), encoding="utf-8")
    proc = subprocess.run(
        [PY, os.path.join(REPO, "scripts", "quality_matrix.py"), "reverify",
         "--run-dir", str(tmp_path), "--no-rerun"],
        cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ready"] is False


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_quality_matrix_reverify")
