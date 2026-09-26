import json

from simplicio_loop.execution_route import (
    _stable_hash,
    capability_fingerprint,
    decide_route,
    route_receipt_is_current,
    verify_route_hash,
)
from simplicio_loop.oracle import persist_completion_receipt
from simplicio_loop.progress import build_progress
from simplicio_loop.runner import _fanout_execution_route, read_status, reconcile_delivery


def _receipt_with_capabilities(manifest):
    record = decide_route("mechanically update and test the indexed file", True, False).to_dict()
    record.update({
        "run_id": "run-694",
        "task_id": "task-1",
        "task_index": 1,
        "evidence_handles": ["mapper-pack-1"],
        "causal_ids": ["run-694", "task-1"],
        "route_authority": "loop-runner",
    })
    record["capability_manifest"] = manifest
    record["capability_fingerprint"] = capability_fingerprint(manifest)
    record["receipt_sha"] = _stable_hash({key: value for key, value in record.items()
                                          if key != "receipt_sha"})
    return record

def test_production_route_contract_is_deterministic_and_hybrid_without_worker():
    worker = decide_route("mechanically update and test the indexed file", True, False)
    hybrid = decide_route("mechanically update and test the indexed file", False, False)
    agent = decide_route("investigate ambiguous semantic failure", True, True)
    assert worker.route == "worker"
    assert hybrid.route == "hybrid"
    assert agent.route == "agent"
    assert verify_route_hash(worker.to_dict())
    assert verify_route_hash(hybrid.to_dict())
    assert verify_route_hash(agent.to_dict())


def test_capability_fingerprint_is_stable_and_invalidates_on_change():
    first = capability_fingerprint({"worker": ["edit", "test"], "version": 1})
    equivalent = capability_fingerprint({"version": 1, "worker": ["test", "edit"]})
    changed = capability_fingerprint({"worker": ["edit", "test", "schema"], "version": 1})
    assert first == equivalent
    assert first != changed


def test_route_receipt_currentity_requires_verified_capability_identity():
    manifest = {"worker": ["edit", "test"], "version": 1}
    receipt = _receipt_with_capabilities(manifest)
    assert route_receipt_is_current(receipt, manifest)
    assert {"run_id", "task_id", "evidence_handles", "causal_ids", "confidence", "backend",
            "capability_fingerprint"}.issubset(receipt)
    assert not route_receipt_is_current(receipt, {"worker": ["edit", "test", "schema"], "version": 1})
    receipt["route"] = "agent"
    assert not route_receipt_is_current(receipt, manifest)


def test_route_receipt_identity_reaches_status_progress_delivery_and_completion(tmp_path):
    repo = tmp_path / "repo"
    run = repo / ".simplicio-loop" / "loop-runs" / "run-694"
    loop = repo / ".simplicio-loop/orchestrator" / "loop"
    run.mkdir(parents=True)
    loop.mkdir(parents=True)
    manifest = {"run_id": "run-694", "delivery_target": "implemented", "source_kind": "local"}
    state = {"run_id": "run-694", "phase": "executing", "operator": {"ready": True}}
    route = json.loads(json.dumps(_receipt_with_capabilities({"worker": ["edit", "test"], "version": 1})))
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run / "execution-route.json").write_text(json.dumps(route), encoding="utf-8")

    status = read_status(str(repo), "run-694")
    assert status["execution_route"] == route
    assert status["route_receipt_status"] == "MEASURED"
    assert status["state"]["execution_route"] == route

    progress = build_progress(status["state"], run_dir=run)
    assert progress["execution_route"] == route
    assert progress["route_receipt_status"] == "MEASURED"

    reconciled = reconcile_delivery(str(repo), "run-694", "implemented")
    delivery = json.loads((run / "delivery-receipt.json").read_text(encoding="utf-8"))
    assert reconciled["state"]["delivery"]["execution_route"] == route
    assert delivery["execution_route"] == route
    assert delivery["route_receipt_sha"] == route["receipt_sha"]

    for name, value in {
        "watcher_challenge.json": {},
        "watcher_state.json": {},
        "anchor.json": {},
    }.items():
        (loop / name).write_text(json.dumps(value), encoding="utf-8")
    (loop / "completion-receipt.json").unlink(missing_ok=True)
    completion_path = persist_completion_receipt(
        {"ready": False, "verdict": "DELIVERY_PENDING"}, str(loop), str(run)
    )
    completion = json.loads(open(completion_path, encoding="utf-8").read())
    assert completion["execution_route"] == route
    assert completion["route_receipt_sha"] == route["receipt_sha"]


def test_fanout_items_receive_independent_pre_llm_routes(tmp_path):
    worker = _fanout_execution_route({
        "run_id": "run-694", "task_id": "mechanical", "task_index": 1,
        "context_pack": {
            "goal": "mechanically edit and test the indexed file",
            "worker_capabilities": ["edit", "test"],
            "mapper_envelope_hash": "mapper-1",
        },
    }, tmp_path)
    agent = _fanout_execution_route({
        "run_id": "run-694", "task_id": "semantic", "task_index": 2,
        "context_pack": {
            "goal": "investigate ambiguous semantic failure",
            "ambiguous": True,
            "mapper_envelope_hash": "mapper-2",
        },
    }, tmp_path)
    assert worker["route"] == "worker"
    assert worker["token_usage"] == {
        "input_tokens": 0, "output_tokens": 0, "reason": "deterministic_worker_no_llm",
    }
    assert agent["route"] == "agent"
    assert agent["token_usage"]["input_tokens"] is None
    assert verify_route_hash(worker) and verify_route_hash(agent)
    assert worker["receipt_sha"] != agent["receipt_sha"]
    assert (tmp_path / "execution-route-1.json").exists()
    assert (tmp_path / "execution-route-2.json").exists()
