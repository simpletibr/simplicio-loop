from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from simplicio_loop.execution_envelope import (
    EXECUTION_FLOWS,
    EXECUTION_STATUSES,
    PHASES,
    SCHEMA,
    EnvelopeValidationError,
    build_execution_envelope,
    is_v1_receipt_compatible,
    validate_execution_envelope,
)


REPORT = {
    "schema": "simplicio.execution-report/v1",
    "run_id": "run-1",
    "status": "COMPLETE",
    "wall_ms": 12,
    "tasks": [],
    "consolidated": {
        "tokens_in_sum": None,
        "tokens_out_sum": None,
        "ram_mb_peak": None,
    },
}


def _phase(status: str = "complete", *, provider_called: bool = True, receipt=None):
    return {
        "status": status,
        "provider_called": provider_called,
        "receipt": receipt if receipt is not None else ({"receipt_id": "r-1"} if provider_called else None),
        "evidence": [{"kind": "phase-check", "ref": "tests/test_universal_execution_envelope.py"}],
    }


def _tasks():
    return [
        {
            "task_id": "task-a",
            "order": 0,
            "depends_on": [],
            "status": "complete",
            "evidence": [{"kind": "test", "ref": "tests/test_a.py", "status": "passed"}],
        },
        {
            "task_id": "task-b",
            "order": 1,
            "depends_on": ["task-a"],
            "status": "complete",
            "evidence": [{"kind": "test", "ref": "tests/test_b.py", "status": "passed"}],
        },
    ]


def _phases(status: str = "complete"):
    return {phase: _phase(status) for phase in PHASES}


def _complete(**changes):
    values = {
        "run_id": "run-1",
        "flow": "run",
        "tasks": _tasks(),
        "phases": _phases(),
        "status": "complete",
        "evidence": [{"kind": "gate", "ref": "pytest tests/test_universal_execution_envelope.py", "status": "passed"}],
        "execution_report": REPORT,
        "completion": {"verified": True, "oracle": "MEASURED"},
        "metrics": {
            "wall_ms": 12,
            "cpu_percent": None,
            "ram_mb": None,
            "tokens_in": None,
            "tokens_out": None,
        },
    }
    values.update(changes)
    return build_execution_envelope(**values)


@pytest.mark.parametrize("flow", sorted(EXECUTION_FLOWS))
def test_every_supported_flow_produces_the_same_canonical_schema(flow):
    envelope = _complete(flow=flow)

    assert envelope["schema"] == SCHEMA == "simplicio.loop-execution/v2"
    assert envelope["flow"] == flow
    assert validate_execution_envelope(envelope) is True


def test_ids_order_and_dependencies_are_canonical_and_unique():
    envelope = _complete()

    assert [task["task_id"] for task in envelope["tasks"]] == ["task-a", "task-b"]
    assert [task["order"] for task in envelope["tasks"]] == [0, 1]
    assert envelope["tasks"][1]["depends_on"] == ["task-a"]

    duplicate = copy.deepcopy(envelope)
    duplicate["tasks"][1]["task_id"] = "task-a"
    with pytest.raises(EnvelopeValidationError, match="duplicate task_id"):
        validate_execution_envelope(duplicate)

    bad_order = copy.deepcopy(envelope)
    bad_order["tasks"][1]["order"] = 0
    with pytest.raises(EnvelopeValidationError, match="order"):
        validate_execution_envelope(bad_order)

    bad_dependency = copy.deepcopy(envelope)
    bad_dependency["tasks"][1]["depends_on"] = ["missing"]
    with pytest.raises(EnvelopeValidationError, match="unknown dependency"):
        validate_execution_envelope(bad_dependency)

    cycle = copy.deepcopy(envelope)
    cycle["tasks"][0]["depends_on"] = ["task-b"]
    with pytest.raises(EnvelopeValidationError, match="cycle"):
        validate_execution_envelope(cycle)


@pytest.mark.parametrize("status", sorted(EXECUTION_STATUSES - {"complete"}))
def test_non_complete_terminal_states_are_explicit_and_valid(status):
    if status == "partial":
        tasks = [dict(_tasks()[0], status="complete"), dict(_tasks()[1], status="partial", evidence=[])]
        phases = _phases("partial")
        changes = {"tasks": tasks, "phases": phases, "evidence": [{"kind": "progress", "ref": "run.jsonl"}]}
    elif status == "expected_governor_blocked":
        phases = {phase: _phase("not_run", provider_called=False) for phase in PHASES}
        phases["mapper"] = _phase("blocked", provider_called=False)
        changes = {
            "phases": phases,
            "evidence": [{"kind": "governor", "ref": "capacity-receipt.json", "status": "blocked"}],
            "reason_code": "PHYSICAL_CAPACITY_PRESSURE",
            "governor": {"decision": "blocked", "expected": True, "reason_code": "PHYSICAL_CAPACITY_PRESSURE"},
        }
    else:
        changes = {
            "phases": _phases("blocked" if status == "blocked" else "error"),
            "evidence": [{"kind": status, "ref": "run.json", "status": status}],
            "reason_code": f"{status}_reason",
        }

    envelope = _complete(status=status, completion={"verified": False, "oracle": "UNAVAILABLE"}, **changes)
    assert validate_execution_envelope(envelope) is True


def test_provider_called_requires_a_receipt_and_unexpected_receipt_is_rejected():
    missing_receipt = _complete()
    missing_receipt["phases"]["dev_cli"]["receipt"] = None
    with pytest.raises(EnvelopeValidationError, match="receipt"):
        validate_execution_envelope(missing_receipt)

    unexpected_receipt = _complete()
    unexpected_receipt["phases"]["dev_cli"]["provider_called"] = False
    with pytest.raises(EnvelopeValidationError, match="provider_called"):
        validate_execution_envelope(unexpected_receipt)


def test_metrics_must_be_observed_numbers_or_null_and_report_is_reused():
    envelope = _complete()
    assert envelope["execution_report"]["schema"] == "simplicio.execution-report/v1"
    assert envelope["metrics"]["tokens_in"] is None

    invalid = copy.deepcopy(envelope)
    invalid["metrics"]["wall_ms"] = "12ms"
    with pytest.raises(EnvelopeValidationError, match="metrics.wall_ms"):
        validate_execution_envelope(invalid)

    invalid_report = copy.deepcopy(envelope)
    invalid_report["execution_report"]["schema"] = "simplicio.execution-report/v0"
    with pytest.raises(EnvelopeValidationError, match="execution-report"):
        validate_execution_envelope(invalid_report)


@pytest.mark.parametrize("secret_key", ["credential", "api_key", "access_token", "password", "private_key"])
def test_credentials_are_never_accepted_in_the_payload(secret_key):
    envelope = _complete()
    envelope["phases"]["loop"]["receipt"][secret_key] = "must-not-cross-boundary"
    with pytest.raises(EnvelopeValidationError, match="sensitive"):
        validate_execution_envelope(envelope)


def test_completion_claim_without_evidence_or_verified_oracle_is_rejected():
    false_completion = _complete()
    false_completion["evidence"] = []
    with pytest.raises(EnvelopeValidationError, match="evidence"):
        validate_execution_envelope(false_completion)

    false_oracle = _complete()
    false_oracle["completion"] = {"verified": False, "oracle": "MEASURED"}
    with pytest.raises(EnvelopeValidationError, match="completion"):
        validate_execution_envelope(false_oracle)


def test_validation_is_pure_and_v1_receipt_relation_is_explicit():
    envelope = _complete()
    before = json.dumps(envelope, sort_keys=True)
    assert validate_execution_envelope(envelope) is True
    assert json.dumps(envelope, sort_keys=True) == before
    assert is_v1_receipt_compatible(envelope) is False


def test_schema_is_versioned_under_existing_loop_execution_family_and_documented():
    schema_path = Path(__file__).parents[1] / "contracts" / "loop-execution" / "v2" / "receipt.schema.json"
    docs_path = schema_path.with_name("SCHEMA.md")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == SCHEMA
    assert "v1" in docs_path.read_text(encoding="utf-8")


def test_phases_have_no_fast_phase():
    assert PHASES == ("mapper", "dev_cli", "loop")
    stale = _complete()
    stale["phases"]["fast"] = _phase("complete")
    with pytest.raises(EnvelopeValidationError, match="phases"):
        validate_execution_envelope(stale)
