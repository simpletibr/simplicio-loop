"""Tests for turn-loop progress instrumentation (issue #300, EPIC #296).

Covers the fail-open `emit` hooks wired into scripts/loop_journal.py (resume/record/stall),
scripts/task_anchor.py (check -> DRIFT) and scripts/watcher_verify.py (verify), plus the
DRIFT/STALLED warning banner in loop_progress.py's render.

loop_journal.py has no env-var path override (unlike task_anchor.py/task_backlog.py/
loop_progress.py), so its tests import the module directly and monkeypatch its JOURNAL/LOOP_DIR
module attributes rather than spawning a subprocess against the real repo's .simplicio-loop/orchestrator/loop/.
"""
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL_SCRIPT = os.path.join(REPO, "scripts", "loop_journal.py")
ANCHOR = os.path.join(REPO, "scripts", "task_anchor.py")
PROGRESS = os.path.join(REPO, "scripts", "loop_progress.py")
WATCHER = os.path.join(REPO, "scripts", "watcher_verify.py")

_spec = importlib.util.spec_from_file_location("loop_progress_turn_test", PROGRESS)
loop_progress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loop_progress)

_jspec = importlib.util.spec_from_file_location("loop_journal_turn_test", JOURNAL_SCRIPT)
loop_journal = importlib.util.module_from_spec(_jspec)
_jspec.loader.exec_module(loop_journal)


def _env(tmp_path):
    return {
        "SIMPLICIO_PROGRESS_DIR": str(tmp_path),
        "SIMPLICIO_ANCHOR_FILE": str(tmp_path / "anchor.json"),
        "SIMPLICIO_BACKLOG_FILE": str(tmp_path / "backlog.jsonl"),
    }


def _run(script, args, cwd, env):
    full_env = dict(os.environ)
    full_env.update(env)
    return subprocess.run([sys.executable, script] + args, capture_output=True, text=True,
                          cwd=cwd, env=full_env, stdin=subprocess.DEVNULL)


def _events(tmp_path):
    path = tmp_path / "progress.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class _bind_journal:
    """Context manager: point loop_journal at tmp_path and the progress env vars there too, then
    restore both on exit. Avoids the `monkeypatch` fixture so this test stays runnable under the
    bare-python3 fallback (`tests/_selfrun.py` only special-cases `tmp_path`)."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self._orig_loop_dir = None
        self._orig_journal = None
        self._orig_env = {}

    def __enter__(self):
        self._orig_loop_dir = loop_journal.LOOP_DIR
        self._orig_journal = loop_journal.JOURNAL
        loop_journal.LOOP_DIR = str(self.tmp_path)
        loop_journal.JOURNAL = str(self.tmp_path / "journal.jsonl")
        for k, v in _env(self.tmp_path).items():
            self._orig_env[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        loop_journal.LOOP_DIR = self._orig_loop_dir
        loop_journal.JOURNAL = self._orig_journal
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def test_journal_resume_emits_triage_begin_and_end(tmp_path):
    with _bind_journal(tmp_path):
        loop_journal.cmd_resume({})
        events = _events(tmp_path)
    steps = [(e["step"], e["status"]) for e in events]
    assert ("triage", "begin") in steps
    assert ("triage", "end") in steps


def test_journal_record_emits_journal_end_with_gate_outcome(tmp_path):
    with _bind_journal(tmp_path):
        loop_journal.cmd_record({"iteration": "1", "action": "fix test", "hypothesis": "h",
                                "gate": "pass"})
        events = _events(tmp_path)
    journal_end = [e for e in events if e["step"] == "journal" and e["status"] == "end"]
    assert journal_end, events
    assert journal_end[-1]["outcome"] == "pass"


def test_journal_stall_emits_blocked_with_stalled_detail_and_banner(tmp_path):
    with _bind_journal(tmp_path):
        fail_log = tmp_path / "fail.log"
        fail_log.write_text("AssertionError: boom\n", encoding="utf-8")
        for i in range(3):
            loop_journal.cmd_record({"iteration": str(i), "action": "same broken fix",
                                    "hypothesis": "h", "gate": "fail",
                                    "gate-output": str(fail_log)})
        events_before = len(_events(tmp_path))
        loop_journal.cmd_stall({"k": "3"})
        events = _events(tmp_path)
        assert len(events) > events_before
        blocked = [e for e in events if e["step"] == "journal" and e["status"] == "blocked"]
        assert blocked, events
        assert "STALLED" in blocked[-1]["detail"]
        header = loop_progress.render_turn_header(loop_progress.build_snapshot())
    assert "⚠ STALLED" in header, header


def test_anchor_drift_emits_blocked_with_drift_detail(tmp_path):
    env = _env(tmp_path)
    r1 = _run(ANCHOR, ["set", "--item", "T1", "--goal", "original goal",
                       "--ac", "A real criterion here"], str(tmp_path), env)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    r2 = _run(ANCHOR, ["check", "--goal", "a totally different goal"], str(tmp_path), env)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "drift" in r2.stdout.lower(), r2.stdout
    events = _events(tmp_path)
    drift_events = [e for e in events if e["step"] == "triage" and e["status"] == "blocked"]
    assert drift_events, events
    assert "DRIFT" in drift_events[-1]["detail"]


def test_watcher_verify_missing_challenge_emits_no_watcher_event(tmp_path):
    """No challenge on disk -> watcher_verify exits early; no misleading 'end' event fires
    (invariant: progress reports the gate, it is written only AFTER watcher_state.json)."""
    env = _env(tmp_path)
    env["SIMPLICIO_LOOP_REPO"] = str(tmp_path)
    r = _run(WATCHER, ["verify"], str(tmp_path), env)
    assert r.returncode == 1
    events = _events(tmp_path)
    watcher_events = [e for e in events if e["step"] == "watcher"]
    assert watcher_events == []


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_watcher_verify_match_false_emits_watcher_end_outcome_fail(tmp_path):
    """AC4 (issue #300) — dedicated FAIL pass: a challenge that cannot be matched against any
    evidence (no anchor, no independent/evidence receipt) makes watcher_verify write
    watcher_state.json with match=False and emit a `watcher end outcome=fail` progress event
    (never `blocked`/`begin`-only — the gate result IS the outcome)."""
    env = _env(tmp_path)
    env["SIMPLICIO_LOOP_REPO"] = str(tmp_path)
    loop_dir = tmp_path / ".simplicio-loop/orchestrator" / "loop"
    _write_json(str(loop_dir / "watcher_challenge.json"), {
        "challenge": "abc123", "goal_fp": "fp1", "iteration": 2,
        "written_at": "2026-07-10T00:00:00Z",
    })
    r = _run(WATCHER, ["verify"], str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("UNVERIFIED|"), r.stdout

    state_path = loop_dir / "watcher_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["match"] is False
    assert state["status"] == "UNVERIFIED"

    events = _events(tmp_path)
    watcher_events = [e for e in events if e["step"] == "watcher"]
    assert watcher_events, events
    assert watcher_events[-1]["status"] == "end"
    assert watcher_events[-1]["outcome"] == "fail", watcher_events[-1]


def test_watcher_verify_match_true_emits_watcher_end_outcome_pass(tmp_path):
    """AC4 (issue #300) — dedicated PASS pass: the mirror image of the FAIL test above. A
    challenge bound to an anchor whose criteria are both backed by a verified evidence receipt
    (with non-empty proof_refs) makes watcher_verify write watcher_state.json with match=True and
    emit `watcher end outcome=pass`."""
    env = _env(tmp_path)
    env["SIMPLICIO_LOOP_REPO"] = str(tmp_path)
    loop_dir = tmp_path / ".simplicio-loop/orchestrator" / "loop"
    _write_json(str(loop_dir / "watcher_challenge.json"), {
        "challenge": "abc123", "goal_fp": "fp1", "iteration": 2,
        "written_at": "2026-07-10T00:00:00Z",
    })
    _write_json(str(loop_dir / "anchor.json"), {
        "goal_fp": "fp1",
        "criteria": [
            {"id": "AC1", "status": "done"},
            {"id": "AC2", "status": "done"},
        ],
    })
    run_dir = tmp_path / ".simplicio-loop/orchestrator" / "runs" / "demo"
    _write_json(str(run_dir / "evidence-receipt.json"), {
        "schema": "simplicio.evidence-receipt/v1",
        "run_id": "demo",
        "status": "VERIFIED",
        "run": {"task_contract_hash": "hash1", "plan_hash": "hash2", "commit_sha": "", "diff_hash": ""},
        "criteria": [
            {"id": "AC1", "verification_state": "verified", "proof_refs": ["proof-1"]},
            {"id": "AC2", "verification_state": "verified", "proof_refs": ["proof-2"]},
        ],
        "summary": {"criteria_total": 2, "criteria_verified": 2, "scenario_total": 2,
                   "scenario_verified": 2, "rule_total": 1, "rule_verified": 1},
        "checks": [],
    })
    env["SIMPLICIO_RUN_DIR"] = str(run_dir)

    r = _run(WATCHER, ["verify"], str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("MEASURED|"), r.stdout

    state_path = loop_dir / "watcher_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["match"] is True
    assert state["status"] == "MEASURED"
    assert len(state["criteria_results"]) == 2

    events = _events(tmp_path)
    watcher_events = [e for e in events if e["step"] == "watcher"]
    assert watcher_events, events
    assert watcher_events[-1]["status"] == "end"
    assert watcher_events[-1]["outcome"] == "pass", watcher_events[-1]


def test_warning_banner_pure_function_drift_and_stalled():
    drift_snap = {"last_status": "blocked", "last_detail": "DRIFT detectado — re-anchor necessário"}
    assert loop_progress._warning_banner(drift_snap) == "⚠ DRIFT "
    stalled_snap = {"last_status": "blocked", "last_detail": "STALLED: 3 falhas com mesmo fingerprint"}
    assert loop_progress._warning_banner(stalled_snap) == "⚠ STALLED "
    clean_snap = {"last_status": "end", "last_detail": "all good"}
    assert loop_progress._warning_banner(clean_snap) == ""


def test_decide_event_has_llm_source_and_is_never_measured_tagged(tmp_path):
    env = _env(tmp_path)
    r = _run(PROGRESS, ["emit", "--step", "decide", "--status", "end", "--source", "llm",
                       "--detail", "target AC1: rename function"], str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    events = _events(tmp_path)
    decide = [e for e in events if e["step"] == "decide"]
    assert decide and decide[-1]["source"] == "llm"
    full = _run(PROGRESS, ["render", "--full"], str(tmp_path), env)
    assert full.returncode == 0, full.stdout + full.stderr
    for line in full.stdout.splitlines():
        if "decide" in line and line.strip().startswith("-"):
            assert not line.strip().startswith(("MEASURED|", "UNVERIFIED|")), line


def test_existing_selftests_stay_green_after_turn_instrumentation():
    for script in (JOURNAL_SCRIPT, ANCHOR, WATCHER):
        r = subprocess.run([sys.executable, script, "selftest"], capture_output=True, text=True,
                           cwd=REPO, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, "%s: %s" % (script, r.stdout + r.stderr)


def test_journal_help_is_side_effect_free_in_disposable_dir(tmp_path):
    env = _env(tmp_path)
    env["SIMPLICIO_REPO"] = str(tmp_path)
    commands = [
        ["--help"], ["-h"],
        *[[verb, flag] for verb in ("record", "fingerprint", "stall", "resume", "status",
                                    "since", "delegation", "claims-gate", "suggest", "selftest")
          for flag in ("--help", "-h")],
    ]
    for args in commands:
        result = _run(JOURNAL_SCRIPT, args, str(tmp_path), env)
        assert result.returncode == 0, args + [result.stdout, result.stderr]
    assert list(tmp_path.rglob("*")) == [], "help created state: %s" % list(tmp_path.rglob("*"))


def test_journal_invalid_record_args_do_not_create_state(tmp_path):
    env = _env(tmp_path)
    env["SIMPLICIO_REPO"] = str(tmp_path)
    invalid = [
        ["record"],
        ["record", "--iteration", "1"],
        ["record", "--iteration", "bad", "--action", "x", "--gate", "pass"],
        ["record", "--iteration", "1", "--action", "x", "--gate", "pass", "--bogus", "x"],
        ["record", "--iteration", "-1", "--action", "x", "--gate", "pass"],
        ["record", "--iteration", "1", "--action", "x", "--gate", "oops"],
        ["record", "--iteration", "1", "--action", "x", "--gate", "fail", "--gate-output", "missing.log"],
        ["record", "--iteration", "1", "--action", "x", "--gate", "fail"],
        ["record", "--iteration", "1", "--gate", "pass"],
    ]
    for args in invalid:
        result = _run(JOURNAL_SCRIPT, args, str(tmp_path), env)
        assert result.returncode == 2, args + [result.stdout, result.stderr]
        assert "invalid arguments" in result.stderr, result.stderr
    assert list(tmp_path.rglob("*")) == [], "invalid record created state"


def test_journal_valid_record_appends_one_row_without_hypothesis(tmp_path):
    env = _env(tmp_path)
    env["SIMPLICIO_REPO"] = str(tmp_path)
    result = _run(JOURNAL_SCRIPT,
                   ["record", "--iteration", "1", "--action", "hook", "--gate", "pass"],
                   str(tmp_path), env)
    assert result.returncode == 0, result.stdout + result.stderr
    journal = tmp_path / ".simplicio-loop" / "orchestrator" / "loop" / "journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["iteration"] == 1
    assert rows[0]["action"] == "hook"
    assert rows[0]["gate"] == "pass"
    assert rows[0]["hypothesis"] == ""

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_turn_progress")
