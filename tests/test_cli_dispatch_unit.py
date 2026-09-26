"""In-process coverage of simplicio_loop.cli's argument-parsing/dispatch layer (#275).

The existing CLI tests exercise the *behavior* correctly, but many of them shell out to
`python -m simplicio_loop.cli ...` as a real subprocess — which is right for proving the
end-to-end contract, but pytest-cov cannot attribute lines executed in a different
process back to this run. That is the actual reason `simplicio_loop/cli.py` measured so
low in earlier full-suite coverage reports: not that the dispatch layer is untested, but
that most of what tests it runs out-of-process.

This file closes that specific, mechanical gap: it calls `cli.main(argv)` **in-process**
for every subcommand, with the underlying business-logic functions (imported from
.runner/.drain/.oracle/.progress/.task_contract) replaced by monkeypatched fakes. That
keeps these tests fast and deterministic (no real repo, no operator binaries, no
network) while proving the CLI wires each flag to the right function with the right
positional/keyword arguments and propagates its return code faithfully — the part of
cli.py that has no other direct-import test coverage today.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import cli


def test_main_defaults_to_install_when_no_command(monkeypatch, tmp_path):
    captured = {}

    def fake_install(target, globally, *_args):
        captured["target"] = target
        captured["globally"] = globally
        return 0

    monkeypatch.setattr(cli, "install", fake_install)
    rc = cli.main([])
    assert rc == 0
    assert captured["globally"] is False
    assert str(captured["target"]) == str(Path(".").resolve())


def test_main_install_global_flag(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        cli,
        "install",
        lambda target, globally, *_args: captured.update(globally=globally) or 0,
    )
    rc = cli.main(["install", "--target", str(tmp_path), "--global"])
    assert rc == 0
    assert captured["globally"] is True


def test_main_task_forwards_remaining_args(monkeypatch):
    captured = {}

    def fake_task_main(argv):
        captured["argv"] = argv
        return 3

    monkeypatch.setattr(cli, "task_contract_main", fake_task_main)
    rc = cli.main(["task", "compile", "foo.md"])
    assert rc == 3
    assert captured["argv"] == ["compile", "foo.md"]


def test_main_task_strips_leading_double_dash(monkeypatch):
    captured = {}

    def fake_task_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "task_contract_main", fake_task_main)
    cli.main(["task", "--", "compile", "foo.md"])
    assert captured["argv"] == ["compile", "foo.md"]


def test_main_prototype_forwards_remaining_args(monkeypatch):
    captured = {}

    def fake_prototype_main(argv):
        captured["argv"] = argv
        return 3

    monkeypatch.setattr(cli._prototype_cli, "main", fake_prototype_main)
    rc = cli.main(["prototype", "classify", "--task-description", "x"])
    assert rc == 3
    assert captured["argv"] == ["classify", "--task-description", "x"]


def test_main_prototype_strips_leading_double_dash(monkeypatch):
    captured = {}

    def fake_prototype_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli._prototype_cli, "main", fake_prototype_main)
    cli.main(["prototype", "--", "doctor"])
    assert captured["argv"] == ["doctor"]


def test_main_prototype_errors_when_module_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_prototype_cli", None)
    with pytest.raises(SystemExit):
        cli.main(["prototype", "doctor"])


def test_main_plan_dispatches_with_task_and_out(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "plan", lambda task_path, out_path: captured.update(
        task_path=task_path, out_path=out_path) or 0)
    rc = cli.main(["plan", "--task", "t.md", "--out", "out.json"])
    assert rc == 0
    assert captured == {"task_path": "t.md", "out_path": "out.json"}


def test_plan_writes_contract_and_previews_each_task(monkeypatch, tmp_path):
    task_file = tmp_path / "t.md"
    task_file.write_text("# task\n", encoding="utf-8")
    out_file = tmp_path / "out.json"
    monkeypatch.setattr(cli, "compile_many", lambda raw, source_path: {
        "tasks": [{"id": "T1"}, {"id": "T2"}]})
    monkeypatch.setattr(cli, "preview_contract", lambda task: "preview-%s" % task["id"])
    rc = cli.plan(str(task_file), str(out_file))
    assert rc == 0
    assert json.loads(out_file.read_text(encoding="utf-8"))["tasks"][0]["id"] == "T1"


def test_main_run_dispatches_all_positional_and_flags(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run", lambda repo, task_path, delivery, max_iterations: captured.update(
        repo=repo, task_path=task_path, delivery=delivery, max_iterations=max_iterations) or 0)
    rc = cli.main(["run", "--task", "t.md", "--repo", "/r", "--delivery", "verified", "--max-iterations", "5"])
    assert rc == 0
    assert captured == {"repo": "/r", "task_path": "t.md", "delivery": "verified", "max_iterations": 5}


def test_run_wraps_conduct_run_and_prints_json(monkeypatch, capsys):
    captured = {}

    def fake_conduct_run(repo, task_path, delivery, max_iterations, *,
                         quality_provider, quality_policy):
        captured.update(
            quality_provider=quality_provider,
            quality_policy=quality_policy,
        )
        return {"ok": True, "outcome": {"exit_code": 0}}

    monkeypatch.setattr(cli, "conduct_run", fake_conduct_run)
    rc = cli.run(
        "/r",
        "t.md",
        "verified",
        3,
        quality_provider="simplicio_loop_quality",
    )
    assert rc == 2
    assert captured == {
        "quality_provider": "simplicio_loop_quality",
        "quality_policy": "strict-default",
    }
    public = json.loads(capsys.readouterr().out)
    assert public["schema"] == "simplicio.loop-execution/v1"
    assert public["verified"] is False


def test_verify_returns_zero_only_when_phase_done(monkeypatch):
    import simplicio_loop.runner as runner_mod
    monkeypatch.setattr(runner_mod, "verify_run", lambda repo, run_id: {"state": {"phase": "done"}})
    assert cli.verify("/r", "run-1") == 0
    monkeypatch.setattr(runner_mod, "verify_run", lambda repo, run_id: {"state": {"phase": "blocked"}})
    assert cli.verify("/r", "run-1") == 1


def test_main_verify_dispatches_positional_run_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "verify", lambda repo, run_id: captured.update(repo=repo, run_id=run_id) or 0)
    rc = cli.main(["verify", "--repo", "/r", "run-9"])
    assert rc == 0
    assert captured == {"repo": "/r", "run_id": "run-9"}


def test_status_prints_read_status_payload(monkeypatch, capsys):
    monkeypatch.setattr(cli, "read_status", lambda repo, run_id: {"run_id": run_id})
    rc = cli.status("/r", "run-1")
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "run-1"


def test_resume_calls_change_phase_with_awaiting_decision(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "change_phase", lambda repo, run_id, phase, reason: captured.update(
        repo=repo, run_id=run_id, phase=phase, reason=reason) or {"phase": phase})
    rc = cli.resume("/r", "run-1")
    assert rc == 0
    assert captured["phase"] == "awaiting_decision"


def test_cancel_calls_change_phase_with_cancelled(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "change_phase", lambda repo, run_id, phase, reason: captured.update(phase=phase) or {})
    cli.cancel("/r", "run-1")
    assert captured["phase"] == "cancelled"


def test_tick_dispatches_task_index(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "execute_operator", lambda repo, run_id, task_index: captured.update(
        task_index=task_index) or {})
    cli.tick("/r", "run-1", 3)
    assert captured["task_index"] == 3


def test_batch_parses_task_indices_and_serial_flag(monkeypatch):
    captured = {}

    def fake_batch(repo, run_id, indices, max_workers=None, retry_budget=0, auto_fan_out=True):
        captured.update(indices=indices, max_workers=max_workers, retry_budget=retry_budget,
                        auto_fan_out=auto_fan_out)
        return {}

    monkeypatch.setattr(cli, "execute_operator_batch", fake_batch)
    cli.batch("/r", "run-1", "1, 2,3", max_workers=2, retry_budget=1, serial=True)
    assert captured["indices"] == [1, 2, 3]
    assert captured["auto_fan_out"] is False


def test_batch_empty_indices_means_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "execute_operator_batch", lambda repo, run_id, indices, **kw: captured.update(
        indices=indices) or {})
    cli.batch("/r", "run-1", "", max_workers=0, retry_budget=3)
    assert captured["indices"] is None


def test_batch_invalid_task_indices_raises_value_error():
    with pytest.raises(ValueError):
        cli.batch("/r", "run-1", "abc", max_workers=0, retry_budget=3)


def test_main_batch_dispatches_all_args(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "batch", lambda repo, run_id, indices, max_workers, retry_budget, serial, batch_size: captured.update(
        repo=repo, run_id=run_id, indices=indices, max_workers=max_workers,
        retry_budget=retry_budget, serial=serial, batch_size=batch_size) or 0)
    rc = cli.main(["batch", "--repo", "/r", "run-1", "--task-indices", "1,2",
                  "--max-workers", "4", "--retry-budget", "2", "--batch-size", "30", "--serial"])
    assert rc == 0
    assert captured["serial"] is True
    assert captured["indices"] == "1,2"
    assert captured["batch_size"] == 30


def test_batch_dispatches_reconciled_prism_waves(monkeypatch):
    calls = []

    def fake_batch(repo, run_id, indices, **kwargs):
        calls.append((indices, kwargs["max_workers"]))
        return {"workers": [{"status": "succeeded", "task_index": index} for index in indices]}

    monkeypatch.setattr(cli, "execute_operator_batch", fake_batch)
    rc = cli.batch("/r", "run-1", "1,2,3", max_workers=5, retry_budget=0, batch_size=2)
    assert rc == 2
    assert calls == [([1, 2, 3], 5)]


def test_oracle_write_receipt_persists_and_reflects_status(monkeypatch, capsys):
    import simplicio_loop.oracle as oracle_mod

    monkeypatch.setattr(cli, "evaluate_matrix", lambda loop_dir, run_dir, response_text, flow_gap: {
        "parity": True, "signature": [True]})
    # oracle() does `from .oracle import evaluate_completion` locally, so the fake must be
    # installed on the oracle module itself, not on the cli module's namespace.
    monkeypatch.setattr(oracle_mod, "evaluate_completion", lambda loop_dir, run_dir, response_text, flow_gap: {"v": 1})
    monkeypatch.setattr(cli, "persist_completion_receipt", lambda verdict, loop_dir, run_dir: "receipt.json")
    rc = cli.oracle("loop", "run", "", "", True)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt_path"] == "receipt.json"


def test_oracle_without_write_receipt_returns_1_when_no_parity(monkeypatch):
    monkeypatch.setattr(cli, "evaluate_matrix", lambda loop_dir, run_dir, response_text, flow_gap: {
        "parity": False, "signature": [False]})
    rc = cli.oracle("loop", "run", "", "", False)
    assert rc == 1


def test_progress_run_missing_returns_2(monkeypatch, capsys):
    def boom(repo, run_id):
        raise FileNotFoundError("no such run")

    monkeypatch.setattr(cli, "read_status", boom)
    rc = cli.progress("/r", "run-1", "text", True, 0.1)
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_code"] == "run_missing"


def test_progress_missing_run_dir_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "read_status", lambda repo, run_id: {})
    rc = cli.progress("/r", "run-1", "text", True, 0.1)
    assert rc == 2


def test_progress_streams_when_run_dir_present(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "read_status", lambda repo, run_id: {"run_dir": "/r/.simplicio-loop/orchestrator/run-1"})
    monkeypatch.setattr(cli, "stream_progress", lambda run_dir, **kw: captured.update(run_dir=run_dir, **kw))
    rc = cli.progress("/r", "run-1", "json", True, 0.5, no_animation=True, ascii_only=True)
    assert rc == 0
    assert captured["run_dir"] == "/r/.simplicio-loop/orchestrator/run-1"
    assert captured["fmt"] == "json"
    assert captured["ascii_only"] is True


def test_main_progress_defaults_to_latest_run(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "progress", lambda repo, run_id, fmt, once, interval, no_animation, ascii_only:
                        captured.update(repo=repo, run_id=run_id, once=once) or 0)
    assert cli.main(["progress", "--repo", "/r", "--once"]) == 0
    assert captured == {"repo": "/r", "run_id": "", "once": True}


def test_main_progress_prefers_explicit_run_flag_over_positional(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "progress", lambda repo, run_id, fmt, once, interval, no_animation, ascii_only:
                        captured.update(run_id=run_id) or 0)
    cli.main(["progress", "--run", "run-explicit"])
    assert captured["run_id"] == "run-explicit"


def test_maintenance_deferred_rejects_invalid_mode_or_disposition():
    rc = cli.maintenance_deferred("/r", "run-1", "active", "operator", "s", "r", [], "UNVERIFIED")
    assert rc == 2


def test_maintenance_deferred_valid_calls_defer_backlog(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "defer_maintenance_backlog_only", lambda repo, run_id, **kw: captured.update(kw) or {})
    rc = cli.maintenance_deferred("/r", "run-1", "maintenance_deferred", "backlog_only",
                                  "summary", "reason", ["step1"], "MEASURED")
    assert rc == 0
    assert captured["correction_summary"] == "summary"
    assert captured["resume_instructions"] == ["step1"]


def test_deliver_reads_payload_file_and_reconciles(monkeypatch, tmp_path):
    payload_file = tmp_path / "p.json"
    payload_file.write_text(json.dumps({"a": 1}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(cli, "reconcile_delivery", lambda repo, run_id, state, source_kind, source_payload:
                        captured.update(source_payload=source_payload) or {})
    rc = cli.deliver("/r", "run-1", "done", "local", str(payload_file))
    assert rc == 0
    assert captured["source_payload"] == {"a": 1}


def test_deliver_without_payload_file_uses_empty_dict(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "reconcile_delivery", lambda repo, run_id, state, source_kind, source_payload:
                        captured.update(source_payload=source_payload) or {})
    cli.deliver("/r", "run-1", "done", "local", "")
    assert captured["source_payload"] == {}


def test_decide_calls_apply_human_decision(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "apply_human_decision", lambda repo, run_id, decision_id, answer, impact:
                        captured.update(decision_id=decision_id, answer=answer, impact=impact) or {})
    cli.decide("/r", "run-1", "Q1", "yes", "behavior-change")
    assert captured == {"decision_id": "Q1", "answer": "yes", "impact": "behavior-change"}


def test_sync_source_forwards_optional_pr_and_tag(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "sync_source_state", lambda repo, run_id, source, external_repo, pr, tag:
                        captured.update(pr=pr, tag=tag) or {})
    cli.sync_source("/r", "run-1", "github", "owner/repo", 0, "")
    assert captured["pr"] is None


def test_main_dispatches_every_thin_subcommand(monkeypatch):
    """One parametrized sweep across every remaining CLI subcommand->function mapping,
    proving argparse wiring end to end without duplicating one test per command."""
    calls = []

    for name in ("status", "resume", "tick", "cancel", "deliver", "decide", "sync_source"):
        def make_fake(bound_name):
            return lambda *a, **k: calls.append(bound_name) or 0
        monkeypatch.setattr(cli, name, make_fake(name))

    cli.main(["status", "--repo", "/r", "--run-id", "run-1"])
    cli.main(["resume", "--repo", "/r", "run-1"])
    cli.main(["tick", "--repo", "/r", "run-1", "--task-index", "2"])
    cli.main(["cancel", "--repo", "/r", "run-1"])
    cli.main(["deliver", "--repo", "/r", "run-1", "--state", "done"])
    cli.main(["decide", "--repo", "/r", "run-1", "--decision-id", "Q1", "--answer", "yes"])
    cli.main(["sync-source", "--repo", "/r", "run-1", "--source", "github"])

    assert calls == ["status", "resume", "tick", "cancel", "deliver", "decide", "sync_source"]


def test_main_drain_dispatches_action_and_paths(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "drain", lambda action, snapshot_path, receipt_path, polls_required:
                        captured.update(action=action, snapshot_path=snapshot_path,
                                       receipt_path=receipt_path, polls_required=polls_required) or 0)
    rc = cli.main(["drain", "evaluate", "--snapshot", "s.json", "--receipt", "r.json", "--polls-required", "3"])
    assert rc == 0
    assert captured == {"action": "evaluate", "snapshot_path": "s.json", "receipt_path": "r.json",
                        "polls_required": 3}


def test_main_ledger_replay_and_validate_dispatch(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "ledger_replay", lambda path, compatibility, recover_trailing,
                        handshake_json, handshake_file, command: captured.update(command=command) or 0)
    cli.main(["ledger", "replay", "--path", "l.jsonl"])
    assert captured["command"] == "replay"
    cli.main(["ledger", "validate", "--path", "l.jsonl", "--compatibility"])
    assert captured["command"] == "validate"


def test_main_maintenance_deferred_aliases_both_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "maintenance_deferred", lambda *a, **k: calls.append(a) or 0)
    common = ["--repo", "/r", "run-1", "--mode", "active", "--disposition", "operator",
             "--correction-summary", "s", "--deferral-reason", "r"]
    cli.main(["maintenance-deferred"] + common)
    cli.main(["defer-maintenance"] + common)
    assert len(calls) == 2


# --- cli.drain() internal branches: exercised in-process (not via subprocess) so pytest-cov
# actually attributes them, unlike tests/test_drain_cli.py's `python -m simplicio_loop.cli`
# subprocess calls which prove the same behavior end-to-end but from a different process. ---

def test_drain_evaluate_requires_snapshot_path():
    rc = cli.drain("evaluate", "", "", 2)
    assert rc == 2


def test_drain_evaluate_reads_bad_json_snapshot_fails_closed(tmp_path):
    bad = tmp_path / "snap.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = cli.drain("evaluate", str(bad), "", 2)
    assert rc == 2


def test_drain_evaluate_snapshot_must_be_object(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text("[1, 2, 3]", encoding="utf-8")
    rc = cli.drain("evaluate", str(snap), "", 2)
    assert rc == 2


def test_drain_evaluate_success_returns_zero(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"tasks": [], "polls": [], "active_leases": 0}), encoding="utf-8")
    rc = cli.drain("evaluate", str(snap), "", 2)
    assert rc == 0


def test_drain_persist_requires_receipt_path(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"tasks": [], "polls": [], "active_leases": 0}), encoding="utf-8")
    rc = cli.drain("persist", str(snap), "", 2)
    assert rc == 2


def test_drain_persist_then_load_round_trip_in_process(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"tasks": [], "polls": [], "active_leases": 0}), encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    rc = cli.drain("persist", str(snap), str(receipt), 2)
    assert rc == 0
    assert receipt.exists()
    rc = cli.drain("load", "", str(receipt), 2)
    assert rc == 0


def test_drain_load_requires_receipt_path():
    rc = cli.drain("load", "", "", 2)
    assert rc == 2


def test_drain_load_missing_receipt_file_returns_2(tmp_path):
    rc = cli.drain("load", "", str(tmp_path / "nope.json"), 2)
    assert rc == 2


def test_drain_load_semantically_invalid_receipt_returns_2(tmp_path, monkeypatch):
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"not": "a-real-receipt"}), encoding="utf-8")
    monkeypatch.setattr(cli, "load_drain_receipt", lambda path: {"not": "a-real-receipt"})
    rc = cli.drain("load", "", str(receipt), 2)
    assert rc == 2


def test_drain_unknown_action_is_fail_closed():
    rc = cli.drain("bogus-action", "", "", 2)
    assert rc == 2


def test_valid_drain_result_rejects_ready_without_drained():
    assert cli._valid_drain_result({
        "schema": cli.DRAIN_SCHEMA, "verdict": "CONTINUE", "ready": True, "tag": "MEASURED",
    }) is False


def test_valid_drain_result_accepts_well_formed_receipt():
    assert cli._valid_drain_result({
        "schema": cli.DRAIN_SCHEMA, "verdict": "DRAINED", "ready": True, "tag": "MEASURED",
    }) is True


# --- cli._load_handshake(): the ledger CLI's inline/from-file mutual-exclusion + parse-error
# branches, also not reachable through the thin main()-dispatch monkeypatch tests above. ---

def test_load_handshake_returns_none_when_neither_arg_given():
    assert cli._load_handshake("", "") is None


def test_load_handshake_rejects_both_json_and_file():
    with pytest.raises(ValueError):
        cli._load_handshake("{}", "somefile.json")


def test_load_handshake_rejects_malformed_json():
    from simplicio_loop.ops_ledger import LedgerError
    with pytest.raises(LedgerError):
        cli._load_handshake("{not json", "")


def test_load_handshake_reads_from_file(tmp_path, monkeypatch):
    handshake_file = tmp_path / "hs.json"
    valid_handshake = {"executor": "codex", "run_id": "run-1", "attempt": 1, "context_hash": "abc"}
    handshake_file.write_text(json.dumps(valid_handshake), encoding="utf-8")
    monkeypatch.setattr(cli, "validate_handshake", lambda payload: payload)
    result = cli._load_handshake("", str(handshake_file))
    assert result == valid_handshake
