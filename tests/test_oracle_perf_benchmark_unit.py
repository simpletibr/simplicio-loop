"""Performance benchmark (#7 of the Definition-of-Done checklist) for the completion
oracle's hot path: `simplicio_loop.oracle.evaluate_completion` runs on every Stop-hook
invocation of the Ralph loop (`hooks/loop_stop.py`), i.e. once per turn of the main
orchestration loop. This is a lightweight timeit-based budget assertion (no
pytest-benchmark dependency required) that both prints a measured number and fails
the suite on a real regression.
"""
import json
import os
import sys
import timeit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simplicio_loop.oracle import evaluate_completion

ITERATIONS = 200
# Generous budget for a pure filesystem + JSON parse + regex hot path on any dev
# machine or CI runner; this is a regression guard, not a tight perf target.
BUDGET_SECONDS_PER_CALL = 0.05


def _seed_loop(loop):
    (loop / "scratchpad.md").write_text(
        '---\ncompletion_promise: "PERF_DONE"\n---\ngoal\n', encoding="utf-8"
    )
    (loop / "anchor.json").write_text(
        json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}), encoding="utf-8"
    )
    (loop / "watcher_challenge.json").write_text(
        json.dumps({"challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z"}),
        encoding="utf-8",
    )
    (loop / "watcher_state.json").write_text(
        json.dumps({
            "match": True, "status": "MEASURED", "checked_at": "2026-07-10T00:00:01Z",
            "challenge": "abc", "goal_fp": "",
        }),
        encoding="utf-8",
    )


def _seed_run(run_dir):
    (run_dir / "manifest.json").write_text(
        json.dumps({"schema": "simplicio.run-manifest/v1", "delivery_target": "verified"}),
        encoding="utf-8",
    )
    (run_dir / "task-contract.json").write_text(
        json.dumps({"schema": "simplicio.task-contract-collection/v1"}), encoding="utf-8"
    )
    (run_dir / "mapper-context.json").write_text(json.dumps({"handoff": {}}), encoding="utf-8")
    (run_dir / "operator-receipt.json").write_text(
        json.dumps({"schema": "simplicio.operator-receipt/v0"}), encoding="utf-8"
    )
    (run_dir / "evidence-receipt.json").write_text(
        json.dumps({
            "schema": "simplicio.evidence-receipt/v1",
            "status": "VERIFIED",
            "criteria": [{"id": "AC1", "verification_state": "verified"}],
            "summary": {"criteria_total": 1, "criteria_verified": 1,
                        "scenario_total": 1, "scenario_verified": 1,
                        "rule_total": 1, "rule_verified": 1},
        }),
        encoding="utf-8",
    )
    (run_dir / "delivery-receipt.json").write_text(
        json.dumps({
            "schema": "simplicio.delivery-receipt/v1",
            "target": "verified",
            "current_state": "verified",
            "ready": True,
            "source_kind": "local",
            "source_payload": {"evidence_receipt": "evidence-receipt.json", "criteria_verified": 1},
        }),
        encoding="utf-8",
    )
    # The completion oracle requires a quality-matrix receipt as part of the
    # run-artifacts gate (quality_matrix_gate). Seed a fully-passing matrix so the
    # success-path benchmark actually reaches ready=True.
    (run_dir / "quality-matrix.json").write_text(
        json.dumps({
            "schema": "simplicio.quality-matrix/v1",
            "coverage_threshold": 0.0,
            "coverage": {"measured": 100.0},
            "requirements": {
                "implementation": {"status": "pass", "proof_ref": "evidence-receipt.json"},
                "unit": {"status": "pass", "proof_ref": "evidence-receipt.json"},
                "integration": {"status": "pass", "proof_ref": "evidence-receipt.json"},
                "system": {"status": "pass", "proof_ref": "evidence-receipt.json"},
                "regression": {"status": "pass", "proof_ref": "evidence-receipt.json"},
                "benchmark": {"status": "pass", "proof_ref": "evidence-receipt.json"},
            },
        }),
        encoding="utf-8",
    )


def test_evaluate_completion_stays_within_time_budget(tmp_path):
    loop = tmp_path / ".simplicio-loop/orchestrator" / "loop"
    loop.mkdir(parents=True)
    run_dir = tmp_path / ".simplicio-loop/orchestrator" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    _seed_loop(loop)
    _seed_run(run_dir)
    response = "<promise>PERF_DONE</promise>"

    result = evaluate_completion(str(loop), str(run_dir), response_text=response)
    assert result["ready"] is True  # sanity: we are benchmarking the success path

    elapsed = timeit.timeit(
        lambda: evaluate_completion(str(loop), str(run_dir), response_text=response),
        number=ITERATIONS,
    )
    per_call = elapsed / ITERATIONS
    print(f"\n[perf] evaluate_completion: {per_call * 1000:.4f} ms/call over {ITERATIONS} calls "
          f"(budget {BUDGET_SECONDS_PER_CALL * 1000:.1f} ms/call)")
    assert per_call < BUDGET_SECONDS_PER_CALL, (
        f"evaluate_completion regressed to {per_call * 1000:.4f} ms/call, "
        f"budget is {BUDGET_SECONDS_PER_CALL * 1000:.1f} ms/call"
    )
