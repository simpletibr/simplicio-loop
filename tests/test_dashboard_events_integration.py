"""Integration tests for the dashboard-event/v1 stream against its real collaborators (#1398)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import dashboard_events as de

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
HOOKS = REPO / "hooks"

_WORKER = r"""
import sys
sys.path.insert(0, sys.argv[1])
import dashboard_events as de
run_dir, count, worker = sys.argv[2], int(sys.argv[3]), sys.argv[4]
for index in range(count):
    evt = de.emit(run_dir, "lane_progress", source="worker", lane=worker, iteration=index,
                  payload={"worker": worker, "index": index}, strict=True)
    assert evt is not None, "event dropped"
"""


def _lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_four_processes_emit_one_thousand_events_without_seq_gaps_or_duplicates(tmp_path):
    run_dir = tmp_path / "run-concurrent"
    run_dir.mkdir()
    procs = [
        subprocess.Popen([sys.executable, "-c", _WORKER, str(SCRIPTS), str(run_dir), "250", "w%d" % n],
                         stderr=subprocess.PIPE, text=True)
        for n in range(4)
    ]
    for proc in procs:
        _, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
    events = _lines(run_dir / "events.jsonl")
    assert len(events) == 1000
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, 1001))  # file order == seq order: allocated under the lock
    assert len({e["event_id"] for e in events}) == 1000
    assert all(de.validate_envelope(e) == [] for e in events)
    for worker in ("w0", "w1", "w2", "w3"):
        indexes = [e["payload"]["index"] for e in events if e["lane"] == worker]
        assert indexes == list(range(250))


def test_unwritable_sink_fails_open_and_records_a_diagnostic(tmp_path, monkeypatch, capsys):
    diag = tmp_path / "diag.jsonl"
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_DIAGNOSTICS", str(diag))
    run_dir = tmp_path / "run-blocked"
    (run_dir / "events.jsonl").mkdir(parents=True)  # unopenable for append, even for root
    before = len(de.diagnostics())
    assert de.emit(run_dir, "run_started", source="runner") is None
    assert len(de.diagnostics()) == before + 1
    assert de.diagnostics()[-1]["reason"] == "emit_failed"
    record = json.loads(diag.read_text(encoding="utf-8").splitlines()[-1])
    assert record["schema"] == "simplicio.dashboard-event-diagnostic/v1"
    assert "DEGRADE" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="POSIX permission bits are not enforced for root/Windows")
def test_read_only_run_dir_fails_open(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_DIAGNOSTICS", str(tmp_path / "diag.jsonl"))
    run_dir = tmp_path / "run-ro"
    run_dir.mkdir()
    run_dir.chmod(0o555)
    try:
        assert de.emit(run_dir, "run_started", source="runner") is None
    finally:
        run_dir.chmod(0o755)
    assert (tmp_path / "diag.jsonl").is_file()


def _state(run_id):
    return {"schema": "simplicio.run-state/v1", "run_id": run_id, "phase": "executing",
            "task_ids": ["T1"], "ac_ids": ["AC-1"], "events": [], "history": [], "blockers": []}


def test_runner_loop_continues_when_the_sink_is_unwritable(tmp_path, monkeypatch):
    from simplicio_loop.runner import _emit_event, _transition

    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_DIAGNOSTICS", str(tmp_path / "diag.jsonl"))
    run_dir = tmp_path / "run-x"
    (run_dir / "events.jsonl").mkdir(parents=True)
    state = _state("run-x")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    _emit_event(run_dir, state, "plan_ready", receipt=str(run_dir / "plan.json"), message="ready")
    _transition(run_dir, state, "validating", "operator receipt persisted")
    persisted = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "validating"
    assert [e.get("kind") or e.get("phase") for e in persisted["events"]] == ["plan_ready", "phase_transition"]
    assert (run_dir / "transitions.jsonl").is_file()
    assert (tmp_path / "diag.jsonl").is_file()


def test_runner_transitions_and_events_land_in_the_stream(tmp_path):
    from simplicio_loop.runner import _emit_event, _transition

    run_dir = tmp_path / "run-live"
    run_dir.mkdir()
    state = _state("run-live")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    _emit_event(run_dir, state, "worker_claimed", receipt=str(run_dir / "task-contract.json"),
                task_id="T1", message="claimed", branch="feat/x")
    _transition(run_dir, state, "validating", "operator receipt persisted",
                receipt=str(run_dir / "operator-receipt.json"))
    events = de.read_live_events(run_dir)
    assert [(e["kind"], e["source"]) for e in events] == [
        ("worker_claimed", "worker"), ("phase_exited", "runner"), ("phase_entered", "runner")]
    assert events[0]["lane"] == "feat/x" and events[0]["task_id"] == "T1"
    assert events[1]["phase"] == "executing" and events[2]["phase"] == "validating"
    assert events[2]["refs"] == ["operator-receipt.json"]
    # the live stream and the retroactive adapter agree on the lifecycle kinds of transitions.jsonl
    derived = [e["kind"] for e in de.derive_events(run_dir) if e["kind"].startswith("phase_")]
    assert derived == ["phase_exited", "phase_entered"]


def test_technical_debt_notice_is_a_lane_progress_event(tmp_path):
    from simplicio_loop import technical_debt

    run_dir = tmp_path / "run-debt"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(json.dumps(_state("run-debt")), encoding="utf-8")
    technical_debt.record_notice(run_dir, run_id="run-debt", reason_code="fan_out_disabled",
                                 stage="executing", source="runner", message="serial lane",
                                 next_action="enable fan-out")
    events = de.read_live_events(run_dir)
    assert [e["kind"] for e in events] == ["lane_progress"]
    assert events[0]["payload"]["step"] == "technical_debt"
    assert events[0]["payload"]["debt_reason_code"] == "fan_out_disabled"


def test_kill_switch_silences_the_runner(tmp_path, monkeypatch):
    from simplicio_loop.runner import _transition

    monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS", "0")
    run_dir = tmp_path / "run-off"
    run_dir.mkdir()
    state = _state("run-off")
    _transition(run_dir, state, "validating", "x")
    assert not (run_dir / "events.jsonl").exists()
    assert not (run_dir / "events.jsonl.lock").exists()


def _legacy_run(tmp_path):
    run_dir = tmp_path / ".simplicio-loop" / "loop-runs" / "run-old"
    run_dir.mkdir(parents=True)
    (run_dir / "transitions.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"ts": "2026-09-01T10:00:00Z", "from": None, "to": "intake", "reason": "armed"},
        {"ts": "2026-09-01T10:00:05Z", "from": "intake", "to": "mapping", "reason": "m"},
    ]) + "\n{torn\n", encoding="utf-8")
    state = {"run_id": "run-old", "phase": "mapping", "events": [
        {"schema": "simplicio.event-metadata/v1", "kind": "contract_frozen", "phase": "intake",
         "ts": "2026-09-01T10:00:01Z", "receipt": str(run_dir / "task-contract.json"), "scope": "collection"},
        {"phase": "phase_transition", "to_phase": "mapping", "from_phase": "intake", "ts": "2026-09-01T10:00:05Z"},
    ]}
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(json.dumps(state["events"][0]) + "\n", encoding="utf-8")
    return run_dir


def test_older_runs_are_derived_from_transitions_and_state_events(tmp_path):
    run_dir = _legacy_run(tmp_path)
    events = de.read_events(run_dir)
    assert [e["kind"] for e in events] == ["run_started", "phase_entered", "contract_frozen",
                                           "phase_exited", "phase_entered"]
    assert all(e["derived"] is True for e in events)
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert all(de.validate_envelope(e) == [] for e in events)
    assert events[2]["refs"] == ["task-contract.json"]
    assert [e["event_id"] for e in de.read_events(run_dir)] == [e["event_id"] for e in events]


def test_first_live_event_on_an_older_run_switches_to_the_live_stream(tmp_path):
    run_dir = _legacy_run(tmp_path)
    evt = de.emit(run_dir, "phase_entered", source="runner", phase="planning", strict=True)
    assert evt["seq"] == 1  # older progress records do not carry a dashboard seq
    assert [e["kind"] for e in de.read_events(run_dir)] == ["phase_entered"]


def test_hook_run_resolution(tmp_path, monkeypatch):
    for name in ("SIMPLICIO_RUN_DIR", "SIMPLICIO_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    assert de.resolve_run_dir(cwd=str(tmp_path), env={}) is None
    a = tmp_path / ".simplicio-loop" / "loop-runs" / "run-a"
    a.mkdir(parents=True)
    (a / "state.json").write_text(json.dumps({"phase": "executing"}), encoding="utf-8")
    assert de.resolve_run_dir(cwd=str(tmp_path), env={}) == str(a)
    b = tmp_path / ".simplicio-loop" / "orchestrator" / "runs" / "run-b"
    b.mkdir(parents=True)
    (b / "state.json").write_text(json.dumps({"phase": "planning"}), encoding="utf-8")
    assert de.resolve_run_dir(cwd=str(tmp_path), env={}) is None  # ambiguous: emit nothing
    assert de.resolve_run_dir(cwd=str(tmp_path), env={"SIMPLICIO_RUN_ID": "run-b"}) == str(b)
    assert de.resolve_run_dir(cwd=str(tmp_path), env={"SIMPLICIO_RUN_ID": "../etc"}) is None
    assert de.resolve_run_dir(cwd=str(tmp_path), env={"SIMPLICIO_RUN_DIR": str(a)}) == str(a)
    (b / "state.json").write_text(json.dumps({"phase": "done"}), encoding="utf-8")
    assert de.resolve_run_dir(cwd=str(tmp_path), env={}) == str(a)


def _hook_env(run_dir, extra=None):
    env = dict(os.environ)
    env.pop("SIMPLICIO_RUN_ID", None)
    env["SIMPLICIO_RUN_DIR"] = str(run_dir)
    env.update(extra or {})
    return env


def test_action_gate_block_emits_a_gate_event_without_the_command(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    cmd = "git push --force origin main  # ghp_" + "a" * 36
    result = subprocess.run([sys.executable, str(HOOKS / "action_gate.py"), "check", "--command", cmd],
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    events = de.read_live_events(run_dir)
    assert [e["kind"] for e in events] == ["gate_evaluated"]
    assert events[0]["source"] == "hook"
    assert events[0]["payload"]["gate"] == "action" and events[0]["payload"]["verdict"] == "blocked"
    assert "ghp_" not in json.dumps(events) and "--force" not in json.dumps(events)


def test_action_gate_allow_emits_nothing(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    result = subprocess.run([sys.executable, str(HOOKS / "action_gate.py"), "check", "--command", "ls -la"],
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0
    assert not (run_dir / "events.jsonl").exists()


def test_user_prompt_submit_emits_an_operator_turn_without_the_prompt(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    prompt = "please refactor the parser module"
    result = subprocess.run([sys.executable, str(HOOKS / "user_prompt_submit.py")],
                            input=json.dumps({"prompt": prompt, "cwd": str(tmp_path)}),
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "continue"  # hook output unchanged
    events = de.read_live_events(run_dir)
    assert [(e["kind"], e["source"]) for e in events] == [("iteration_started", "operator")]
    assert events[0]["payload"]["prompt_chars"] == len(prompt)
    assert prompt not in json.dumps(events)


def test_loop_stop_refeed_emits_iteration_events(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    loop_dir = tmp_path / ".simplicio-loop" / "orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "scratchpad.md").write_text(
        "---\niteration: 2\nmax_iterations: 10\ncompletion_promise: null\n---\nDo the task.\n",
        encoding="utf-8")
    result = subprocess.run([sys.executable, str(HOOKS / "loop_stop.py")], input="{}",
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"  # re-feed still happens
    kinds = [(e["kind"], e["iteration"]) for e in de.read_live_events(run_dir)]
    assert ("gate_evaluated", 2) in kinds
    assert kinds[-2:] == [("iteration_finished", 2), ("iteration_started", 3)]


def test_loop_stop_emits_stall_detected_on_a_three_turn_failure_streak(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    loop_dir = tmp_path / ".simplicio-loop" / "orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "scratchpad.md").write_text(
        "---\niteration: 4\nmax_iterations: 10\ncompletion_promise: null\n---\nDo the task.\n",
        encoding="utf-8")
    (loop_dir / "journal.jsonl").write_text("".join(
        json.dumps({"iteration": n, "gate": "fail", "fingerprint": "pytest:test_x"}) + "\n"
        for n in (2, 3, 4)), encoding="utf-8")
    result = subprocess.run([sys.executable, str(HOOKS / "loop_stop.py")], input="{}",
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    stalls = [e for e in de.read_live_events(run_dir) if e["kind"] == "stall_detected"]
    assert len(stalls) == 1
    assert stalls[0]["payload"] == {"fingerprint": "pytest:test_x", "streak": 3}
    assert stalls[0]["severity"] == "warning" and stalls[0]["iteration"] == 4


def test_loop_stop_cap_emits_a_blocked_iteration_finished(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    loop_dir = tmp_path / ".simplicio-loop" / "orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "scratchpad.md").write_text(
        "---\niteration: 5\nmax_iterations: 5\ncompletion_promise: null\n---\nDo the task.\n",
        encoding="utf-8")
    result = subprocess.run([sys.executable, str(HOOKS / "loop_stop.py")], input="{}",
                            cwd=str(tmp_path), env=_hook_env(run_dir), capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0
    last = de.read_live_events(run_dir)[-1]
    assert last["kind"] == "iteration_finished" and last["severity"] == "warning"
    assert last["payload"]["outcome"] == "blocked" and last["iteration"] == 5


def test_hooks_with_the_kill_switch_emit_nothing(tmp_path):
    run_dir = tmp_path / "run-hook"
    run_dir.mkdir()
    subprocess.run([sys.executable, str(HOOKS / "action_gate.py"), "check", "--command", "git push --force"],
                   cwd=str(tmp_path), env=_hook_env(run_dir, {"SIMPLICIO_DASHBOARD_EVENTS": "0"}),
                   capture_output=True, text=True, timeout=60)
    assert not (run_dir / "events.jsonl").exists()
