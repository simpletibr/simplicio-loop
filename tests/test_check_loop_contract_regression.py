"""Regression test: `scripts/check_loop_contract.py` must stay green under pytest, not only
under the `scripts/check.py` local gate. This directly guards against the class of bug just
fixed here — a fixture (`converge-success`, `evidence-gated-done/satisfied`) that predates a
tightened `simplicio_loop/oracle.py` completion-oracle requirement (the `.simplicio-loop/orchestrator/runs/
<run-id>/` artifact bundle) and can therefore never reach `ready: true`, so `hooks/loop_stop.py`
never honors its `<promise>` and the fixture silently drifts from the real producer it claims to
describe.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "check_loop_contract.py")


def _run(*args):
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        capture_output=True, text=True, cwd=REPO, stdin=subprocess.DEVNULL, timeout=120,
    )


def test_check_loop_contract_passes_all_fixtures():
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout


def test_converge_success_and_evidence_gated_done_satisfied_fixtures_ship_run_artifacts():
    # Belt-and-suspenders: assert the specific artifact bundle exists on disk for the two
    # fixtures that were stale (no `.simplicio-loop/orchestrator/runs/<run-id>/` at all) before this fix, so a
    # future edit that deletes the bundle again fails here even before check_loop_contract runs.
    required = {
        "manifest.json", "task-contract.json", "mapper-context.json",
        "operator-receipt.json", "evidence-receipt.json", "delivery-receipt.json",
    }
    for rel in ("converge-success", os.path.join("evidence-gated-done", "satisfied")):
        fixture_dir = os.path.join(REPO, "contracts", "loop-execution", "v1", "fixtures", rel)
        runs_dir = os.path.join(fixture_dir, ".simplicio-loop/orchestrator", "runs")
        assert os.path.isdir(runs_dir), f"{rel}: missing .simplicio-loop/orchestrator/runs/ directory"
        run_ids = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))]
        assert run_ids, f"{rel}: .simplicio-loop/orchestrator/runs/ has no run directory"
        present = set(os.listdir(os.path.join(runs_dir, run_ids[0])))
        missing = required - present
        assert not missing, f"{rel}/{run_ids[0]}: missing artifact(s) {missing}"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_check_loop_contract_regression")
