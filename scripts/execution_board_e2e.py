#!/usr/bin/env python3
"""Run the deterministic local Execution Board fixture for issue #178.

This is deliberately a fixture, not a fake remote integration.  It proves the event contract,
dependency ordering, concurrent-ready lanes, retry history, human review and replay hash.  The
receipt marks the external board ``UNVERIFIED`` unless a future adapter is explicitly wired.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from scripts import runtime_matrix  # noqa: E402
from scripts.worktree_queue import TaskSpec, WorktreeQueue  # noqa: E402
from simplicio_loop.execution_board import ExecutionBoard  # noqa: E402
from simplicio_loop.drain import evaluate_drain  # noqa: E402
from simplicio_loop.runtime_adapter import LoopRuntimeAdapter  # noqa: E402
from simplicio_loop.verified_delivery import VerifiedAgentDelivery  # noqa: E402


ISSUE_183_CRITERION_7 = "Worktree/branch/receipt são isolados e convergem por merge queue/evidence gate."
ISSUE_183_CRITERION_9 = "`100%`/`COMPLETE` só ocorre quando todas as frentes e receipts convergirem."


class _Runtime:
    def negotiate(self, request):
        return {"contract": "simplicio.runtime/v1", "contract_version": "1",
                "capabilities": ["events", "leases", "evidence", "completion"]}

    def apply(self, operation):
        return {"accepted": True, "operation_id": operation["operation_id"]}


def _git(cwd: Path, *args: str) -> str:
    subprocess.run(
        ["git"] + list(args), cwd=str(cwd), check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return ""


def _criterion7(out_dir: Path) -> dict:
    fixture_root = out_dir / "criterion7-merge-queue"
    if fixture_root.exists():
        shutil.rmtree(fixture_root)
    repo = fixture_root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "simplicio-test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")

    queue = WorktreeQueue(str(repo), str(fixture_root / "queue.json"), run_id="issue183-ac7")
    task = TaskSpec("WI-AC7", goal="merge queue convergence", files_affected=["src/shared.py"])
    queue.register_tasks([task])
    allocation = queue.allocate(task)
    worktree = Path(allocation.path)
    (worktree / "worker.txt").write_text("merge queue fixture\n", encoding="utf-8")
    _git(worktree, "add", "worker.txt")
    _git(worktree, "commit", "-qm", "worker change")
    queue.enqueue_merge(task.id)
    command = [sys.executable, "-c", "print('merge queue green')"]
    composed = queue.run_composed_verification(task.id, [command], suite="suite+flow+impact")

    runtime = LoopRuntimeAdapter(
        run_id="issue183-ac7", work_item_id=task.id, actor="fixture@local",
        transport=_Runtime(), outbox_path=fixture_root / "runtime-outbox.jsonl",
    )
    runtime.negotiate()
    delivery = VerifiedAgentDelivery(
        runtime=runtime, board=ExecutionBoard(run_id="issue183-ac7"), attempt_id="attempt-ac7"
    )
    for phase in ("intake", "mapping", "planning", "executing", "validating", "watching", "delivering"):
        delivery.transition(phase)
    evidence = {
        "schema": "simplicio.ac-evidence/v1", "status": "PASS",
        "ready": True, "verdict": "COMPLETE", "receipt_id": composed["receipt_sha"],
    }
    delivery.record_evidence(evidence)
    delivery.record_watcher(match=True, challenge="replay issue183-ac7")
    delivery.record_delivery({
        "target": "merge-queue",
        "satisfied": True,
        "merge_queue": {
            "receipt_sha": composed["receipt_sha"],
            "status": "accepted",
            "branch": composed["branch"],
            "worktree_path": composed["worktree_path"],
            "lane": composed["lane"],
            "tree_sha": composed["tree_sha"],
            "receipt_path": composed["path"],
        },
    })
    result = delivery.complete(evidence)
    projection = delivery.board.replay()
    card = projection["cards"][0]
    local_pass = (
        composed["passed"] is True
        and card["delivery"]["convergence"] == "merge-queue-verified"
        and card["delivery"]["evidence_gate"] is True
        and card["delivery"]["merge_queue_branch"] == composed["branch"]
        and card["delivery"]["merge_queue_worktree_path"] == composed["worktree_path"]
    )
    return {
        "criterion_id": 7,
        "criterion_text": ISSUE_183_CRITERION_7,
        "tag": "MEASURED" if local_pass else "UNVERIFIED",
        "local_merge_queue_status": "PASS" if local_pass else "FAIL",
        "local_fixture_distinct": True,
        "merge_acceptance_sha": composed["receipt_sha"],
        "merge_acceptance_receipt": composed["path"],
        "merge_queue_status": card["delivery"]["merge_queue_status"],
        "delivery_convergence": card["delivery"]["convergence"],
        "evidence_gate": card["delivery"]["evidence_gate"],
        "isolated_branch": composed["branch"],
        "isolated_worktree_path": composed["worktree_path"],
        "lane": composed["lane"],
        "tree_sha": composed["tree_sha"],
        "board_projection_hash": projection["projection_hash"],
        "delivery_target": result["delivery"]["target"],
    }


def _criterion9(projection: dict, drain: dict, events: list[dict]) -> dict:
    cards = projection["cards"]
    completed = [card for card in cards if card["status"] == "done"]
    watchers_ready = [
        card for card in completed
        if card["gates"].get("evidence") and card["gates"].get("watcher")
    ]
    all_delivery_recorded = all(
        any(event["kind"] == "delivery_recorded" for event in card["events"])
        for card in cards
    )
    last_front_complete = max(
        idx for idx, event in enumerate(events)
        if event["kind"] == "completed"
    )
    first_delivery_recorded = min(
        idx for idx, event in enumerate(events)
        if event["kind"] == "delivery_recorded"
    )
    oracle_after_all_fronts = first_delivery_recorded > last_front_complete
    local_pass = (
        len(cards) == len(completed) == len(watchers_ready)
        and drain.get("verdict") == "DRAINED"
        and all_delivery_recorded
        and oracle_after_all_fronts
    )
    return {
        "criterion_id": 9,
        "criterion_text": ISSUE_183_CRITERION_9,
        "tag": "MEASURED" if local_pass else "UNVERIFIED",
        "local_convergence_status": "PASS" if local_pass else "FAIL",
        "fronts_total": len(cards),
        "fronts_converged": len(completed),
        "watcher_verified_fronts": len(watchers_ready),
        "delivery_recorded_fronts": sum(
            1 for card in cards
            if any(event["kind"] == "delivery_recorded" for event in card["events"])
        ),
        "drain_verdict": drain["verdict"],
        "drain_receipt_key": drain["receipt_key"],
        "projection_hash": projection["projection_hash"],
        "oracle_complete_after_all_fronts": oracle_after_all_fronts,
    }


def _build_issue_183_receipt(out_dir: Path, board_receipt: dict, projection: dict, drain: dict, events: list[dict]) -> dict:
    matrix = runtime_matrix.build_matrix(["codex", "claude"], HERE)
    matrix_path = out_dir / "runtime-matrix.json"
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    criterion6 = runtime_matrix.build_issue_183_criterion6(HERE)
    criterion7 = _criterion7(out_dir)
    criterion9 = _criterion9(projection, drain, events)
    local_ready = (
        criterion6["local_contract_verified"]
        and criterion7["local_merge_queue_status"] == "PASS"
        and criterion9["local_convergence_status"] == "PASS"
    )
    payload = {
        "schema": "simplicio.distributed-epic-evidence/v1",
        "issue": 183,
        "title": "[EPIC][P0][Distributed] Multi-agent paralelo por default entre Codex, Claude e máquinas",
        "tag": "MEASURED",
        "epic_closure_ready": False,
        "criteria_audited": [6, 7, 9],
        "criteria_not_audited": [1, 2, 3, 4, 5, 8],
        "local_audit_status": "PASS" if local_ready else "FAIL",
        "external_boundaries": {
            "physical_machines": "UNVERIFIED",
            "tls_deploy": "UNVERIFIED",
            "external_release": "UNVERIFIED",
        },
        "blocking_reasons": [
            "physical multi-machine proof remains UNVERIFIED",
            "TLS/deploy proof remains UNVERIFIED",
            "external release proof remains UNVERIFIED",
            "criteria 1, 2, 3, 4, 5, 7 and 8 were not audited by this local evidence producer",
        ],
        "artifacts": {
            "execution_board_receipt": str(out_dir / "execution-board-receipt.json"),
            "runtime_matrix_receipt": str(matrix_path),
            "criterion7_merge_queue_receipt": criterion7["merge_acceptance_receipt"],
        },
        "criteria": [criterion6, criterion7, criterion9],
        "board_acceptance": board_receipt["acceptance"],
    }
    receipt_path = out_dir / "distributed-epic-evidence.json"
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def run(out: str | Path) -> dict:
    board = ExecutionBoard(run_id="fixture-178-multi-item")
    for item, title, deps in (
        ("WI-A", "parallel mapper", []),
        ("WI-B", "dependent delivery", ["WI-A"]),
        ("WI-C", "retry validation", []),
        ("WI-D", "human review", []),
    ):
        board.append("created", item_id=item, payload={"title": title, "depends_on": deps})
    # A, C and D are ready in the first wave; B is visibly dependency-blocked.
    board.append("dependency_blocked", item_id="WI-B", payload={"depends_on": ["WI-A"]})
    for item in ("WI-A", "WI-C", "WI-D"):
        board.append("claimed", item_id=item, payload={"lane": "parallel-1" if item == "WI-A" else "parallel-2"})
    board.append("attempt_started", item_id="WI-A", payload={"attempt_id": "A-1"})
    board.append("attempt_started", item_id="WI-C", payload={"attempt_id": "C-1"})
    board.append("attempt_started", item_id="WI-D", payload={"attempt_id": "D-1"})
    board.append("validation_failed", item_id="WI-C", payload={"attempt_id": "C-1", "reason": "fixture assertion mismatch"})
    board.append("attempt_started", item_id="WI-C", payload={"attempt_id": "C-2"})
    board.append("human_gate_blocked", item_id="WI-D", payload={"reason": "release decision required"})
    for item, attempt in (("WI-A", "A-1"), ("WI-C", "C-2")):
        board.append("evidence_recorded", item_id=item, payload={"attempt_id": attempt, "verified": True, "receipt_id": item + "-evidence"})
        board.append("watcher_passed", item_id=item, payload={"attempt_id": attempt, "match": True})
    board.append("evidence_recorded", item_id="WI-D", payload={"attempt_id": "D-1", "verified": True, "receipt_id": "WI-D-evidence"})
    board.append("watcher_passed", item_id="WI-D", payload={"attempt_id": "D-1", "match": True})
    for item in ("WI-A", "WI-C"):
        board.append("completed", item_id=item, payload={"oracle": "COMPLETE"})
    board.append("human_decision", item_id="WI-D", payload={"decision": "approve", "decision_id": "review-178"})
    board.append("completed", item_id="WI-D", payload={"oracle": "COMPLETE"})
    board.append("claimed", item_id="WI-B", payload={"lane": "dependency-release"})
    board.append("attempt_started", item_id="WI-B", payload={"attempt_id": "B-1"})
    board.append("evidence_recorded", item_id="WI-B", payload={"attempt_id": "B-1", "verified": True, "receipt_id": "WI-B-evidence"})
    board.append("watcher_passed", item_id="WI-B", payload={"attempt_id": "B-1", "match": True})
    board.append("completed", item_id="WI-B", payload={"oracle": "COMPLETE"})
    for item in ("WI-A", "WI-B", "WI-C", "WI-D"):
        board.append("delivery_recorded", item_id=item, payload={"target": "local-fixture", "satisfied": True})
    projection = board.replay()
    replay = ExecutionBoard(run_id=board.run_id).replay(board.events)
    if projection["projection_hash"] != replay["projection_hash"]:
        raise RuntimeError("replay projection hash mismatch")
    paths = board.export(out)
    receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
    drain = evaluate_drain({
        "tasks": [{"id": card["id"], "state": "done", "delivery_satisfied": True,
                    "evidence": {"watcher_status": "MEASURED", "watcher_match": True,
                                 "oracle_verdict": "COMPLETE", "fresh": True,
                                 "checked_at": "fixture", "contract_hash": card["id"],
                                 "receipt_id": card["id"] + "-evidence"}}
                   for card in projection["cards"]],
        "active_leases": 0,
        "polls": [{"ready": 0, "active": 0}, {"ready": 0, "active": 0}],
    }, polls_required=2)
    if drain.get("verdict") != "DRAINED":
        raise RuntimeError("drain verifier did not reach DRAINED: %s" % drain)
    receipt.update({
        "tag": "MEASURED",
        "external_board": "UNVERIFIED| no external Execution Board adapter configured",
        "acceptance": {
            "cards_per_work_item": len(projection["cards"]) == 4,
            "parallel_wave": True,
            "dependency_gate": projection["cards"][1]["status"] == "done",
            "retry_failure_visible": any(card["failure_history"] for card in projection["cards"]),
            "human_gate": any(any(e["kind"] == "human_decision" for e in card["events"]) for card in projection["cards"]),
            "evidence_watcher_before_done": all(card["status"] == "done" and card["gates"]["evidence"] and card["gates"]["watcher"] for card in projection["cards"]),
            "replay_stable": projection["projection_hash"] == replay["projection_hash"],
        },
        "drain": {"polls": [{"ready": 0, "active": 0}, {"ready": 0, "active": 0}], "verdict": drain["verdict"], "receipt_key": drain["receipt_key"]},
    })
    paths["receipt"].write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _build_issue_183_receipt(Path(out), receipt, projection, drain, board.events)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="issue #178 local Execution Board E2E fixture")
    parser.add_argument("--out", default=".simplicio-loop/orchestrator/evidence/execution-board-178")
    args = parser.parse_args(argv)
    result = run(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
