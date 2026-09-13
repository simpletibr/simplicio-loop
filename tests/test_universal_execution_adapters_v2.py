from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from simplicio_loop import cli_impl
from simplicio_loop.execution_envelope import PHASES, SCHEMA, validate_execution_envelope
from simplicio_loop.execution_adapters import (
    ENVELOPE_FILENAME,
    expected_governor_blocked,
    persist_execution_envelope,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_fixture(tmp_path: Path, *, phase: str = "done", governor: dict | None = None):
    repo = tmp_path / "repo"
    run = repo / ".simplicio" / "loop-runs" / "run-1"
    loop = run / "loop"
    loop.mkdir(parents=True)
    manifest = {
        "schema": "simplicio.run-manifest/v1",
        "run_id": "run-1",
        "repo": str(repo),
        "task_count": 2,
        "delivery_target": "implemented",
    }
    contract = {
        "schema": "simplicio.task-contract-collection/v1",
        "collection_hash": "contract-1",
        "task_count": 2,
        "tasks": [
            {"id": "task-a", "scenarios": [], "depends_on": []},
            {"id": "task-b", "scenarios": [], "depends_on": ["task-a"]},
        ],
    }
    state = {
        "schema": "simplicio.run-state/v1",
        "run_id": "run-1",
        "phase": phase,
        "task_ids": ["task-a", "task-b"],
        "mapper": {"ready": True, "receipt": str(run / "mapper-context.json")},
        "fast": {"ready": True, "receipt": str(run / "fast-receipt.json")},
        "operator": {"ready": True, "receipt": str(run / "operator-receipt.json"), "execution_state": "applied"},
        "evidence": {"ready": True, "receipt": str(run / "evidence-receipt.json"), "status": "VERIFIED"},
        "loop": {"ready": phase == "done", "receipt": str(loop / "watcher_state.json"), "status": "complete" if phase == "done" else "blocked"},
        "completion": {"ready": phase == "done", "verdict": "VERIFIED" if phase == "done" else "UNAVAILABLE"},
        "governor": governor,
        "tasks": [
            {"task_index": 1, "task_id": "task-a", "status": "complete", "dev_cli_receipt": str(run / "operator-receipt-task-1.json"), "evidence_receipt": str(run / "evidence-receipt.json")},
            {"task_index": 2, "task_id": "task-b", "status": "complete", "dev_cli_receipt": str(run / "operator-receipt-task-2.json"), "evidence_receipt": str(run / "evidence-receipt.json")},
        ],
    }
    mapper_receipt = {
        "scan": {"returncode": 0, "stdout": {}, "stderr": ""},
        "inspect": {"returncode": 0, "stdout": {}, "stderr": ""},
        "snapshot": {"returncode": 0, "stdout": {}, "stderr": ""},
        "handoff": {"returncode": 0, "stdout": {"context_pack": {"pack_hash": "pack-1", "files": [{"path": "app.py"}]}}, "stderr": ""},
        "repo_state_before": {"head": "commit-1", "tree_hash": "tree-1"},
        "repo_state_after": {"head": "commit-1", "tree_hash": "tree-1"},
        "foreground_generation": {"head": "commit-1", "tree_hash": "tree-1"},
        "generated_at": "2026-09-13T17:00:00Z",
        "run_id": "run-1",
        "task_contract_hash": "contract-1",
    }
    fast_receipt = {
        "schema": "simplicio.loop-fast-receipt/v1", "status": "MEASURED",
        "repo": str(repo), "run_id": "run-1", "generation": "fast-1",
        "operator": "simplicio-fast", "stage": "plan",
        "fast_receipt": {"schema": "simplicio.fast.plandag/v2", "nodes": [{"id": "node-1"}]},
    }
    fast_receipt["receipt_hash"] = hashlib.sha256(
        json.dumps(fast_receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    operator_receipt = {
        "schema": "simplicio.operator-receipt/v0", "mode": "apply",
        "tool": "simplicio-dev-cli", "execution_state": "applied", "target": "app.py",
        "goal": "fixture task", "returncode": 0, "measured_at": "2026-09-13T17:00:00Z",
        "source": "fixture", "repo_state_before": {"tree_hash": "tree-1"},
        "run_id": "run-1", "task_contract_hash": "contract-1", "plan_hash": "plan-1",
        "result": {"status": "applied"},
    }
    operator_receipt_task_1 = {**operator_receipt, "task_id": "task-a", "task_index": 1}
    operator_receipt_task_2 = {**operator_receipt, "task_id": "task-b", "task_index": 2}
    evidence_receipt = {
        "schema": "simplicio.evidence-receipt/v1", "run_id": "run-1", "status": "VERIFIED",
        "measured_at": "2026-09-13T17:00:00Z",
        "run": {"commit_sha": "commit-1", "diff_hash": "diff-1"},
        "operator": {"execution_state": "applied", "receipt_path": str(run / "operator-receipt.json")},
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 0, "scenario_verified": 0, "rule_total": 0, "rule_verified": 0},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": [str(run / "operator-receipt.json")]}],
        "scenarios": [], "rules": [],
    }
    evidence_receipt_task_1 = {
        **evidence_receipt,
        "task_id": "task-a",
        "task_index": 1,
        "operator": {**evidence_receipt["operator"], "receipt_path": str(run / "operator-receipt-task-1.json")},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": [str(run / "operator-receipt-task-1.json")]}],
    }
    evidence_receipt_task_2 = {
        **evidence_receipt,
        "task_id": "task-b",
        "task_index": 2,
        "operator": {**evidence_receipt["operator"], "receipt_path": str(run / "operator-receipt-task-2.json")},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": [str(run / "operator-receipt-task-2.json")]}],
    }
    watcher_receipt = {
        "schema": "simplicio.watcher-receipt/v1", "match": phase == "done",
        "status": "MEASURED" if phase == "done" else "UNVERIFIED",
        "checked_at": "2026-09-13T17:00:00Z", "challenge": "challenge-1", "goal_fp": "goal-1",
        "iteration": 1, "recomputed_truth": phase == "done", "reported": "1/1",
        "run_id": "run-1", "task_contract_hash": "contract-1", "plan_hash": "plan-1",
        "commit_sha": "commit-1", "diff_hash": "diff-1", "criteria_results": [{"id": "AC1", "match": phase == "done"}],
    }
    completion_receipt = {
        "schema": "simplicio.completion-receipt/v1", "ready": phase == "done",
        "verdict": "VERIFIED" if phase == "done" else "DELIVERY_PENDING",
        "reason_code": "verified_execution" if phase == "done" else "oracle_incomplete",
        "tag": "MEASURED" if phase == "done" else "UNVERIFIED",
        "generated_at": "2026-09-13T17:00:00Z", "run_id": "run-1",
        "watcher_status": "MEASURED" if phase == "done" else "UNVERIFIED",
        "watcher_match": phase == "done",
    }
    for path, payload in {
        run / "manifest.json": manifest,
        run / "task-contract.json": contract,
        run / "state.json": state,
        run / "mapper-context.json": mapper_receipt,
        run / "fast-receipt.json": fast_receipt,
        run / "operator-receipt.json": operator_receipt,
        run / "operator-receipt-task-1.json": operator_receipt_task_1,
        run / "operator-receipt-task-2.json": operator_receipt_task_2,
        run / "evidence-receipt.json": evidence_receipt,
        run / "evidence-receipt-task-1.json": evidence_receipt_task_1,
        run / "evidence-receipt-task-2.json": evidence_receipt_task_2,
        loop / "watcher_state.json": watcher_receipt,
        run / "completion-receipt.json": completion_receipt,
        run / "execution-report.json": {"schema": "simplicio.execution-report/v1", "run_id": "run-1", "status": "COMPLETE", "wall_ms": None, "tasks": [], "consolidated": {}},
    }.items():
        _write_json(path, payload)
    return repo, run, manifest, state, contract


def _successful_dispatch(run: Path) -> dict:
    return {
        "schema": "simplicio.operator-batch/v1",
        "run_id": "run-1",
        "status": "completed",
        "requested_tasks": [1, 2],
        "workers": [
            {"task_index": 1, "task_id": "task-a", "status": "succeeded", "operator_receipt": str(run / "operator-receipt-task-1.json"), "evidence_receipt": str(run / "evidence-receipt-task-1.json")},
            {"task_index": 2, "task_id": "task-b", "status": "succeeded", "operator_receipt": str(run / "operator-receipt-task-2.json"), "evidence_receipt": str(run / "evidence-receipt-task-2.json")},
        ],
        "completed_task_indices": [1, 2],
    }


def _assert_v2(repo: Path, run: Path, flow: str) -> dict:
    path = run / ENVELOPE_FILENAME
    assert path.is_file(), path
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema"] == SCHEMA
    assert envelope["flow"] == flow
    assert validate_execution_envelope(envelope) is True
    assert envelope["task_order"] == ["task-a", "task-b"]
    assert envelope["tasks"][1]["depends_on"] == ["task-a"]
    assert set(envelope["phases"]) == set(PHASES)
    assert envelope["execution_report"]["schema"] == "simplicio.execution-report/v1"
    assert envelope["evidence"]
    assert len(list(run.glob(ENVELOPE_FILENAME))) == 1
    return envelope


@pytest.mark.parametrize("flow", ["run", "tick", "batch", "wave", "prism"])
def test_run_backed_public_flows_persist_one_canonical_v2_envelope(tmp_path, monkeypatch, flow):
    repo, run, manifest, state, _contract = _run_fixture(tmp_path)

    if flow == "run":
        task = tmp_path / "task.md"
        task.write_text("task\n", encoding="utf-8")
        monkeypatch.setattr(cli_impl, "conduct_run", lambda *args, **kwargs: {"run_dir": str(run), "manifest": manifest, "state": state, "outcome": {"outcome": "COMPLETE", "exit_code": 0}})
        assert cli_impl.main(["run", "--task", str(task), "--repo", str(repo), "--delivery", "implemented"]) == 0
    elif flow == "tick":
        monkeypatch.setattr(cli_impl, "execute_operator", lambda *args, **kwargs: {"run_dir": str(run), "manifest": manifest, "state": state})
        assert cli_impl.main(["tick", "--repo", str(repo), "run-1", "--task-index", "1"]) == 0
    else:
        monkeypatch.setattr(cli_impl, "execute_operator_batch", lambda *args, **kwargs: _successful_dispatch(run))
        assert cli_impl.main([flow, "--repo", str(repo), "run-1", "--task-indices", "1,2"]) == 0

    envelope = _assert_v2(repo, run, flow)
    assert envelope["status"] == "complete"
    assert envelope["completion"] == {"verified": True, "oracle": "MEASURED"}


def test_single_task_fast_persists_one_artifact_envelope(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    task_file = tmp_path / "task.json"
    task = {
        "repo": str(repo), "goal": "update one file", "issue": "I-1", "source_revision": "r1",
        "acceptance_criteria": ["the file changes"], "target_hints": ["app.py"],
        "verification_commands": [["python3", "-c", "print('ok')"]],
        "budgets": {"max_context_bytes": 1000, "max_context_tokens": 1000, "max_diff_lines": 10, "max_iterations": 1},
        "delivery_contract": {"watcher": True, "dod": True}, "stop": {"preserve": True}, "recovery": {"preserve": True},
    }
    _write_json(task_file, task)
    receipt = {"schema": "simplicio.single-task-fast-receipt/v1", "status": "COMPLETED", "route": "single-task-fast",
               "mapper": {"receipt": {"ok": True}}, "context": {"receipt": {"ok": True}},
               "plan": {"receipt": {"ok": True}}, "mutation": {"receipt": {"ok": True}},
               "watcher": {"ok": True}, "dod": {"ok": True}, "verification": {"focused_ok": True}}
    monkeypatch.setattr(cli_impl, "dispatch_single_task_fast", lambda tasks: receipt)
    assert cli_impl.main(["single-task-fast", "--task-file", str(task_file)]) == 0
    candidates = list((repo / ".simplicio" / "loop-executions").glob("**/" + ENVELOPE_FILENAME))
    assert len(candidates) == 1
    envelope = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert envelope["flow"] == "single-task-fast"
    assert envelope["status"] != "complete"
    assert envelope["completion"]["verified"] is False
    assert validate_execution_envelope(envelope) is True


def test_no_provider_or_receipt_never_becomes_complete_and_unknown_metrics_are_null(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path, phase="blocked")
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json", "evidence-receipt.json"):
        (run / name).unlink()
    observed = {"run_dir": str(run), "manifest": manifest, "state": state, "contract": contract, "status": "blocked"}
    envelope = persist_execution_envelope(flow="run", repo=repo, run_id="run-1", observed=observed)
    assert envelope["status"] == "blocked"
    assert envelope["completion"]["verified"] is False
    assert all(value is None for value in envelope["metrics"].values())
    assert validate_execution_envelope(envelope) is True


def test_three_empty_receipts_and_success_flags_are_not_complete(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json"):
        _write_json(run / name, {})

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={
            "run_dir": str(run),
            "manifest": manifest,
            "state": state,
            "contract": contract,
            "result": {
                "status": "completed",
                "completed_task_indices": [1, 2],
                "watcher": {"ok": True},
            },
        },
    )

    assert envelope["status"] != "complete"
    assert envelope["completion"]["verified"] is False
    assert all(
        not envelope["phases"][phase]["provider_called"]
        for phase in ("mapper", "fast", "dev_cli")
    )


def test_arbitrary_json_receipts_are_not_phase_receipts(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json"):
        _write_json(run / name, {"success": True, "status": "COMPLETE"})

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={"run_dir": str(run), "manifest": manifest, "state": state,
                  "contract": contract, "status": "completed"},
    )

    assert envelope["status"] != "complete"
    assert all(
        not envelope["phases"][phase]["provider_called"]
        for phase in ("mapper", "fast", "dev_cli")
    )


def test_receipt_outside_authorized_run_root_is_not_evidence(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    outside = tmp_path / "outside-operator-receipt.json"
    outside.write_text((run / "operator-receipt.json").read_text(encoding="utf-8"), encoding="utf-8")
    (run / "operator-receipt.json").unlink()
    state = dict(state)
    state["operator"] = {"ready": True, "receipt": str(outside), "status": "complete"}

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={"run_dir": str(run), "manifest": manifest, "state": state,
                  "contract": contract, "result": {"status": "completed", "completed_task_indices": [1, 2]}},
    )

    assert envelope["status"] != "complete"
    assert envelope["phases"]["dev_cli"]["provider_called"] is False


def test_in_memory_receipt_mappings_do_not_establish_provider_or_completion(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    observed = {
        "state": {
            "phase": "done",
            "completion": {"ready": True},
            "mapper": {"status": "complete", "receipt": {"schema": "simplicio.mapper-receipt/v1", "verified": True}},
            "fast": {"status": "complete", "receipt": {"schema": "simplicio.fast-receipt/v1", "status": "COMPLETE"}},
            "operator": {"status": "complete", "receipt": {"schema": "simplicio.operator-receipt/v0", "execution_state": "applied"}},
        },
        "contract": {"tasks": [{"id": "task-1"}]},
        "result": {"status": "completed", "completed_task_indices": [1], "watcher": {"ok": True}},
    }

    envelope = persist_execution_envelope(flow="run", repo=repo, run_id="run-1", observed=observed)

    assert envelope["status"] != "complete"
    assert envelope["completion"]["verified"] is False
    assert all(not phase["provider_called"] for phase in envelope["phases"].values())


def test_generic_receipt_field_cannot_be_reused_across_phases(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json", "evidence-receipt.json", "completion-receipt.json"):
        (run / name).unlink()
    (run / "loop" / "watcher_state.json").unlink()
    shared = run / "shared-receipt.json"
    _write_json(shared, {"schema": "simplicio.mapper-receipt/v1", "verified": True})
    state = dict(state)
    state["mapper"] = {"ready": True, "status": "complete"}
    state["fast"] = {"ready": True, "status": "complete"}
    state["operator"] = {"ready": True, "status": "complete"}
    state["evidence"] = {"ready": True, "status": "complete"}
    state["loop"] = {"ready": True, "status": "complete"}
    state["receipt"] = str(shared)

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={"run_dir": str(run), "manifest": manifest, "state": state,
                  "contract": contract, "result": {"status": "completed", "receipt": str(shared),
                  "completed_task_indices": [1, 2], "watcher": {"ok": True}}},
    )

    assert envelope["status"] != "complete"
    assert all(not envelope["phases"][phase]["provider_called"] for phase in PHASES)


def test_completion_flags_cannot_replace_independent_persisted_evidence(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    (run / "evidence-receipt.json").unlink()
    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={"run_dir": str(run), "manifest": manifest, "state": state,
                  "contract": contract, "result": {"status": "completed",
                  "completed_task_indices": [1, 2], "watcher": {"ok": True}}},
    )

    assert envelope["status"] != "complete"
    assert envelope["completion"]["verified"] is False


def test_one_valid_dev_cli_receipt_cannot_complete_two_tasks(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    state = dict(state)
    state["tasks"] = [
        {"task_index": 1, "task_id": "task-a", "status": "complete"},
        {"task_index": 2, "task_id": "task-b", "status": "complete"},
    ]
    dispatch = _successful_dispatch(run)
    for worker in dispatch["workers"]:
        worker["operator_receipt"] = str(run / "operator-receipt.json")
    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={
            "run_dir": str(run),
            "manifest": manifest,
            "state": state,
            "contract": contract,
            "result": dispatch,
        },
    )

    assert envelope["status"] != "complete"
    assert sum(task["status"] == "complete" for task in envelope["tasks"]) < 2


def test_taskless_dev_cli_receipt_cannot_satisfy_a_multi_task_contract(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    state = dict(state)
    state["tasks"] = [
        {"task_index": 1, "task_id": "task-a", "status": "complete"},
        {"task_index": 2, "task_id": "task-b", "status": "complete"},
    ]
    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={
            "run_dir": str(run),
            "manifest": manifest,
            "state": state,
            "contract": contract,
            "result": {
                "status": "completed",
                "completed_task_indices": [1, 2],
            },
        },
    )

    assert envelope["status"] != "complete"
    assert all(task["status"] != "complete" for task in envelope["tasks"])


def test_success_flags_without_independent_persisted_oracle_never_complete(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    for name in ("evidence-receipt.json", "completion-receipt.json"):
        (run / name).unlink()
    (run / "loop" / "watcher_state.json").unlink()
    state = dict(state)
    state["loop"] = {"ready": True, "status": "complete"}
    state["completion"] = {"ready": True, "verdict": "VERIFIED"}

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={
            "run_dir": str(run),
            "manifest": manifest,
            "state": state,
            "contract": contract,
            "result": {
                "status": "completed",
                "completed_task_indices": [1, 2],
                "watcher": {"ok": True},
            },
        },
    )

    assert envelope["status"] != "complete"
    assert envelope["completion"]["verified"] is False
    assert envelope["phases"]["loop"]["provider_called"] is False


def test_receipt_symlink_inside_run_root_is_not_durable_evidence(tmp_path):
    repo, run, manifest, state, contract = _run_fixture(tmp_path)
    real = tmp_path / "real-operator-receipt.json"
    real.write_text((run / "operator-receipt.json").read_text(encoding="utf-8"), encoding="utf-8")
    (run / "operator-receipt.json").unlink()
    (run / "operator-receipt.json").symlink_to(real)
    state = dict(state)
    state["operator"] = {"ready": True, "receipt": str(run / "operator-receipt.json"), "status": "complete"}

    envelope = persist_execution_envelope(
        flow="run",
        repo=repo,
        run_id="run-1",
        observed={
            "run_dir": str(run),
            "manifest": manifest,
            "state": state,
            "contract": contract,
            "result": {"status": "completed", "completed_task_indices": [1, 2]},
        },
    )

    assert envelope["status"] != "complete"
    assert envelope["phases"]["dev_cli"]["provider_called"] is False


def test_admitted_false_without_explicit_expected_is_not_expected_governor_blocked(tmp_path):
    observed = {
        "status": "blocked",
        "admission": {"admitted": False, "decision": "blocked", "reason_code": "CAPACITY_PRESSURE"},
    }
    assert expected_governor_blocked(observed) is None
    repo = tmp_path / "repo"
    repo.mkdir()
    envelope = persist_execution_envelope(flow="batch", repo=repo, run_id="run-1", observed=observed)
    assert envelope["status"] != "expected_governor_blocked"


def test_real_provider_receipt_is_not_erased_by_expected_governor_flag(tmp_path):
    governor = {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"}
    repo, run, manifest, state, contract = _run_fixture(tmp_path, governor=governor)
    envelope = persist_execution_envelope(
        flow="batch",
        repo=repo,
        run_id="run-1",
        observed={"run_dir": str(run), "manifest": manifest, "state": state,
                  "contract": contract, "governor": governor, "result": _successful_dispatch(run)},
    )

    assert envelope["status"] != "expected_governor_blocked"
    assert envelope["phases"]["dev_cli"]["provider_called"] is True


def test_run_public_flow_persists_exactly_once_at_cli_boundary(tmp_path, monkeypatch):
    from simplicio_loop import runner as runner_mod
    from simplicio_loop import run_outcome

    calls = []
    status = {
        "manifest": {"run_id": "run-1"},
        "state": {"phase": "blocked"},
        "outcome": {"outcome": "BLOCKED", "exit_code": 2},
    }
    monkeypatch.setattr(runner_mod, "_conduct_run", lambda *args, **kwargs: dict(status))
    assert not hasattr(runner_mod, "persist_execution_envelope")
    monkeypatch.setattr(cli_impl, "persist_execution_envelope", lambda **kwargs: calls.append("cli"))
    monkeypatch.setattr(run_outcome, "persist_run_outcome", lambda value: value["outcome"])

    task = tmp_path / "task.md"
    task.write_text("task\n", encoding="utf-8")
    assert cli_impl.run(str(tmp_path / "repo"), str(task), "implemented", 1) == 2
    assert calls == ["cli"]


def test_expected_governor_blocked_short_circuits_batch_without_provider(tmp_path, monkeypatch):
    governor = {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"}
    repo, run, _manifest, _state, _contract = _run_fixture(tmp_path, phase="executing", governor=governor)
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json", "evidence-receipt.json", "completion-receipt.json"):
        (run / name).unlink()
    (run / "loop" / "watcher_state.json").unlink()
    called = False

    def provider_must_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider/dispatch called for expected governor block")

    monkeypatch.setattr(cli_impl, "execute_operator_batch", provider_must_not_run)
    assert cli_impl.main(["batch", "--repo", str(repo), "run-1", "--task-indices", "1"]) == 2
    envelope = json.loads((run / ENVELOPE_FILENAME).read_text(encoding="utf-8"))
    assert called is False
    assert envelope["status"] == "expected_governor_blocked"
    assert envelope["governor"]["expected"] is True
    assert all(not phase["provider_called"] for phase in envelope["phases"].values())
    assert validate_execution_envelope(envelope) is True


def test_expected_governor_blocked_short_circuits_tick_without_provider(tmp_path, monkeypatch):
    governor = {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"}
    repo, run, _manifest, _state, _contract = _run_fixture(tmp_path, phase="executing", governor=governor)
    for name in ("mapper-context.json", "fast-receipt.json", "operator-receipt.json", "evidence-receipt.json", "completion-receipt.json"):
        (run / name).unlink()
    (run / "loop" / "watcher_state.json").unlink()
    called = False

    def provider_must_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider/dispatch called for expected governor block")

    monkeypatch.setattr(cli_impl, "execute_operator", provider_must_not_run)
    assert cli_impl.main(["tick", "--repo", str(repo), "run-1", "--task-index", "1"]) == 2
    envelope = json.loads((run / ENVELOPE_FILENAME).read_text(encoding="utf-8"))
    assert called is False
    assert envelope["status"] == "expected_governor_blocked"
    assert validate_execution_envelope(envelope) is True


def test_expected_governor_blocked_short_circuits_single_task_fast_without_provider(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    task_file = tmp_path / "task.json"
    task = {
        "repo": str(repo), "goal": "governed task", "issue": "I-1", "source_revision": "r1",
        "acceptance_criteria": ["the file changes"], "target_hints": ["app.py"],
        "verification_commands": [["true"]],
        "budgets": {"max_context_bytes": 1000, "max_context_tokens": 1000, "max_diff_lines": 10, "max_iterations": 1},
        "delivery_contract": {"watcher": True, "dod": True}, "stop": {"preserve": True}, "recovery": {"preserve": True},
        "governor": {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"},
    }
    _write_json(task_file, task)
    called = False

    def provider_must_not_run(tasks):
        nonlocal called
        called = True
        raise AssertionError("provider/dispatch called for expected governor block")

    monkeypatch.setattr(cli_impl, "dispatch_single_task_fast", provider_must_not_run)
    assert cli_impl.main(["single-task-fast", "--task-file", str(task_file)]) == 2
    candidates = list((repo / ".simplicio" / "loop-executions").glob("**/" + ENVELOPE_FILENAME))
    assert len(candidates) == 1
    envelope = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert called is False
    assert envelope["status"] == "expected_governor_blocked"
    assert all(not phase["provider_called"] for phase in envelope["phases"].values())
    assert validate_execution_envelope(envelope) is True


@pytest.mark.parametrize("flow", ["run", "tick", "batch", "wave", "prism"])
def test_run_backed_failure_paths_persist_noncomplete_v2(tmp_path, monkeypatch, flow):
    repo, run, manifest, state, _contract = _run_fixture(tmp_path, phase="blocked")
    if flow == "run":
        task = tmp_path / "task.md"
        task.write_text("task\n", encoding="utf-8")
        monkeypatch.setattr(cli_impl, "conduct_run", lambda *args, **kwargs: {
            "run_dir": str(run), "manifest": manifest, "state": state,
            "outcome": {"outcome": "BLOCKED", "exit_code": 2},
        })
        assert cli_impl.main(["run", "--task", str(task), "--repo", str(repo), "--delivery", "implemented"]) == 2
    elif flow == "tick":
        monkeypatch.setattr(cli_impl, "execute_operator", lambda *args, **kwargs: {
            "run_id": "run-1", "status": "blocked", "reason_code": "operator_blocked",
        })
        assert cli_impl.main(["tick", "--repo", str(repo), "run-1", "--task-index", "1"]) == 2
    else:
        monkeypatch.setattr(cli_impl, "execute_operator_batch", lambda *args, **kwargs: {
            "schema": "simplicio.operator-batch/v1", "run_id": "run-1",
            "status": "blocked", "reason_code": "operator_blocked", "workers": [],
        })
        assert cli_impl.main([flow, "--repo", str(repo), "run-1", "--task-indices", "1,2"]) == 2

    envelope = _assert_v2(repo, run, flow)
    assert envelope["status"] == "blocked"
    assert envelope["completion"]["verified"] is False


def test_single_task_fast_failure_path_persists_noncomplete_v2(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    task_file = tmp_path / "task.json"
    task = {
        "repo": str(repo), "goal": "update one file", "issue": "I-1", "source_revision": "r1",
        "acceptance_criteria": ["the file changes"], "target_hints": ["app.py"],
        "verification_commands": [["python3", "-c", "print('ok')"]],
        "budgets": {"max_context_bytes": 1000, "max_context_tokens": 1000, "max_diff_lines": 10, "max_iterations": 1},
        "delivery_contract": {"watcher": True, "dod": True}, "stop": {"preserve": True}, "recovery": {"preserve": True},
    }
    _write_json(task_file, task)
    monkeypatch.setattr(cli_impl, "dispatch_single_task_fast", lambda tasks: {
        "schema": "simplicio.single-task-fast-receipt/v1", "status": "BLOCKED",
        "route": "single-task-fast", "reason_code": "provider_receipt_missing",
    })
    assert cli_impl.main(["single-task-fast", "--task-file", str(task_file)]) == 2
    candidates = list((repo / ".simplicio" / "loop-executions").glob("**/" + ENVELOPE_FILENAME))
    assert len(candidates) == 1
    envelope = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert envelope["status"] == "blocked"
    assert envelope["completion"]["verified"] is False
    assert validate_execution_envelope(envelope) is True
