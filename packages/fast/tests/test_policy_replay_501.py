from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from simplicio_fast.contract_surface import digest_for, validate_decision_receipt
from simplicio_fast.policy_replay import (
    POLICY_REPLAY_SCHEMA,
    PolicyReplayError,
    load_snapshot,
    load_snapshots,
    replay_snapshot,
    replay_snapshots,
)
from simplicio_fast.speculation_policy import SpeculationPolicy

ROOT = Path(__file__).parents[1]
EXAMPLES = json.loads(
    (ROOT / "contracts/fast-local/v1/examples.json").read_text(encoding="utf-8")
)


def _decision_with_strategy(strategy: str) -> dict:
    decision = copy.deepcopy(EXAMPLES["decision_receipt"])
    decision["payload"]["speculation_policy"] = {
        "enabled": strategy != "disabled",
        "strategy": strategy,
    }
    decision["payload"]["reason_codes"] = sorted(decision["payload"]["reason_codes"])
    decision["payload"]["decision_digest"] = ""
    unsigned = copy.deepcopy(decision)
    unsigned["payload"].pop("decision_digest")
    decision["payload"]["decision_digest"] = digest_for(unsigned)
    return decision


def test_loads_contract_message_or_examples_bundle_and_preserves_historical_receipt():
    direct = load_snapshot(EXAMPLES["telemetry_snapshot"])
    bundled = load_snapshot(EXAMPLES)

    assert direct.sample_id == bundled.sample_id == "sample-001"
    assert bundled.historical_decision is not None
    assert (
        bundled.to_dict()["telemetry_snapshot"]["message_type"] == "telemetry_snapshot"
    )


def test_loads_json_path_and_snapshot_collection(tmp_path):
    path = tmp_path / "snapshots.json"
    path.write_text(
        json.dumps({"snapshots": [EXAMPLES["telemetry_snapshot"]]}),
        encoding="utf-8",
    )

    loaded = load_snapshots(path)

    assert len(loaded) == 1
    assert loaded[0].sample_id == "sample-001"


def test_replay_emits_a_valid_contract_decision_receipt_and_exact_policy_metadata():
    result = replay_snapshot(EXAMPLES)
    receipt = validate_decision_receipt(result.decision_receipt)

    assert result.to_dict()["schema"] == POLICY_REPLAY_SCHEMA
    assert result.policy_result.selected.value == "draft"
    assert receipt["payload"]["speculation_policy"] == {
        "enabled": True,
        "strategy": "draft_verify",
    }
    assert result.diff.selection_changed is False
    assert result.warnings == ("historical_source_digest_differs",)
    assert "No Local/model/KV/kernel execution performed." in result.report


def test_changed_historical_selection_has_a_clear_contract_field_diff():
    record = {
        "snapshot": EXAMPLES["telemetry_snapshot"],
        "historical_decision": _decision_with_strategy("disabled"),
    }

    result = replay_snapshot(record)

    assert result.diff.selection_changed is True
    assert result.diff.to_dict()["changes"] == [
        {
            "field": "speculation_policy.strategy",
            "historical": "disabled",
            "current": "draft_verify",
        }
    ]


def test_version_pinned_policy_and_missing_history_are_explicit():
    result = replay_snapshot(
        EXAMPLES["telemetry_snapshot"],
        policy=SpeculationPolicy("off"),
        policy_version="policy-492-off",
    )

    assert result.policy_version == "policy-492-off"
    assert result.policy_result.selected.value == "baseline"
    assert result.decision_receipt["payload"]["speculation_policy"] == {
        "enabled": False,
        "strategy": "disabled",
    }
    assert result.diff.selection_changed is None
    assert result.diff.to_dict()["status"] == "not_recorded"


def test_batch_summary_and_report_are_deterministic():
    batch = replay_snapshots(
        [
            EXAMPLES,
            EXAMPLES["telemetry_snapshot"],
        ],
        policy_version="current",
    )

    assert batch.summary == {
        "total": 2,
        "historical_recorded": 1,
        "selection_changed": 0,
        "selection_unchanged": 1,
        "selection_unrecorded": 1,
        "current_contract_strategies": {"draft_verify": 2},
        "historical_contract_strategies": {"draft_verify": 1},
    }
    assert (
        batch.to_dict()
        == replay_snapshots(
            [EXAMPLES, EXAMPLES["telemetry_snapshot"]], policy_version="current"
        ).to_dict()
    )
    assert "Snapshots: 2" in batch.report
    assert "Historical selection unrecorded: 1" in batch.report


def test_loads_json_array_and_rejects_unknown_policy_version():
    loaded = load_snapshots([EXAMPLES["telemetry_snapshot"]])
    assert len(loaded) == 1
    with pytest.raises(PolicyReplayError, match="policy_version_unavailable"):
        replay_snapshot(EXAMPLES["telemetry_snapshot"], policy_version="v2")
