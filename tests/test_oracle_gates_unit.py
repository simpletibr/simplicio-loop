"""Direct in-process unit coverage of simplicio_loop.oracle's early-return gates.

tests/test_completion_oracle.py and tests/test_cli_oracle.py already exercise the oracle
end-to-end through the `scripts/completion_oracle.py` CLI subprocess (system-level coverage).
This file complements that with fast, in-process unit tests of `evaluate_completion` and its
private gate helpers for branches the CLI-level tests don't happen to trip (missing/corrupt
scratchpad, missing/blank promise, promise mismatch, missing anchor criteria, watcher
mismatch/staleness, flow-audit gap, missing run_dir).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simplicio_loop.oracle import _anchor_gate, _task_dispatch_gate, _watcher_gate, evaluate_completion


def _write_scratchpad(loop, promise='"DONE"', extra=""):
    (loop / "scratchpad.md").write_text(
        f"---\ncompletion_promise: {promise}\n{extra}---\ngoal\n", encoding="utf-8"
    )


def test_evaluate_completion_blocks_when_scratchpad_missing(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    result = evaluate_completion(str(loop))
    assert result["ready"] is False
    assert result["reason_code"] == "scratchpad_missing"


def test_evaluate_completion_blocks_when_scratchpad_frontmatter_corrupt(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    (loop / "scratchpad.md").write_text("no frontmatter here", encoding="utf-8")
    result = evaluate_completion(str(loop))
    assert result["ready"] is False
    assert result["reason_code"] == "scratchpad_corrupt"


def test_evaluate_completion_blocks_when_promise_missing(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='""')
    result = evaluate_completion(str(loop))
    assert result["ready"] is False
    assert result["reason_code"] == "promise_missing"


def test_evaluate_completion_blocks_when_promise_not_exact(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='"DONE"')
    result = evaluate_completion(str(loop), response_text="no promise tag here")
    assert result["ready"] is False
    assert result["reason_code"] == "promise_not_exact"

    result = evaluate_completion(str(loop), response_text="<promise>WRONG TEXT</promise>")
    assert result["ready"] is False
    assert result["reason_code"] == "promise_not_exact"


def test_evaluate_completion_reads_last_response_file_when_response_text_blank(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='"DONE"')
    (loop / "last_response.txt").write_text("<promise>DONE</promise>", encoding="utf-8")
    (loop / "anchor.json").write_text(json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}),
                                      encoding="utf-8")
    result = evaluate_completion(str(loop), response_text="   ")
    # promise now matches; next gate (anchor) passes too, so it fails later at watcher/run_dir,
    # never at promise_not_exact -- proves last_response.txt was actually read.
    assert result["reason_code"] != "promise_not_exact"


def test_evaluate_completion_blocks_when_anchor_criteria_pending(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='"DONE"')
    (loop / "anchor.json").write_text(json.dumps({
        "criteria": [{"id": "AC1", "status": "pending"}]
    }), encoding="utf-8")
    result = evaluate_completion(str(loop), response_text="<promise>DONE</promise>")
    assert result["ready"] is False
    assert result["reason_code"] == "anchor_pending"


def test_evaluate_completion_blocks_when_flow_gap_open(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='"DONE"')
    (loop / "anchor.json").write_text(json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}),
                                      encoding="utf-8")
    (loop / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z",
    }), encoding="utf-8")
    (loop / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "checked_at": "2026-07-10T00:00:01Z",
        "challenge": "abc", "goal_fp": "",
    }), encoding="utf-8")
    result = evaluate_completion(str(loop), response_text="<promise>DONE</promise>",
                                 flow_gap="unresolved decision Q1")
    assert result["ready"] is False
    assert result["reason_code"] == "flow_audit_required"


def test_evaluate_completion_blocks_when_run_dir_missing(tmp_path):
    loop = tmp_path / "loop"
    loop.mkdir()
    _write_scratchpad(loop, promise='"DONE"')
    (loop / "anchor.json").write_text(json.dumps({"criteria": [{"id": "AC1", "status": "done"}]}),
                                      encoding="utf-8")
    (loop / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "abc", "goal_fp": "", "written_at": "2026-07-10T00:00:00Z",
    }), encoding="utf-8")
    (loop / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "checked_at": "2026-07-10T00:00:01Z",
        "challenge": "abc", "goal_fp": "",
    }), encoding="utf-8")
    result = evaluate_completion(str(loop), response_text="<promise>DONE</promise>")
    assert result["ready"] is False
    assert result["reason_code"] == "run_dir_missing"


# ---------------------------------------------------------------------------
# _anchor_gate / _watcher_gate — direct unit coverage of every branch
# ---------------------------------------------------------------------------

def test_anchor_gate_missing_file(tmp_path):
    ok, gate, anchor = _anchor_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "anchor_missing"
    assert anchor is None


def test_anchor_gate_empty_criteria(tmp_path):
    (tmp_path / "anchor.json").write_text(json.dumps({"criteria": []}), encoding="utf-8")
    ok, gate, _anchor = _anchor_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "anchor_empty"


def test_watcher_gate_missing_files(tmp_path):
    ok, gate = _watcher_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "watcher_missing"


def test_watcher_gate_not_measured(tmp_path):
    (tmp_path / "watcher_challenge.json").write_text(json.dumps({"challenge": "a"}), encoding="utf-8")
    (tmp_path / "watcher_state.json").write_text(json.dumps({"match": False, "status": "UNVERIFIED"}),
                                                 encoding="utf-8")
    ok, gate = _watcher_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "watcher_mismatch"


def test_watcher_gate_challenge_mismatch(tmp_path):
    (tmp_path / "watcher_challenge.json").write_text(json.dumps({"challenge": "a"}), encoding="utf-8")
    (tmp_path / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "challenge": "b",
    }), encoding="utf-8")
    ok, gate = _watcher_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "watcher_challenge_mismatch"


def test_watcher_gate_goal_fingerprint_mismatch(tmp_path):
    (tmp_path / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "a", "goal_fp": "fp-1",
    }), encoding="utf-8")
    (tmp_path / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "challenge": "a", "goal_fp": "fp-2",
    }), encoding="utf-8")
    ok, gate = _watcher_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "watcher_goal_mismatch"


def test_watcher_gate_stale_receipt_predates_challenge(tmp_path):
    (tmp_path / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "a", "goal_fp": "", "written_at": "2026-07-10T10:00:00Z",
    }), encoding="utf-8")
    (tmp_path / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "challenge": "a", "goal_fp": "",
        "checked_at": "2026-07-10T09:00:00Z",
    }), encoding="utf-8")
    ok, gate = _watcher_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "watcher_stale"


# ---------------------------------------------------------------------------
# _task_dispatch_gate -- a run cannot be COMPLETE while any task it scheduled
# never produced a verified operator+evidence receipt (the false-VERIFIED
# regression: 9/10 tasks dead-lettered, only task 1 applied).
# ---------------------------------------------------------------------------

def test_task_dispatch_gate_passes_when_no_batch_dispatched_yet(tmp_path):
    ok, gate = _task_dispatch_gate(tmp_path)
    assert ok is True
    assert gate["reason_code"] == "task_dispatch_not_dispatched"


def test_task_dispatch_gate_blocks_on_dead_lettered_tasks_and_names_indices(tmp_path):
    (tmp_path / "task-contract.json").write_text(json.dumps({"tasks": [{}] * 10}), encoding="utf-8")
    (tmp_path / "operator-batch.json").write_text(json.dumps({
        "completed_task_indices": [1],
        "failed_task_indices": [],
        "blocked_task_indices": [],
        "dead_letter_task_indices": [2, 3, 4, 5, 6, 7, 8, 9, 10],
        "receipt_contract": {"ready": False, "missing_task_indices": [2, 3, 4, 5, 6, 7, 8, 9, 10]},
    }), encoding="utf-8")
    ok, gate = _task_dispatch_gate(tmp_path)
    assert ok is False
    assert gate["reason_code"] == "task_dispatch_incomplete"
    for index in range(2, 11):
        assert str(index) in gate["detail"]


def test_task_dispatch_gate_passes_when_every_task_completed(tmp_path):
    (tmp_path / "task-contract.json").write_text(json.dumps({"tasks": [{}, {}, {}]}), encoding="utf-8")
    (tmp_path / "operator-batch.json").write_text(json.dumps({
        "completed_task_indices": [1, 2, 3],
        "failed_task_indices": [],
        "blocked_task_indices": [],
        "dead_letter_task_indices": [],
        "receipt_contract": {"ready": True, "missing_task_indices": []},
    }), encoding="utf-8")
    ok, gate = _task_dispatch_gate(tmp_path)
    assert ok is True
    assert gate["reason_code"] == "task_dispatch_complete"


def test_watcher_gate_passes_when_everything_aligns(tmp_path):
    (tmp_path / "watcher_challenge.json").write_text(json.dumps({
        "challenge": "a", "goal_fp": "fp-1", "written_at": "2026-07-10T09:00:00Z",
    }), encoding="utf-8")
    (tmp_path / "watcher_state.json").write_text(json.dumps({
        "match": True, "status": "MEASURED", "challenge": "a", "goal_fp": "fp-1",
        "checked_at": "2026-07-10T10:00:00Z",
    }), encoding="utf-8")
    ok, gate = _watcher_gate(tmp_path)
    assert ok is True
    assert gate["reason_code"] == "watcher_verified"
