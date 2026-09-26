"""#283: scripts/watcher_verify.py cmd_verify() independently re-derives the quality-matrix
verdict (simplicio_loop.quality_matrix.independent_reverify_quality_matrix) rather than trusting
quality-matrix.json's self-reported status, and attaches a `quality_gate` block to the watcher
receipt in the shape the issue calls for ("quality_gate": "VERIFIED"/"BLOCKED"/"NOT_PRESENT").
"""
import json

import scripts.watcher_verify as watcher


def _write_anchor_bundle(loop, challenge="c1"):
    (loop / "watcher_challenge.json").write_text(
        json.dumps({"challenge": challenge, "goal_fp": "fp1", "written_at": "2026-07-10T00:00:00Z"}),
        encoding="utf-8",
    )
    (loop / "anchor.json").write_text(
        json.dumps({"goal_fp": "fp1", "criteria": [{"id": "AC1", "status": "done"}]}),
        encoding="utf-8",
    )


def _write_evidence(run):
    (run / "evidence-receipt.json").write_text(json.dumps({
        "schema": "simplicio.evidence-receipt/v1", "run_id": "r1", "status": "VERIFIED",
        "run": {"commit_sha": "actual", "diff_hash": "same"},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": ["p1"]}],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                    "scenario_verified": 1, "rule_total": 0, "rule_verified": 0},
        "checks": [],
    }), encoding="utf-8")


def _setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio-loop/orchestrator" / "loop"
    run = repo / ".simplicio-loop/orchestrator" / "runs" / "r1"
    loop.mkdir(parents=True)
    run.mkdir(parents=True)
    watcher._set_repo(str(repo))
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setattr(watcher, "_git_meta", lambda *a, **k: {"commit_sha": "actual", "diff_hash": "same", "diff_present": False})
    _write_anchor_bundle(loop)
    _write_evidence(run)
    return repo, loop, run


def test_no_quality_matrix_receipt_is_not_present_and_does_not_block(tmp_path, monkeypatch):
    _repo, loop, _run = _setup(tmp_path, monkeypatch)
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["quality_gate"] == "NOT_PRESENT"
    assert state["match"] is True  # unaffected: nothing to independently re-verify


def test_independent_reverification_failure_blocks_the_watcher_match(tmp_path, monkeypatch):
    _repo, loop, run = _setup(tmp_path, monkeypatch)
    (run / "quality-matrix.json").write_text(json.dumps({"schema": "simplicio.quality-matrix/v1"}), encoding="utf-8")
    monkeypatch.setattr(watcher, "independent_reverify_quality_matrix", lambda *a, **k: {
        "ready": False, "reason_code": "quality_regression_reverify_mismatch",
        "reason": "claimed regression pass but a fresh re-run now fails",
        "self_reported": {"ready": True}, "lane_checks": [],
    })
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["quality_gate"] == "BLOCKED"
    assert state["match"] is False
    assert "quality-matrix independent re-verification failed" in state["reported"]


def test_independent_reverification_success_is_verified_and_does_not_block(tmp_path, monkeypatch):
    _repo, loop, run = _setup(tmp_path, monkeypatch)
    (run / "quality-matrix.json").write_text(json.dumps({"schema": "simplicio.quality-matrix/v1"}), encoding="utf-8")
    monkeypatch.setattr(watcher, "independent_reverify_quality_matrix", lambda *a, **k: {
        "ready": True, "reason_code": "quality_matrix_reverified",
        "reason": "self-reported verdict and independent re-verification agree",
        "self_reported": {"ready": True}, "lane_checks": [],
    })
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["quality_gate"] == "VERIFIED"
    assert state["match"] is True


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_watcher_quality_gate_reverify")
