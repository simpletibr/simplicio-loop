"""Acceptance tests for #153's worktree/conflict/merge-queue primitives."""
import json
import os
import subprocess
import sys

import pytest

from simplicio_loop.worktree_queue import TaskSpec, WorktreeQueue


import simplicio_loop.worktree_queue as queue_module


def _git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), check=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          close_fds=True).stdout.strip()


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "simplicio-test")
    (root / "README").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-qm", "base")
    return root


def _queue(tmp_path, repo, run="run1"):
    return WorktreeQueue(str(repo), str(tmp_path / "queue.json"), run_id=run)


def test_independent_tasks_get_distinct_worktrees_without_coordinator_checkout(tmp_path):
    repo = _repo(tmp_path)
    coordinator_head = _git(repo, "rev-parse", "HEAD")
    q = _queue(tmp_path, repo)
    a, b = TaskSpec("A", files_affected=["src/a.py"]), TaskSpec("B", files_affected=["src/b.py"])
    q.register_tasks([a, b])
    aa, bb = q.allocate(a), q.allocate(b)
    assert aa.path != str(repo) and bb.path != str(repo) and aa.path != bb.path
    assert aa.branch != bb.branch
    assert _git(repo, "rev-parse", "HEAD") == coordinator_head
    assert _git(aa.path, "rev-parse", "HEAD") == coordinator_head
    assert _git(bb.path, "rev-parse", "HEAD") == coordinator_head


def test_conflict_lanes_include_contracts_and_are_persisted(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    a = TaskSpec("A", files_affected=["src/shared.py"])
    b = TaskSpec("B", public_contracts=["api.v1"])
    c = TaskSpec("C", public_contracts=["api.v1"])
    q.register_tasks([a, b, c])
    graph = q.conflict_graph([a, b, c])
    assert graph["B"] == ["C"]
    state = q.state()
    assert state["lanes"]["B"] == state["lanes"]["C"]
    assert state["lanes"]["A"] != state["lanes"]["B"]


def test_restart_reattaches_by_persisted_run_and_task_id(tmp_path):
    repo = _repo(tmp_path)
    q1 = _queue(tmp_path, repo)
    original = q1.allocate(TaskSpec("A", files_affected=["a.py"]))
    # No run_id: the persisted state supplies the original namespace.
    q2 = WorktreeQueue(str(repo), str(tmp_path / "queue.json"))
    attached = q2.allocate(TaskSpec("A", files_affected=["a.py"]))
    assert attached.reattached
    assert attached.path == original.path
    assert attached.branch == original.branch


def test_merge_queue_reports_base_drift_with_repair_handoff(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    q.allocate(TaskSpec("A", files_affected=["a.py"]))
    (repo / "drift").write_text("drift\n", encoding="utf-8")
    _git(repo, "add", "drift")
    _git(repo, "commit", "-qm", "move base")
    candidate = q.enqueue_merge("A")
    assert candidate["status"] == "repair-required"
    handoff = json.loads(open(candidate["repair_handoff"], encoding="utf-8").read())
    assert handoff["frozen_base_sha"] != handoff["current_base_sha"]
    assert handoff["branch"] == candidate["branch"]


def test_composed_verification_receipt_is_hash_linked_and_not_delivery(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    q.allocate(TaskSpec("A"))
    q.enqueue_merge("A")
    command = [sys.executable, "-c", "print('composed green')"]
    receipt = q.run_composed_verification("A", [command], suite="suite+flow+impact")
    assert receipt["passed"] is True
    assert receipt["previous_receipt_sha"] == ""
    assert receipt["worktree_path"].endswith(os.path.join("run1", "A"))
    assert receipt["lane"].startswith("lane-")
    assert receipt["tree_sha"]
    assert q.state()["tasks"]["A"]["status"] == "accepted"
    assert q.state()["merge_queue"][0]["status"] == "accepted"
    assert q.state()["tasks"]["A"]["status"] != "delivered"


def test_generation_binding_is_pinned_to_worker_and_merge_candidate(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    q.allocate(TaskSpec("A", files_affected=["a.py"]))
    binding = {
        "schema": "simplicio.loop.generation-binding/v1",
        "candidate_id": "A",
        "mapper_generation": "mapper-1",
        "canonical_cache_key": "sha256:base",
        "overlay_path": str(tmp_path / "overlay-A"),
        "receipt_hash": "sha256:binding",
    }

    q.record_generation_binding("A", binding)
    candidate = q.enqueue_merge("A")

    assert q.state()["tasks"]["A"]["generation_binding_hash"] == "sha256:binding"
    assert candidate["generation_binding"] == {
        "schema": "simplicio.loop.generation-binding/v1",
        "mapper_generation": "mapper-1",
        "canonical_cache_key": "sha256:base",
        "overlay_path": str(tmp_path / "overlay-A"),
        "receipt_hash": "sha256:binding",
    }


def test_shared_checkout_requires_policy_and_one_owned_lock(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    with pytest.raises(ValueError):
        q.allocate(TaskSpec("A"), isolation="shared")
    q.allocate(TaskSpec("A"), isolation="shared", shared_policy=True)
    with pytest.raises(RuntimeError):
        q.allocate(TaskSpec("B"), isolation="shared", shared_policy=True)
    report = q.teardown("A")
    assert report.removed is True
    second = q.allocate(TaskSpec("B"), isolation="shared", shared_policy=True)
    assert second.mode == "shared"


def test_teardown_does_not_remove_unowned_path_and_reports_failure(tmp_path):
    repo = _repo(tmp_path)
    q = _queue(tmp_path, repo)
    q.allocate(TaskSpec("A"))
    state = q.state()
    state["tasks"]["A"]["path"] = str(tmp_path / "unrelated")
    with open(tmp_path / "queue.json", "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    report = q.teardown("A")
    assert report.removed is False
    assert "path-not-owned" in report.failures


def test_active_operator_context_blocks_teardown_and_preserves_receipt_fields(tmp_path):
    q = WorktreeQueue(str(tmp_path), str(tmp_path / "queue.json"), run_id="run-safety")
    state = q.state()
    state["tasks"]["A"] = {
        "task_id": "A", "run_id": "run-safety", "mode": "worktree",
        "path": str(tmp_path / "owned"), "branch": "simplicio/run-safety/A",
        "worktree_id": "run-safety:A", "lease": {"status": "held", "owner": "worker"},
        "terminal_handle": "term-exited",
        "owned": True,
    }
    q._write(state)
    q.record_context("A", {"terminal_handle": "term-delayed", "lease_owner": "worker", "active": True})
    report = q.teardown("A")
    assert report.removed is False
    assert report.failures == ["active-worktree"]
    entry = q.state()["tasks"]["A"]
    assert entry["terminal_handle"] == "term-delayed"
    assert entry["lease"]["owner"] == "worker"


def test_cleanup_receipt_requires_identity_and_is_hash_linked(tmp_path):
    q = WorktreeQueue(str(tmp_path), str(tmp_path / "queue.json"), run_id="run-safety")
    state = q.state()
    state["tasks"]["A"] = {
        "task_id": "A", "run_id": "run-safety", "mode": "worktree",
        "path": str(tmp_path / "owned"), "branch": "simplicio/run-safety/A",
        "worktree_id": "run-safety:A", "lease": {"status": "held", "owner": "worker"},
        "terminal_handle": "term-exited",
        "owned": True,
    }
    q._write(state)
    receipt = q.record_cleanup_receipt("A", {
        "worktree_id": "run-safety:A", "terminal_handle": "term-exited",
        "lease_owner": "worker", "cleanup_decision": "cleanup", "reason": "no_changes_confirmed",
    })
    assert receipt["receipt_sha"]
    assert q.state()["tasks"]["A"]["cleanup_receipt_sha"] == receipt["receipt_sha"]


def test_cleanup_receipt_must_match_lease_and_terminal_authority(tmp_path):
    q = WorktreeQueue(str(tmp_path), str(tmp_path / "queue.json"), run_id="run-safety")
    state = q.state()
    state["tasks"]["A"] = {
        "task_id": "A", "run_id": "run-safety", "mode": "worktree", "path": "",
        "branch": "simplicio/run-safety/A", "worktree_id": "run-safety:A",
        "terminal_handle": "real-terminal", "lease": {"status": "released", "owner": "real-owner"},
        "owned": True,
    }
    q._write(state)
    receipt = {"worktree_id": "run-safety:A", "terminal_handle": "forged",
               "lease_owner": "attacker", "cleanup_decision": "cleanup", "reason": "fake"}
    with pytest.raises(ValueError, match="lease_owner mismatch"):
        q.record_cleanup_receipt("A", receipt)
    receipt.update(lease_owner="real-owner")
    with pytest.raises(ValueError, match="terminal_handle mismatch"):
        q.record_cleanup_receipt("A", receipt)


def test_shared_lock_receipt_cannot_delete_path_outside_owned_root(tmp_path):
    q = WorktreeQueue(str(tmp_path), str(tmp_path / "queue.json"), run_id="run-safety")
    victim = tmp_path / "victim.json"
    victim.write_text(json.dumps({"run_id": "run-safety", "task_id": "A"}), encoding="utf-8")
    state = q.state()
    state["tasks"]["A"] = {
        "task_id": "A", "run_id": "run-safety", "mode": "shared", "path": "",
        "branch": "simplicio/run-safety/A", "owned": True,
        "lock_receipt": str(victim), "lease": {"status": "released"},
    }
    q._write(state)
    report = q.teardown("A")
    assert report.removed is False
    assert report.failures == ["lock-receipt-path-not-owned"]
    assert victim.exists()


def test_packaged_queue_mapping_cli_selftest_and_corrupt_state(tmp_path, monkeypatch, capsys):
    mapped = TaskSpec.from_mapping({"id": "mapped", "plan_files": ["src/a.py"], "contracts": ["api.v1"]})
    assert mapped.conflict_keys() == ["contract:api.v1", "path:src/a.py"]
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([{"id": "A", "files_affected": ["a.py"]}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["worktree_queue.py", "graph", "--tasks", str(tasks)])
    assert queue_module._cli() == 0
    assert "lane-" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["worktree_queue.py", "graph"])
    with pytest.raises(SystemExit):
        queue_module._cli()
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{broken", encoding="utf-8")
    queue = WorktreeQueue(str(tmp_path), str(corrupt), "corrupt")
    assert queue.state()["schema"] == queue_module.SCHEMA
    assert queue_module.selftest() == 0
    assert "selftest: ALL PASS" in capsys.readouterr().out


def test_packaged_queue_public_guards_and_failure_receipt(tmp_path):
    repo = _repo(tmp_path)
    queue = _queue(tmp_path, repo)
    with pytest.raises(ValueError, match="task id"):
        queue.allocate(TaskSpec(""))
    with pytest.raises(ValueError, match="isolation"):
        queue.allocate(TaskSpec("A"), isolation="invalid")
    with pytest.raises(KeyError, match="unknown task"):
        queue.snapshot("missing")
    with pytest.raises(ValueError, match="task_id"):
        queue.record_context("", {})
    with pytest.raises(KeyError, match="unknown task"):
        queue.record_context("missing", {})
    with pytest.raises(KeyError, match="unknown task"):
        queue.record_composed_verification("missing", True)

    queue.allocate(TaskSpec("A"))
    with pytest.raises(ValueError, match="not queued"):
        queue.record_composed_verification("A", True)
    queue.enqueue_merge("A")
    receipt = queue.run_composed_verification("A", [[]], suite="empty-command")
    assert receipt["passed"] is False
    assert receipt["details"]["commands"][0]["returncode"] == 2
    assert queue.composed_candidates() == []
    assert queue.cleanup_orphans(["missing"]) == []
    assert queue.teardown("missing").failures == ["unknown-task"]


def test_packaged_queue_rejects_frozen_base_and_bad_cleanup_receipts(tmp_path):
    repo = _repo(tmp_path)
    queue = _queue(tmp_path, repo)
    base = _git(repo, "rev-parse", "HEAD")
    queue.register_tasks([TaskSpec("A")], base_sha=base)
    with pytest.raises(ValueError, match="frozen base SHA"):
        queue.register_tasks([TaskSpec("B")], base_sha="0" * 40)
    with pytest.raises(ValueError, match="cleanup receipt missing"):
        queue.record_cleanup_receipt("A", {})
    with pytest.raises(ValueError, match="decision"):
        queue.record_cleanup_receipt("A", {
            "worktree_id": "", "terminal_handle": "done", "lease_owner": "worker",
            "cleanup_decision": "keep", "reason": "still active",
        })
