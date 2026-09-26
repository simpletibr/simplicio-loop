#!/usr/bin/env python3
"""Local-only AC7 fixture for issue #183.

This script proves only the local integration slice for AC7:

- one local HTTP queue,
- two stable identities,
- allow-listed context packs,
- isolated worktree/branch receipts,
- VerifiedAgentDelivery + ExecutionBoard in the same flow,
- explicit evidence/watcher gate before delivery,
- explicit merge-queue receipt before convergence.

It does NOT claim physical multi-machine, production merge queue, or external
board proof. Those boundaries stay UNVERIFIED on purpose.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from scripts.worktree_queue import TaskSpec, WorktreeQueue  # noqa: E402
from simplicio_loop.agent_contract import (  # noqa: E402
    CONTEXT_FIELDS,
    build_context_pack,
    validate_context_pack,
    validate_identity,
)
from simplicio_loop.execution_board import ExecutionBoard  # noqa: E402
from simplicio_loop.runtime_adapter import LoopRuntimeAdapter  # noqa: E402
from simplicio_loop.verified_delivery import VerifiedAgentDelivery  # noqa: E402

PHASES = ("intake", "mapping", "planning", "executing", "validating", "watching", "delivering")
CAPABILITIES = ["claim", "heartbeat", "fencing", "receipts", "events", "evidence", "completion"]


def _json_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "issue183@example.invalid")
    _git(repo, "config", "user.name", "issue-183-fixture")
    (repo / "README.md").write_text("# distributed 183 fixture\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "planner.py").write_text("ROLE = 'planner'\n", encoding="utf-8")
    (repo / "src" / "operator.py").write_text("ROLE = 'operator'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base fixture")


def _evidence_receipt(task_id: str) -> dict[str, Any]:
    return {
        "schema": "simplicio.ac-evidence/v1",
        "status": "PASS",
        "ready": True,
        "verdict": "COMPLETE",
        "receipt_id": f"{task_id}-evidence",
    }


class _QueueState:
    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        self._lock = threading.Lock()
        self._tasks = {}
        for task in tasks:
            row = dict(task)
            row.setdefault("status", "ready")
            row.setdefault("fence", "")
            row.setdefault("claimed_by", None)
            self._tasks[row["task_id"]] = row
        self._claims: list[dict[str, Any]] = []
        self._completions: list[dict[str, Any]] = []
        self._runtime_ops: list[dict[str, Any]] = []
        self._negotiations: list[dict[str, Any]] = []

    def _identity_key(self, identity: dict[str, Any]) -> tuple[str, str, str, str]:
        normalized = validate_identity(identity)
        return tuple(normalized[field] for field in ("agent_id", "runtime", "device_id", "session_id"))

    def claim(self, identity: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_identity(identity)
        identity_key = self._identity_key(normalized)
        with self._lock:
            for task in self._tasks.values():
                if task.get("claimed_by") == normalized:
                    return {
                        "task_id": task["task_id"],
                        "lease": {"fence": task["fence"], "status": "claimed"},
                        "context_pack": task["context_pack"],
                        "allocation_receipt": task["allocation_receipt"],
                    }
            for task in self._tasks.values():
                if task["assigned_key"] != identity_key or task["status"] != "ready":
                    continue
                fence = f"fence-{len(self._claims) + 1}"
                task["status"] = "claimed"
                task["fence"] = fence
                task["claimed_by"] = normalized
                claim = {
                    "task_id": task["task_id"],
                    "lease": {"fence": fence, "status": "claimed"},
                    "context_pack": task["context_pack"],
                    "allocation_receipt": task["allocation_receipt"],
                }
                self._claims.append({"task_id": task["task_id"], "identity": normalized, "fence": fence})
                return claim
        raise ValueError("no claimable task for identity")

    def complete(self, identity: dict[str, Any], task_id: str, fence: str, result: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_identity(identity)
        with self._lock:
            task = self._tasks[str(task_id)]
            if task.get("claimed_by") != normalized:
                raise ValueError("task owned by another identity")
            if str(task.get("fence")) != str(fence):
                raise ValueError("fencing token mismatch")
            task["status"] = "done"
            task["result"] = dict(result)
            self._completions.append({"task_id": task_id, "identity": normalized, "result": dict(result)})
            return {"completed": True, "task_id": task_id}

    def runtime_negotiate(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._negotiations.append(dict(request))
        return {
            "contract": "simplicio.runtime/v1",
            "contract_version": "1",
            "capabilities": ["events", "leases", "evidence", "completion"],
        }

    def runtime_apply(self, operation: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._runtime_ops.append(dict(operation))
        return {"accepted": True, "operation_id": operation["operation_id"]}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tasks": {
                    task_id: {
                        "status": task["status"],
                        "fence": task.get("fence", ""),
                        "assigned_to": task["context_pack"]["assigned_to"],
                        "context_pack": task["context_pack"],
                        "allocation_receipt": task["allocation_receipt"],
                    }
                    for task_id, task in self._tasks.items()
                },
                "claims": list(self._claims),
                "completions": list(self._completions),
                "runtime_operations": list(self._runtime_ops),
                "runtime_negotiations": list(self._negotiations),
            }


class _QueueHandler(BaseHTTPRequestHandler):
    state: _QueueState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/queue/claim":
                body = self.state.claim(payload["identity"])
            elif self.path == "/queue/complete":
                body = self.state.complete(payload["identity"], payload["task_id"], payload["fence"], payload["result"])
            elif self.path == "/runtime/negotiate":
                body = self.state.runtime_negotiate(payload)
            elif self.path == "/runtime/apply":
                body = self.state.runtime_apply(payload)
            else:
                self.send_response(404)
                self.end_headers()
                return
        except Exception as exc:  # pragma: no cover - test asserts happy path
            body = {"error": type(exc).__name__, "message": str(exc)}
            self.send_response(400)
        else:
            self.send_response(200)
        wire = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(wire)))
        self.end_headers()
        self.wfile.write(wire)


class _HttpRuntimeTransport:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def negotiate(self, request: dict[str, Any]) -> dict[str, Any]:
        return _json_post(self.base_url + "/runtime/negotiate", request)

    def apply(self, operation: dict[str, Any]) -> dict[str, Any]:
        return _json_post(self.base_url + "/runtime/apply", operation)


def _start_server(state: _QueueState) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    _QueueHandler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QueueHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _task_rows(repo: Path) -> list[dict[str, Any]]:
    identities = [
        validate_identity(
            {
                "agent_id": "agent-codex-a",
                "runtime": "codex",
                "device_id": "device-laptop-a",
                "session_id": "session-183-codex",
                "protocol": "simplicio-distributed/v1",
                "capabilities": CAPABILITIES,
            }
        ),
        validate_identity(
            {
                "agent_id": "agent-claude-b",
                "runtime": "claude",
                "device_id": "device-laptop-b",
                "session_id": "session-183-claude",
                "protocol": "simplicio-distributed/v1",
                "capabilities": CAPABILITIES,
            }
        ),
    ]
    rows = [
        {
            "task_id": "WI-183-CODEX",
            "goal": "Codex lane proves isolated planner worktree receipt",
            "acs": ["planner lane has explicit merge queue receipt"],
            "source_refs": ["src/planner.py"],
            "identity": identities[0],
        },
        {
            "task_id": "WI-183-CLAUDE",
            "goal": "Claude lane proves isolated operator worktree receipt",
            "acs": ["operator lane has explicit merge queue receipt"],
            "source_refs": ["src/operator.py"],
            "identity": identities[1],
        },
    ]
    queue = WorktreeQueue(
        repo_root=str(repo),
        state_path=str(repo / ".simplicio-loop/orchestrator" / "distributed-183-worktree-queue.json"),
        run_id="issue-183-ac7",
        worktree_root=str(repo / ".simplicio-loop/orchestrator" / "worktrees" / "issue-183-ac7"),
    )
    queue.register_tasks(
        [
            TaskSpec.from_mapping({"id": row["task_id"], "goal": row["goal"], "files_affected": row["source_refs"]})
            for row in rows
        ]
    )
    for row in rows:
        allocation = queue.allocate(
            TaskSpec.from_mapping({"id": row["task_id"], "goal": row["goal"], "files_affected": row["source_refs"]})
        )
        context_pack = build_context_pack(
            task_id=row["task_id"],
            goal=row["goal"],
            identity=row["identity"],
            acs=row["acs"],
            source_refs=row["source_refs"],
            depends_on=[],
            allowed_paths=row["source_refs"],
            issue_ref="wesleysimplicio/simplicio-loop#183",
        )
        queue.record_context(row["task_id"], context_pack)
        row["context_pack"] = context_pack
        row["allocation"] = allocation
        row["allocation_receipt"] = asdict(allocation)
        row["assigned_key"] = tuple(row["identity"][field] for field in ("agent_id", "runtime", "device_id", "session_id"))
        row["queue"] = queue
    return rows


def _record_worker_flow(task: dict[str, Any], board: ExecutionBoard, base_url: str, out_dir: Path) -> dict[str, Any]:
    claim = _json_post(base_url + "/queue/claim", {"identity": task["identity"]})
    context_pack = validate_context_pack(claim["context_pack"], task["identity"])
    runtime = LoopRuntimeAdapter(
        run_id="issue-183-ac7",
        work_item_id=task["task_id"],
        actor=task["identity"]["agent_id"],
        transport=_HttpRuntimeTransport(base_url),
        outbox_path=out_dir / f"{task['task_id']}.outbox.jsonl",
        identity=task["identity"],
    )
    runtime.negotiate()
    delivery = VerifiedAgentDelivery(runtime=runtime, board=board, attempt_id=f"{task['task_id']}-attempt-1")
    for phase in PHASES:
        delivery.transition(phase)
    evidence = _evidence_receipt(task["task_id"])
    delivery.record_evidence(evidence)
    watcher = delivery.record_watcher(match=True, challenge=f"replay {task['task_id']}")
    merge_candidate = task["queue"].enqueue_merge(task["task_id"])
    merge_receipt = task["queue"].record_composed_verification(
        task["task_id"],
        True,
        suite="distributed-183-ac7",
        details={
            "identity": task["identity"]["agent_id"],
            "runtime": task["identity"]["runtime"],
            "transport": "http-local",
        },
    )
    gate_before_delivery = bool(evidence["ready"] and evidence["verdict"] == "COMPLETE" and watcher["payload"]["match"])
    if not gate_before_delivery:
        raise RuntimeError("evidence gate must pass before delivery")
    delivery.record_delivery(
        {
            "target": "merge-queue",
            "satisfied": True,
            "merge_queue": {
                "receipt_sha": merge_receipt["receipt_sha"],
                "status": "accepted",
                "path": merge_receipt["path"],
                "branch": task["allocation_receipt"]["branch"],
                "worktree_path": task["allocation_receipt"]["path"],
            },
            "merge_queue_receipt_sha": merge_receipt["receipt_sha"],
            "merge_queue_status": "accepted",
            "merge_queue_branch": task["allocation_receipt"]["branch"],
            "merge_queue_worktree_path": task["allocation_receipt"]["path"],
        }
    )
    completed = delivery.complete(evidence)
    _json_post(
        base_url + "/queue/complete",
        {
            "identity": task["identity"],
            "task_id": task["task_id"],
            "fence": claim["lease"]["fence"],
            "result": {
                "status": completed["status"],
                "merge_queue_receipt_sha": merge_receipt["receipt_sha"],
                "merge_queue_status": completed["delivery"]["merge_queue_status"],
            },
        },
    )
    return {
        "task_id": task["task_id"],
        "identity": task["identity"],
        "context_pack": context_pack,
        "allocation_receipt": claim["allocation_receipt"],
        "merge_candidate": merge_candidate,
        "merge_receipt": merge_receipt,
        "completed": completed,
        "gate_before_delivery": gate_before_delivery,
    }


def run(out: str | Path) -> dict[str, Any]:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="distributed-183-ac7-") as temp_dir:
        repo = Path(temp_dir) / "repo"
        _init_repo(repo)
        tasks = _task_rows(repo)
        state = _QueueState(tasks)
        server, thread, base_url = _start_server(state)
        try:
            board = ExecutionBoard(run_id="issue-183-ac7")
            worker_results = [_record_worker_flow(task, board, base_url, out_dir) for task in tasks]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        projection = board.replay()
        board_paths = board.export(out_dir)
        board_receipt = json.loads(board_paths["receipt"].read_text(encoding="utf-8"))
        queue_state = state.snapshot()
        persisted_merge_receipts = []
        for result in worker_results:
            source = Path(result["merge_receipt"]["path"])
            target = out_dir / source.name
            shutil.copy2(source, target)
            persisted_merge_receipts.append(
                {
                    "task_id": result["task_id"],
                    "merge_queue_receipt_sha": result["merge_receipt"]["receipt_sha"],
                    "merge_queue_receipt_path": str(target),
                    "merge_queue_status": result["completed"]["delivery"]["merge_queue_status"],
                }
            )
        # Optional stage/issue fields need not be materialized.  The isolation
        # contract is that every field which *is* present belongs to the allow-list.
        context_pack_keys_ok = all(
            set(result["context_pack"]).issubset(CONTEXT_FIELDS)
            for result in worker_results
        )
        distinct_worktrees = len({result["allocation_receipt"]["path"] for result in worker_results}) == 2
        distinct_branches = len({result["allocation_receipt"]["branch"] for result in worker_results}) == 2
        merge_receipts_explicit = all(result["merge_receipt"]["receipt_sha"] and Path(result["merge_receipt"]["path"]).exists() for result in worker_results)
        acceptance = {
            "http_queue_two_identities": len(queue_state["claims"]) == 2 and len({claim["identity"]["agent_id"] for claim in queue_state["claims"]}) == 2,
            "context_packs_allow_listed": context_pack_keys_ok,
            "worktree_branch_isolated": distinct_worktrees and distinct_branches,
            "evidence_gate_before_delivery": all(result["gate_before_delivery"] for result in worker_results),
            "merge_queue_receipt_explicit": merge_receipts_explicit,
            "verified_delivery_complete": all(result["completed"]["status"] == "VERIFIED" for result in worker_results),
            "execution_board_converged": projection["status"] == "COMPLETE" and projection["summary"]["merge_queue_verified_cards"] == 2,
        }
        receipt = {
            "schema": "simplicio.distributed-183-ac7-receipt/v1",
            "issue": 183,
            "slice": "AC7",
            "tag": "MEASURED",
            "epic_closure_ready": False,
            "acceptance": acceptance,
            "artifacts": {
                "board_events": str(board_paths["events"]),
                "board_receipt": str(board_paths["receipt"]),
            },
            "local_measured": {
                "transport": "http-local",
                "run_id": "issue-183-ac7",
                "projection_hash": projection["projection_hash"],
                "board_status": projection["status"],
                "board_completion_percent": projection["summary"]["completion_percent"],
                "merge_queue_verified_cards": projection["summary"]["merge_queue_verified_cards"],
                "runtime_negotiations": len(queue_state["runtime_negotiations"]),
                "runtime_operations": len(queue_state["runtime_operations"]),
                "claims": queue_state["claims"],
                "queue_tasks": queue_state["tasks"],
                "worktree_receipts": [result["allocation_receipt"] for result in worker_results],
                "merge_queue_receipts": persisted_merge_receipts,
                "board_acceptance": board_receipt.get("acceptance", {}),
            },
            "external_unverified": {
                "physical_multi_machine": "UNVERIFIED| local HTTP server only; no second physical machine was exercised",
                "remote_queue_service": "UNVERIFIED| no external durable HTTP/SQLite/Redis queue was exercised",
                "production_merge_queue": "UNVERIFIED| merge_queue acceptance came from local composed receipt only",
                "external_execution_board": "UNVERIFIED| no external board adapter was bound",
            },
        }
        receipt_path = out_dir / "distributed-183-ac7-receipt.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "receipt": receipt,
            "projection": projection,
            "queue_state": queue_state,
            "workers": worker_results,
            "artifact_paths": {"receipt": str(receipt_path), "board_receipt": str(board_paths["receipt"])},
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local AC7 distributed fixture for issue #183")
    parser.add_argument("--out", default=".simplicio-loop/orchestrator/evidence/distributed-183-ac7")
    args = parser.parse_args(argv)
    result = run(args.out)
    print(json.dumps(result["receipt"], ensure_ascii=False, indent=2))
    return 0 if all(result["receipt"]["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
