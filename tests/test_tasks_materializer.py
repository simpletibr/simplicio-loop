import json
import re
from pathlib import Path

import pytest

from simplicio_loop.tasks_materializer import ContractMaterializationError, LoopRunContractMaterializer
from simplicio_loop.runner import _operator_dispatch_item

def intake():
    return {"run_identity": {"run_id": "batch-1"}, "items": {"7": {"state": "planned", "title": "Do work", "source_revision": "rev-7", "planning_receipt": "plan-7", "base_ref": "origin/main", "base_sha": "a" * 40, "acceptance_criteria": [{"statement": "the check passes"}, {"statement": "the package smoke passes"}]}, "8": {"state": "remote_closed", "title": "Skip"}}}

def test_materializes_canonical_run_and_authorized_worktree_item(tmp_path):
    calls = []
    def arm(repo, task_path, delivery, max_iterations):
        calls.append((repo, Path(task_path).read_text(encoding="utf-8"), delivery, max_iterations))
        run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-7"
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text(json.dumps({"steps": [{"candidate_targets": ["src/a.py"]}]}), encoding="utf-8")
        (run_dir / "state.json").write_text(json.dumps({"phase": "awaiting_decision"}), encoding="utf-8")
        return {"manifest": {"run_id": "run-7"}, "state": {"phase": "awaiting_decision"}, "run_dir": str(run_dir)}
    rows = LoopRunContractMaterializer(str(tmp_path), arm=arm)(intake())
    assert len(rows) == 1
    assert rows[0]["task_id"] == "issue-7"
    assert rows[0]["isolation"] == "worktree"
    assert rows[0]["task_spec"]["files_affected"] == ["src/a.py"]
    authority = rows[0]["authority_receipt"]
    assert set(authority) == {"request", "source", "command", "targets", "operator", "receipt_hash"}
    assert authority["targets"] == ["src/a.py"]
    assert authority["operator"] == "simplicio-dev-cli"
    assert "the check passes" in calls[0][1]
    assert "the package smoke passes" in calls[0][1]
    assert "Cenário 2" in calls[0][1]
    normalized = _operator_dispatch_item(rows[0])
    assert normalized["authority_receipt"] == authority
    tampered = dict(rows[0], authority_receipt=dict(authority, targets=["src/other.py"]))
    with pytest.raises(ValueError, match="hash mismatch"):
        _operator_dispatch_item(tampered)

def test_materialization_fails_closed_on_blocked_preflight(tmp_path):
    def arm(*args):
        return {"state": {"phase": "blocked", "blockers": ["mapper stale"]}}
    with pytest.raises(ContractMaterializationError, match="mapper stale"):
        LoopRunContractMaterializer(str(tmp_path), arm=arm)(intake())


def test_replay_reuses_persisted_run_without_rearming(tmp_path):
    calls = []
    def arm(repo, task_path, delivery, max_iterations):
        calls.append(task_path)
        run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-7"
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(json.dumps({"phase": "awaiting_decision"}), encoding="utf-8")
        (run_dir / "plan.json").write_text(json.dumps({"steps": [{"candidate_targets": ["src/a.py"]}]}), encoding="utf-8")
        return {"manifest": {"run_id": "run-7"}, "state": {"phase": "awaiting_decision"}, "run_dir": str(run_dir)}
    materialize = LoopRunContractMaterializer(str(tmp_path), arm=arm)
    assert materialize(intake()) == materialize(intake())
    assert len(calls) == 1
    receipt = json.loads((tmp_path / ".simplicio-loop" / "tasks-run" / "batch-1" / "materialization-receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "simplicio.tasks-materialization-receipt/v1"

    assert receipt["receipt_hash"]


def test_replay_rejects_tampered_hash_and_escaped_run_dir(tmp_path):
    materialize = LoopRunContractMaterializer(str(tmp_path), arm=lambda *args: None)
    receipt_path = tmp_path / ".simplicio-loop" / "tasks-run" / "batch-1" / "materialization-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({"schema": "simplicio.tasks-materialization-receipt/v1", "items": {}, "receipt_hash": "tampered"}), encoding="utf-8")
    with pytest.raises(ContractMaterializationError, match="receipt hash"):
        materialize(intake())

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.json").write_text(json.dumps({"phase": "awaiting_decision"}), encoding="utf-8")
    (outside / "plan.json").write_text(json.dumps({"steps": [{"candidate_targets": ["src/a.py"]}]}), encoding="utf-8")
    with pytest.raises(ContractMaterializationError, match="escapes canonical"):
        materialize._row("7", intake()["items"]["7"], {"manifest": {"run_id": "run-7"}, "run_dir": str(outside)})

def test_corrupt_replay_receipt_fails_closed_without_rearming(tmp_path):
    receipt = tmp_path / ".simplicio-loop" / "tasks-run" / "batch-1" / "materialization-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{broken", encoding="utf-8")
    calls = []
    with pytest.raises(ContractMaterializationError, match="invalid materialization receipt"):
        LoopRunContractMaterializer(str(tmp_path), arm=lambda *args: calls.append(args))(intake())
    assert calls == []


def test_canonical_git_base_flows_from_materializer_to_merge_receipt(tmp_path):
    import subprocess
    from simplicio_loop.tasks_materializer import _git_text
    from simplicio_loop.tasks_stage_pipeline import _coordinator_merge_receipt
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "base").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "base"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    feature_ref = "feature&echo-PWNED"
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-qb", feature_ref], check=True)
    (tmp_path / "feature").write_text("feature", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "feature"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "feature"], check=True)
    feature_sha = _git_text(tmp_path, "rev-parse", "--verify", feature_ref)
    assert re.fullmatch(r"[0-9a-f]{40}", feature_sha)
    assert _git_text(tmp_path, "rev-parse", "--verify", 'missing"&echo PWNED>PWNED&"') == ""
    assert not (tmp_path / "PWNED").exists()
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "master"], check=True)
    (tmp_path / "main").write_text("main", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "main"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "main"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
    run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-7"
    run_dir.mkdir(parents=True)
    (run_dir / "plan.json").write_text(json.dumps({"steps": [{"candidate_targets": ["src/a.py"]}]}), encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps({"phase": "awaiting_decision"}), encoding="utf-8")
    item = dict(intake()["items"]["7"])
    item.pop("base_ref")
    item.pop("base_sha")
    row = LoopRunContractMaterializer(str(tmp_path), arm=lambda *args: {
        "manifest": {"run_id": "run-7"}, "run_dir": str(run_dir)})
    materialized = row._row("7", item, {"manifest": {"run_id": "run-7"}, "run_dir": str(run_dir)})
    subprocess.run(["git", "-C", str(tmp_path), "merge", "--no-ff", "-qm", "merge", feature_ref], check=True)
    merge_sha = (tmp_path / ".git" / "refs" / "heads" / "master").read_text(encoding="utf-8").strip()
    worker = dict(materialized, worktree_path=str(tmp_path), branch=feature_ref, admission_fence=3)
    receipt = _coordinator_merge_receipt(
        {"pr_url": "https://github.com/acme/widgets/pull/7", "pr_repo": "acme/widgets",
         "merge_receipt": {"merge_commit_sha": merge_sha}}, worker)
    assert receipt is not None
    assert receipt["base_ref"] == "origin/main"
    assert receipt["base_sha"] == materialized["expected_base_sha"]
