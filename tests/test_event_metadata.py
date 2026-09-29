import json
import shutil
import subprocess
import sys

import pytest

from simplicio_loop.event_metadata import infer_scope, normalise_event, validate_event_metadata
from simplicio_loop.progress import build_progress
from simplicio_loop.runner import _emit_event


def _state(events):
    return {
        "schema": "simplicio.run-state/v1",
        "run_id": "run-918",
        "phase": "watching",
        "task_count": 2,
        "task_ids": [],
        "ac_ids": ["SCN1"],
        "events": events,
        "evidence": {"ready": False, "status": "UNVERIFIED"},
        "completion": {"ready": False, "verdict": "DELIVERY_PENDING"},
    }


def test_collection_single_and_multi_task_events_accept_null_task_id(tmp_path):
    events = [
        {"schema": "simplicio.event-metadata/v1", "event_id": "evt-c1", "kind": "contract_frozen",
         "scope": "collection", "run_id": "run-918", "task_id": None, "receipt": "contract.json"},
        {"schema": "simplicio.event-metadata/v1", "event_id": "evt-c2", "kind": "watcher_challenge",
         "scope": "collection", "run_id": "run-918", "task_id": None, "receipt": "watcher.json"},
        {"schema": "simplicio.event-metadata/v1", "event_id": "evt-c3", "kind": "phase_transition",
         "scope": "collection", "run_id": "run-918", "task_id": None, "receipt": "state.json"},
    ]
    payload = build_progress(_state(events), run_dir=tmp_path)
    assert [event["scope"] for event in payload["events"]] == ["collection"] * 3
    assert all(event["task_id"] is None for event in payload["events"])
    assert all(event["metadata_status"] == "MEASURED" for event in payload["events"])
    assert not any("missing_event_metadata:task_id" in blocker for blocker in payload["blockers"])
    assert payload["event_metadata_policy"]["scopes"]["collection"]["task_id"] == "optional-null"


def test_task_event_without_task_id_fails_closed_with_precise_diagnostic():
    event = normalise_event({"schema": "simplicio.event-metadata/v1", "event_id": "evt-t1",
                             "kind": "worker_claimed", "scope": "task", "run_id": "run-918",
                             "receipt": "claim.json"})
    assert event["metadata_status"] == "UNVERIFIED"
    assert event["metadata_diagnostics"] == ["missing_event_metadata:event_id=evt-t1,kind=worker_claimed,scope=task:task_id"]


def test_scenario_valid_and_missing_task_id_matrix():
    valid = normalise_event({"schema": "simplicio.event-metadata/v1", "event_id": "evt-s1",
                             "kind": "scenario_completed", "scope": "scenario", "run_id": "run-918",
                             "task_id": "task-1", "ac_ids": ["SCN1"], "receipt": "scenario.json"})
    invalid = normalise_event({"schema": "simplicio.event-metadata/v1", "event_id": "evt-s2",
                               "kind": "scenario_completed", "scope": "scenario", "run_id": "run-918",
                               "ac_ids": ["SCN1"], "receipt": "scenario.json"})
    assert valid["metadata_status"] == "MEASURED"
    assert valid["task_id"] == "task-1"
    assert invalid["metadata_status"] == "UNVERIFIED"
    assert invalid["metadata_diagnostics"] == ["missing_event_metadata:event_id=evt-s2,kind=scenario_completed,scope=scenario:task_id"]


def test_historical_receipt_without_scope_is_read_append_only():
    event = normalise_event({"event_id": "legacy-1", "kind": "contract_frozen", "run_id": "run-old",
                             "receipt_ref": "old-contract.json"})
    assert event["scope"] == "collection"
    assert event["task_id"] is None
    assert event["schema"] == "simplicio.event-metadata/v1"
    assert event["source_schema"] == "simplicio.event-metadata/legacy"
    assert event["metadata_status"] == "MEASURED"


def test_runner_receipts_are_versioned_and_collection_explicit(tmp_path):
    state = _state([])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _emit_event(run_dir, state, "contract_frozen", receipt="contract.json", message="frozen")
    persisted = json.loads((run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert persisted["schema"] == "simplicio.event-metadata/v1"
    assert persisted["scope"] == "collection"
    assert persisted["task_id"] is None
    assert persisted["event_id"] and persisted["run_id"] == "run-918"


@pytest.mark.satellite
@pytest.mark.skipif(
    shutil.which("simplicio-mapper") is None,
    reason="requires the external simplicio-mapper executable",
)
def test_bounded_plan_to_first_mapping_is_utf8_safe(tmp_path):
    task = tmp_path / "task.md"
    contract = tmp_path / "contract.json"
    task.write_text("""Sistema: loop\nFuncionalidade: metadados\nTipo: Bug\n\nCOMO operador\nQUERO validar eventos\nPARA evitar blocker falso\n\n1. Critérios de Aceite\n\nCenário 1: coleção nula\n  Dado que um evento tem task_id nulo\n  Quando o renderer processa o evento\n  Então nenhum blocker sintético é criado [RN01]\n\n2. Regras de Negócio\n\nRN01 – collection aceita task_id nulo.\n""", encoding="utf-8")
    planned = subprocess.run([sys.executable, "-m", "simplicio_loop.cli", "plan", "--task", str(task), "--out", str(contract)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(tmp_path), stdin=subprocess.DEVNULL, timeout=30)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert json.loads(contract.read_text(encoding="utf-8"))["task_count"] == 1
    mapped = subprocess.run(["simplicio-mapper", "index", str(tmp_path), "--json", "--no-docs"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(tmp_path), stdin=subprocess.DEVNULL, timeout=45)
    assert mapped.returncode == 0, mapped.stdout + mapped.stderr
    status = subprocess.run(["simplicio-mapper", "status", str(tmp_path), "--json", "--await", "--timeout", "45"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(tmp_path), stdin=subprocess.DEVNULL, timeout=60)
    assert status.returncode == 0, status.stdout + status.stderr
    assert json.loads(status.stdout)["fresh"] is True


def test_metadata_policy_rejects_unknown_and_incomplete_scopes():
    assert infer_scope({"scope": "invalid"}) == "unknown"
    assert infer_scope({"scenario_id": "SCN1"}) == "scenario"
    assert infer_scope({"work_item_id": "task-1"}) == "task"
    assert infer_scope({"ac_id": "AC1"}) == "scenario"
    diagnostics = validate_event_metadata({"event_id": "evt-bad", "scope": "scenario"})
    assert any(item.endswith(":run_id") for item in diagnostics)
    assert any(item.endswith(":task_id") for item in diagnostics)
    assert any(item.endswith(":ac_id") for item in diagnostics)
    assert any(item.endswith(":receipt_or_blocker") for item in diagnostics)


def test_normalise_event_canonicalises_ac_id_shapes():
    scalar = normalise_event({"kind": "scenario", "run_id": "run", "task_id": "task", "ac_ids": "AC1", "receipt": "r"})
    invalid = normalise_event({"kind": "contract_frozen", "run_id": "run", "ac_ids": 7, "receipt": "r"})
    assert scalar["ac_ids"] == ["AC1"]
    assert invalid["ac_ids"] == []
