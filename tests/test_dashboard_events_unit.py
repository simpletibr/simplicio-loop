"""Unit tests for the simplicio.dashboard-event/v1 envelope (issue #1398)."""
import json
import os
import re
from pathlib import Path

import pytest

import dashboard_events as de

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "contracts" / "dashboard-event" / "v1" / "schema.json"
ISSUE_FIELDS = [
    "schema", "event_id", "seq", "ts", "run_id", "task_id", "scope", "source", "kind",
    "phase", "lane", "iteration", "severity", "payload", "refs", "producer_version",
]


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _envelope(**overrides):
    spec = {"kind": "phase_entered", "source": "runner", "phase": "mapping"}
    spec.update(overrides)
    return de.build_envelope(run_id="run-1", seq=1, **spec)


def test_envelope_has_exactly_the_issue_fields_and_validates():
    evt = _envelope()
    assert list(evt) == ISSUE_FIELDS
    assert de.validate_envelope(evt) == []
    assert _schema()["required"] == ISSUE_FIELDS


def test_jsonschema_and_stdlib_validator_agree_on_a_valid_envelope():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_envelope(), _schema())
    jsonschema.validate(_envelope(task_id="T1", scope="task", kind="worker_claimed",
                                  source="worker", lane="lane-a", iteration=2), _schema())


@pytest.mark.parametrize("mutate, needle", [
    (lambda e: e.update(kind="not_a_kind"), "kind"),
    (lambda e: e.update(kind="loop.run_started"), "kind"),
    (lambda e: e.update(source="robot"), "source"),
    (lambda e: e.update(scope="collection", task_id="T1"), "task_id"),
    (lambda e: e.update(scope="task", task_id=None), "task_id"),
    (lambda e: e.update(ts="2026-10-02 10:00:00"), "ts"),
    (lambda e: e.update(seq=0), "seq"),
    (lambda e: e.update(event_id="lowercase-not-ulid"), "event_id"),
    (lambda e: e.update(severity="fatal"), "severity"),
    (lambda e: e.update(refs=[""]), "refs"),
    (lambda e: e.update(payload=[]), "payload"),
    (lambda e: e.update(extra_field=1), "extra_field"),
    (lambda e: e.update(iteration=-1), "iteration"),
    (lambda e: e.pop("lane"), "lane"),
    (lambda e: e.update(producer_version="no version"), "producer_version"),
])
def test_invalid_envelopes_are_rejected_by_both_validators(mutate, needle):
    evt = _envelope()
    mutate(evt)
    errors = de.validate_envelope(evt)
    assert errors and any(needle in err for err in errors), errors
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(evt, _schema())


def test_other_products_use_a_namespaced_kind():
    evt = _envelope(kind="marketing.post_published", source="worker")
    assert de.validate_envelope(evt) == []


def test_schema_kind_catalog_matches_code_and_docs():
    enum = _schema()["properties"]["kind"]["anyOf"][0]["enum"]
    assert enum == list(de.LOOP_KINDS_ORDERED)
    assert set(de.LOOP_KINDS) == {k for kinds in de.KIND_CATALOG.values() for k in kinds}
    doc = (REPO / "docs" / "DASHBOARD_EVENTS.md").read_text(encoding="utf-8")
    for kind in de.LOOP_KINDS_ORDERED:
        assert "`%s`" % kind in doc, kind


def test_ulid_shape_time_prefix_and_determinism():
    a = de.new_ulid(ts_ms=1_700_000_000_000, randomness=b"\x00" * 10)
    b = de.new_ulid(ts_ms=1_700_000_000_001, randomness=b"\x00" * 10)
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", a)
    assert a < b
    assert de.new_ulid(ts_ms=1_700_000_000_000, randomness=b"\x00" * 10) == a
    assert de.new_ulid() != de.new_ulid()


def test_ts_format_and_parse_roundtrip():
    assert de.format_ts(0) == "1970-01-01T00:00:00.000Z"
    assert de.parse_ts("2026-10-02T21:00:00Z") == de.parse_ts("2026-10-02T21:00:00.000Z")
    assert de.parse_ts("2026-10-02T21:00:00+00:00") is not None
    assert de.parse_ts("garbage") is None


def test_scope_is_inferred_from_task_id():
    assert _envelope()["scope"] == "collection"
    evt = _envelope(task_id="T9")
    assert evt["scope"] == "task" and evt["task_id"] == "T9"


def test_payload_secrets_are_redacted_and_oversized_payloads_truncated():
    evt = _envelope(payload={"api_key": "abc", "nested": {"password": "p"}, "note": "Bearer xyz123"})
    assert evt["payload"]["api_key"] == "[REDACTED]"
    assert evt["payload"]["nested"]["password"] == "[REDACTED]"
    assert "xyz123" not in json.dumps(evt)
    big = _envelope(payload={"blob": "x" * (de.MAX_PAYLOAD_BYTES + 10)})
    assert big["payload"]["truncated"] is True
    assert de.validate_envelope(big) == []


def test_transition_derivation_covers_lifecycle_kinds():
    kinds = lambda entry: [s["kind"] for s in de.events_from_transition(entry)]  # noqa: E731
    assert kinds({"from": None, "to": "intake", "reason": "armed"}) == ["run_started", "phase_entered"]
    assert kinds({"from": "intake", "to": "mapping"}) == ["phase_exited", "phase_entered"]
    assert kinds({"from": "planning", "to": "awaiting_decision"}) == [
        "phase_exited", "phase_entered", "decision_requested"]
    assert kinds({"from": "delivering", "to": "done"}) == ["phase_exited", "phase_entered", "run_finished"]
    blocked = de.events_from_transition({"from": "executing", "to": "blocked", "reason": "x"})
    assert blocked[-1]["severity"] == "error"
    assert de.events_from_transition({"to": ""}) == []


@pytest.mark.parametrize("runner_kind, expected", [
    ("contract_frozen", "contract_frozen"),
    ("mapper_fresh", "map_ready"),
    ("mapper_degraded", "map_ready"),
    ("plan_ready", "plan_frozen"),
    ("worker_claimed", "worker_claimed"),
    ("worktree_created", "lane_progress"),
    ("operator_receipt", "apply_result"),
    ("operator_bootstrap", "retry_scheduled"),
    ("rollback", "retry_scheduled"),
    ("test_gate", "gate_evaluated"),
    ("watcher_challenge", "gate_evaluated"),
    ("oracle_verdict", "gate_evaluated"),
    ("delivery_reconciled", "delivery_reconciled"),
    ("blocked", "stall_detected"),
    ("technical_debt", "lane_progress"),
    ("something_new", "lane_progress"),
])
def test_runner_events_map_onto_the_catalog(runner_kind, expected):
    specs = de.specs_from_runner_event({"kind": runner_kind, "message": "m", "receipt": "/r/x.json"},
                                       {"run_id": "run-1", "phase": "executing"})
    assert [s["kind"] for s in specs] == [expected]
    assert specs[0]["payload"]["step"] == runner_kind
    assert specs[0]["run_id"] == "run-1"
    for spec in specs:
        assert de.validate_envelope(de.build_envelope(seq=1, **spec)) == []


def test_runner_phase_transition_reuses_transition_derivation():
    specs = de.specs_from_runner_event(
        {"phase": "phase_transition", "from_phase": "mapping", "to_phase": "planning", "reason": "r"},
        {"run_id": "run-1"})
    assert [s["kind"] for s in specs] == ["phase_exited", "phase_entered"]


def test_gate_payload_names_gate_and_verdict():
    spec = de.specs_from_runner_event({"kind": "test_gate", "blocker": "evidence_unverified",
                                       "status": "UNVERIFIED"}, {"run_id": "r"})[0]
    assert spec["payload"]["gate"] == "evidence"
    assert spec["payload"]["verdict"] == "fail"
    assert spec["severity"] == "warning"


def test_refs_inside_the_run_dir_are_relative(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    spec = de.specs_from_runner_event({"kind": "plan_ready", "receipt": str(run_dir / "plan.json")},
                                      {"run_id": "run-1"}, run_dir=run_dir)[0]
    assert spec["refs"] == ["plan.json"]


def test_kill_switch_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS", "0")
    assert de.enabled() is False
    assert de.emit(tmp_path, "run_started", source="runner") is None
    assert list(tmp_path.iterdir()) == []


def test_emit_appends_valid_envelopes_with_contiguous_seq(tmp_path):
    first = de.emit(tmp_path, "run_started", source="runner", phase="intake", strict=True)
    batch = de.emit_batch(tmp_path, [
        {"kind": "phase_entered", "source": "runner", "phase": "intake"},
        {"kind": "contract_frozen", "source": "runner", "refs": ["task-contract.json"]},
    ], strict=True)
    assert first["seq"] == 1 and [e["seq"] for e in batch] == [2, 3]
    assert first["run_id"] == tmp_path.name
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [1, 2, 3]
    assert all(de.validate_envelope(json.loads(line)) == [] for line in lines)


def test_seq_survives_a_torn_last_line(tmp_path):
    de.emit(tmp_path, "run_started", source="runner", strict=True)
    with open(tmp_path / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"schema": "simplicio.dashboard-event/v1", "seq": 9')  # torn, no newline
    evt = de.emit(tmp_path, "phase_entered", source="runner", phase="intake", strict=True)
    assert evt["seq"] == 2
    events = de.read_events(tmp_path)
    assert [e["seq"] for e in events] == [1, 2]


def test_rotation_by_size_keeps_seq_monotonic(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_MAX_BYTES", "2000")
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_KEEP", "2")
    for _ in range(40):
        de.emit(tmp_path, "lane_progress", source="worker", payload={"pad": "y" * 100}, strict=True)
    assert (tmp_path / "events.jsonl.1").is_file()
    assert (tmp_path / "events.jsonl.2").is_file()
    assert not (tmp_path / "events.jsonl.3").exists()
    assert os.path.getsize(tmp_path / "events.jsonl") <= 2000
    seqs = [e["seq"] for e in de.read_events(tmp_path)]
    assert seqs == sorted(seqs) and seqs[-1] == 40 and len(set(seqs)) == len(seqs)


def test_read_events_since_seq(tmp_path):
    for _ in range(5):
        de.emit(tmp_path, "lane_progress", source="worker", strict=True)
    assert [e["seq"] for e in de.read_events(tmp_path, since_seq=3)] == [4, 5]


def test_invalid_spec_is_dropped_with_a_diagnostic_not_raised(tmp_path):
    before = len(de.diagnostics())
    assert de.emit(tmp_path, "nope", source="runner") is None
    assert len(de.diagnostics()) == before + 1
    with pytest.raises(ValueError):
        de.emit(tmp_path, "nope", source="runner", strict=True)
