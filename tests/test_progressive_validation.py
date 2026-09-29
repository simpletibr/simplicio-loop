from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from simplicio_loop.progressive_validation import (
    ProgressiveValidator,
    Risk,
    ValidationCommand,
    ValidationLevel,
    ValidationRequest,
    canonical_hash,
    receipt_hash_valid,
    selected_commands,
    sha256_bytes,
    source_tree_hash,
)


HASHES = {
    "source_hash": "sha256:" + "1" * 64,
    "tool_hash": "sha256:" + "2" * 64,
    "config_hash": "sha256:" + "3" * 64,
}


def commands():
    return tuple(
        ValidationCommand(level, ("validate", level.value))
        for level in ValidationLevel
    )


def request(**overrides):
    values = dict(HASHES, commands=commands())
    values.update(overrides)
    return ValidationRequest(**values)


class Recorder:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def __call__(self, command):
        self.calls.append(tuple(command))
        code = int(command[-1] == self.failure)
        return {
            "exit_code": code,
            "duration_ns": 100,
            "stdout_hash": sha256_bytes(("out:" + command[-1]).encode()),
            "stderr_hash": sha256_bytes(b"" if not code else b"failure"),
        }


def test_targeted_precedes_impact_and_smallest_sufficient_lane(tmp_path):
    recorder = Recorder()
    receipt = ProgressiveValidator(tmp_path / "cache.json", executor=recorder).run(
        request(impact_level=ValidationLevel.IMPACT)
    )
    assert [row["level"] for row in receipt["commands"]] == [
        "parse", "format", "targeted", "impact"
    ]
    assert receipt["status"] == "passed"
    assert receipt["metrics"]["final_duration_ns"] is None
    assert receipt["metrics"]["final_duration_reason"]


def test_stale_source_and_tool_drift_are_rejected(tmp_path):
    cache = tmp_path / "cache.json"
    first = Recorder()
    ProgressiveValidator(cache, executor=first).run(request())
    second = Recorder()
    stale_source = request(source_hash="sha256:" + "4" * 64)
    receipt = ProgressiveValidator(cache, executor=second).run(stale_source)
    assert receipt["metrics"]["cache_hits"] == 0
    assert receipt["metrics"]["stale_rejections"] == 3
    third = Recorder()
    tool_drift = request(
        source_hash=stale_source.source_hash, tool_hash="sha256:" + "5" * 64
    )
    drift = ProgressiveValidator(cache, executor=third).run(tool_drift)
    assert drift["metrics"]["stale_rejections"] == 3
    assert len(third.calls) == 3


def test_targeted_failure_stops_before_broad_promotion(tmp_path):
    recorder = Recorder(failure="targeted")
    receipt = ProgressiveValidator(tmp_path / "cache.json", executor=recorder).run(
        request(risk=Risk.CRITICAL)
    )
    assert receipt["required_level"] == "full"
    assert receipt["status"] == "failed"
    assert receipt["blocked_at"] == "targeted"
    assert [call[-1] for call in recorder.calls] == ["parse", "format", "targeted"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"risk": Risk.MEDIUM}, "impact"),
        ({"risk": Risk.HIGH}, "module"),
        ({"risk": Risk.CRITICAL}, "full"),
        ({"delivery": True}, "full"),
        ({"prior_failure": True}, "full"),
    ],
)
def test_risk_failure_and_delivery_promote_policy(overrides, expected):
    assert selected_commands(request(**overrides))[-1].level.value == expected


def test_critical_policy_receipt_has_commands_versions_durations_and_hashes(tmp_path):
    receipt = ProgressiveValidator(
        tmp_path / "cache.json", executor=Recorder()
    ).run(request(risk=Risk.CRITICAL))
    assert receipt["required_level"] == "full"
    assert receipt["metrics"]["incremental_duration_ns"] == 500
    assert receipt["metrics"]["final_duration_ns"] == 100
    assert receipt["tool_versions"]["python"]
    assert all(row["command"] and row["duration_ns"] >= 0 for row in receipt["commands"])
    assert all(row["stdout_hash"].startswith("sha256:") for row in receipt["commands"])
    assert receipt_hash_valid(receipt)


def test_cache_hit_is_complete_hash_bound_and_tamper_fails_closed(tmp_path):
    cache = tmp_path / "cache.json"
    ProgressiveValidator(cache, executor=Recorder()).run(request())
    recorder = Recorder()
    hit = ProgressiveValidator(cache, executor=recorder).run(request())
    assert hit["metrics"]["cache_hits"] == 3
    assert recorder.calls == []

    payload = json.loads(cache.read_text())
    entry = next(iter(payload["entries"].values()))
    entry["stdout_hash"] = sha256_bytes(b"tampered")
    cache.write_text(json.dumps(payload))
    rerun = Recorder()
    rejected = ProgressiveValidator(cache, executor=rerun).run(request())
    assert rejected["commands"][0]["stale_rejection"] == "entry_tampered"
    assert rerun.calls


def test_source_tree_hash_tracks_names_bytes_and_missing(tmp_path):
    (tmp_path / "a.py").write_text("one")
    first = source_tree_hash(tmp_path, ["a.py", "missing.py"])
    (tmp_path / "a.py").write_text("two")
    second = source_tree_hash(tmp_path, ["a.py", "missing.py"])
    assert first != second
    assert len(first) == 71


def test_e2e_real_subprocess_and_reproducible_cache(tmp_path):
    plan = tuple(
        ValidationCommand(
            level,
            (sys.executable, "-c", "print(%r)" % level.value),
        )
        for level in (ValidationLevel.PARSE, ValidationLevel.FORMAT, ValidationLevel.TARGETED)
    )
    subject = request(commands=plan)
    first = ProgressiveValidator(tmp_path / "cache.json").run(subject)
    second = ProgressiveValidator(tmp_path / "cache.json").run(subject)
    assert first["status"] == "passed"
    assert first["metrics"]["executed_lanes"] == 3
    assert second["metrics"]["cache_hits"] == 3
    assert all(row["duration_ns"] == 0 for row in second["commands"])


def test_rejects_partial_hashes_and_missing_required_lane():
    with pytest.raises(ValueError, match="complete sha256"):
        request(source_hash="sha256:abc")
    with pytest.raises(ValueError, match="required level full"):
        selected_commands(
            request(commands=commands()[:-1], risk=Risk.CRITICAL)
        )


def test_checked_in_benchmark_is_measured_hash_bound_and_model_free():
    path = Path(__file__).parent / "fixtures" / "progressive_validation_benchmark_815.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["classification"] == "MEASURED_LOCAL"
    assert payload["runs"] == 1000
    assert payload["local_llm"] is False
    assert payload["warm"]["median_ns"] < payload["cold"]["median_ns"]
    declared = payload.pop("receipt_hash")
    assert declared == canonical_hash(payload)
