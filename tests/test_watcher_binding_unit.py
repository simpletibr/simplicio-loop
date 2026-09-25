import json
from pathlib import Path

import scripts.watcher_verify as watcher

_REAL_REPO = Path(__file__).resolve().parents[1]
_REAL_PROGRESS_JSONL = _REAL_REPO / ".simplicio/orchestrator/loop/progress.jsonl"


def _write_anchor_bundle(loop, challenge="c1"):
    (loop / "watcher_challenge.json").write_text(
        json.dumps({"challenge": challenge, "goal_fp": "fp1", "written_at": "2026-07-10T00:00:00Z"}),
        encoding="utf-8",
    )
    (loop / "anchor.json").write_text(
        json.dumps({"goal_fp": "fp1", "criteria": [{"id": "AC1", "status": "done"}]}),
        encoding="utf-8",
    )


def test_watcher_rejects_run_from_different_commit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio/orchestrator" / "loop"
    run = repo / ".simplicio/orchestrator" / "runs" / "r1"
    loop.mkdir(parents=True)
    run.mkdir(parents=True)
    watcher._set_repo(str(repo))
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setattr(watcher, "_git_meta", lambda *a, **k: {"commit_sha": "actual", "diff_hash": "same", "diff_present": False})
    _write_anchor_bundle(loop)
    (run / "evidence-receipt.json").write_text(json.dumps({"schema": "simplicio.evidence-receipt/v1", "run_id": "r1", "status": "VERIFIED", "run": {"commit_sha": "deadbeef", "diff_hash": "same"}, "criteria": [{"id": "AC1", "verification_state": "verified"}], "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1, "scenario_verified": 1, "rule_total": 0, "rule_verified": 0}, "checks": []}), encoding="utf-8")
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is False
    assert "run commit differs" in state["reported"]
    assert state["match"] is False
    assert "run commit differs" in state["reported"]


def test_watcher_accepts_independent_receipt_when_evidence_receipt_is_deferred(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio/orchestrator" / "loop"
    run = repo / ".simplicio/orchestrator" / "runs" / "r1"
    loop.mkdir(parents=True)
    run.mkdir(parents=True)
    watcher._set_repo(str(repo))
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setattr(watcher, "_git_meta", lambda *a, **k: {"commit_sha": "actual", "diff_hash": "same", "diff_present": False})
    _write_anchor_bundle(loop)
    (run / "independent-watcher-receipt.json").write_text(json.dumps({
        "schema": "simplicio.independent-watcher-receipt/v1",
        "run_id": "r1",
        "challenge": "c1",
        "status": "MEASURED",
        "match": True,
        "task_contract_hash": "task-hash",
        "plan_hash": "plan-hash",
        "commit_sha": "actual",
        "diff_hash": "same",
        "criteria_results": [{
            "id": "AC1",
            "status": "MEASURED",
            "match": True,
            "recomputed_result": "verified",
            "evidence_ids": ["impl-AC1"],
        }],
    }), encoding="utf-8")
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is True
    assert state["status"] == "MEASURED"
    assert state["run_id"] == "r1"
    assert state["task_contract_hash"] == "task-hash"
    assert state["criteria_results"][0]["evidence_ids"] == ["impl-AC1"]


def test_watcher_rejects_independent_receipt_with_mismatched_challenge(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio/orchestrator" / "loop"
    run = repo / ".simplicio/orchestrator" / "runs" / "r1"
    loop.mkdir(parents=True)
    run.mkdir(parents=True)
    watcher._set_repo(str(repo))
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setattr(watcher, "_git_meta", lambda *a, **k: {"commit_sha": "actual", "diff_hash": "same", "diff_present": False})
    _write_anchor_bundle(loop, challenge="expected-c1")
    (run / "independent-watcher-receipt.json").write_text(json.dumps({
        "schema": "simplicio.independent-watcher-receipt/v1",
        "run_id": "r1",
        "challenge": "stale-c1",
        "status": "MEASURED",
        "match": True,
        "task_contract_hash": "task-hash",
        "commit_sha": "actual",
        "diff_hash": "same",
        "criteria_results": [{
            "id": "AC1",
            "status": "MEASURED",
            "match": True,
            "recomputed_result": "verified",
            "evidence_ids": ["impl-AC1"],
        }],
    }), encoding="utf-8")
    assert watcher.cmd_verify() == 0
    state = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert state["match"] is False
    assert "independent watcher challenge does not match current challenge" in state["reported"]


def test_cmd_verify_on_redirected_repo_never_touches_the_real_repos_progress_state(tmp_path, monkeypatch):
    """#1290: `watcher_verify.cmd_verify()` writes its watcher_state.json under whatever repo
    `_set_repo()` last pointed it at (here, an isolated tmp repo) -- its fail-open progress
    hook (`_emit_progress` -> `loop_progress.emit_event`) must follow that SAME redirection,
    never fall back to `loop_progress`'s own default (this checkout's real
    `.simplicio/orchestrator/loop/progress.jsonl`). Regression for a leak where every unit test
    calling `cmd_verify()` in-process polluted the real repo's progress state as a side effect."""
    before = _REAL_PROGRESS_JSONL.read_bytes() if _REAL_PROGRESS_JSONL.is_file() else None

    repo = tmp_path / "repo"
    loop = repo / ".simplicio/orchestrator" / "loop"
    run = repo / ".simplicio/orchestrator" / "runs" / "r1"
    loop.mkdir(parents=True)
    run.mkdir(parents=True)
    watcher._set_repo(str(repo))
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setattr(watcher, "_git_meta",
                        lambda *a, **k: {"commit_sha": "actual", "diff_hash": "same", "diff_present": False})
    _write_anchor_bundle(loop)
    (run / "evidence-receipt.json").write_text(json.dumps({
        "schema": "simplicio.evidence-receipt/v1", "run_id": "r1", "status": "VERIFIED",
        "run": {"commit_sha": "actual", "diff_hash": "same"},
        "criteria": [{"id": "AC1", "verification_state": "verified"}],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                   "scenario_verified": 1, "rule_total": 0, "rule_verified": 0},
        "checks": [],
    }), encoding="utf-8")

    assert watcher.cmd_verify() == 0

    # The redirected (tmp) repo DID get a progress event -- the hook fired, just not at the
    # real repo's expense.
    assert (loop / "progress.jsonl").is_file()
    # The real repo's own progress state is byte-identical to before this test ran (or still
    # absent, if it was absent before).
    after = _REAL_PROGRESS_JSONL.read_bytes() if _REAL_PROGRESS_JSONL.is_file() else None
    assert after == before, "cmd_verify() on a redirected repo leaked a progress event into the real repo"
