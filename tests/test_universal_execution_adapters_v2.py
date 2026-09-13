from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import cli_impl
from simplicio_loop.execution_envelope import PHASES, SCHEMA, validate_execution_envelope
from simplicio_loop.execution_adapters import ENVELOPE_FILENAME, persist_execution_envelope


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
        "completion": {"ready": phase == "done", "verdict": "VERIFIED" if phase == "done" else "UNAVAILABLE"},
        "governor": governor,
    }
    for path, payload in {
        run / "manifest.json": manifest,
        run / "task-contract.json": contract,
        run / "state.json": state,
        run / "mapper-context.json": {"schema": "simplicio.mapper-receipt/v1", "status": "MEASURED"},
        run / "fast-receipt.json": {"schema": "simplicio.fast-receipt/v1", "status": "MEASURED"},
        run / "operator-receipt.json": {"schema": "simplicio.operator-receipt/v0", "status": "applied"},
        run / "evidence-receipt.json": {"schema": "simplicio.evidence-receipt/v1", "status": "VERIFIED"},
        loop / "watcher_state.json": {"schema": "simplicio.watcher/v1", "match": True, "status": "MEASURED"},
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
            {"task_index": 1, "task_id": "task-a", "status": "succeeded", "operator_receipt": str(run / "operator-receipt.json"), "evidence_receipt": str(run / "evidence-receipt.json")},
            {"task_index": 2, "task_id": "task-b", "status": "succeeded", "operator_receipt": str(run / "operator-receipt.json"), "evidence_receipt": str(run / "evidence-receipt.json")},
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
        assert cli_impl.main([flow, "--repo", str(repo), "run-1", "--task-indices", "1,2", "--serial"]) == 0

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
    assert envelope["status"] == "complete"
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


def test_expected_governor_blocked_short_circuits_batch_without_provider(tmp_path, monkeypatch):
    governor = {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"}
    repo, run, _manifest, _state, _contract = _run_fixture(tmp_path, phase="executing", governor=governor)
    called = False

    def provider_must_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider/dispatch called for expected governor block")

    monkeypatch.setattr(cli_impl, "execute_operator_batch", provider_must_not_run)
    assert cli_impl.main(["batch", "--repo", str(repo), "run-1", "--task-indices", "1", "--serial"]) == 2
    envelope = json.loads((run / ENVELOPE_FILENAME).read_text(encoding="utf-8"))
    assert called is False
    assert envelope["status"] == "expected_governor_blocked"
    assert envelope["governor"]["expected"] is True
    assert all(not phase["provider_called"] for phase in envelope["phases"].values())
    assert validate_execution_envelope(envelope) is True


def test_expected_governor_blocked_short_circuits_tick_without_provider(tmp_path, monkeypatch):
    governor = {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"}
    repo, run, _manifest, _state, _contract = _run_fixture(tmp_path, phase="executing", governor=governor)
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
        assert cli_impl.main([flow, "--repo", str(repo), "run-1", "--task-indices", "1,2", "--serial"]) == 2

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
