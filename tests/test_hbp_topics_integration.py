"""#128: journal consumes dev-cli events + the new HBP evidence-chain points.

Two halves, both deterministic:

1. `scripts/loop_journal.py` optionally folds the dev-cli's OWN event log
   (`<repo>/.simplicio-loop/events.jsonl`, schema `simplicio.dev-cli-event/v1` — the documented
   contract from simplicio-dev-cli's `observability.emit_event`, read by shape, never imported)
   into the attempt fingerprint + stall detector: a repeated `validation_fail` on the same
   target streaks to STALLED exactly like a repeated journal failure; `edit_applied`/
   `task_complete` reset the streak; a missing/corrupt file changes nothing (fail-open).

2. The three new HBP producers append to the runtime's tamper-evident chain via
   `simplicio hbp append` and are FAIL-OPEN like the pre-existing promise-verified append
   (`hooks/loop_stop.py::_call_simplicio_hbp_append`): with a FAKE `simplicio` binary on PATH the
   exact topic + payload go through; with the binary ABSENT the caller degrades silently — never
   a crash, never a changed decision. (Producer discipline per tests/test_evidence_chain.py:
   prove the positive chain with fixtures shaped like the real producer's output, and prove the
   absent-toolchain path degrades rather than fakes.)
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import loop_journal as lj  # noqa: E402

HOOK = os.path.join(REPO, "hooks", "loop_stop.py")
GATE = os.path.join(REPO, "hooks", "action_gate.py")

SCHEMA = "simplicio.dev-cli-event/v1"


def _event(event, target="src/app.py", ts="2026-07-09T00:00:00Z", warnings=None, attempt=1):
    """A record shaped exactly like observability.emit_event()'s documented on-disk contract."""
    return {"schema": SCHEMA, "ts": ts, "event": event, "level": "info",
            "payload": {"target": target, "attempt": attempt, "warnings": warnings or []}}


def _write_events(root, records, extra_lines=()):
    d = os.path.join(root, ".simplicio-loop")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "events.jsonl"), "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
        for ln in extra_lines:
            f.write(ln + "\n")


# ── half 1: dev-cli events -> stall detector ────────────────────────────────────────────────


def test_missing_events_file_changes_nothing(tmp_path):
    events, corrupt = lj.load_dev_cli_events(str(tmp_path))
    assert events == [] and corrupt == 0
    rows = [{"gate": "fail", "fingerprint": "aaa", "ts": "t", "action": "x"}]
    assert lj.merge_dev_cli(rows, events) == rows  # identical behavior to today


def test_repeated_validation_fail_same_target_streaks_to_stalled(tmp_path):
    root = str(tmp_path)
    _write_events(root, [
        _event("validation_fail", ts="2026-07-09T00:00:0%dZ" % i, warnings=["pytest failed"])
        for i in (1, 2, 3)
    ])
    events, corrupt = lj.load_dev_cli_events(root)
    assert len(events) == 3 and corrupt == 0
    verdict = lj.analyze(lj.merge_dev_cli([], events), 3)
    assert verdict["verdict"] == "STALLED", verdict
    assert verdict["stall_count"] == 3


def test_different_targets_do_not_streak(tmp_path):
    root = str(tmp_path)
    _write_events(root, [
        _event("validation_fail", target="a.py", ts="2026-07-09T00:00:01Z", warnings=["boom"]),
        _event("validation_fail", target="b.py", ts="2026-07-09T00:00:02Z", warnings=["boom"]),
        _event("validation_fail", target="c.py", ts="2026-07-09T00:00:03Z", warnings=["boom"]),
    ])
    events, _ = lj.load_dev_cli_events(root)
    assert lj.analyze(lj.merge_dev_cli([], events), 3)["verdict"] == "PROGRESS"


def test_task_complete_resets_the_streak(tmp_path):
    root = str(tmp_path)
    _write_events(root, [
        _event("validation_fail", ts="2026-07-09T00:00:01Z", warnings=["boom"]),
        _event("validation_fail", ts="2026-07-09T00:00:02Z", warnings=["boom"]),
        _event("validation_fail", ts="2026-07-09T00:00:03Z", warnings=["boom"]),
        _event("task_complete", ts="2026-07-09T00:00:04Z"),
    ])
    events, _ = lj.load_dev_cli_events(root)
    assert lj.analyze(lj.merge_dev_cli([], events), 3)["verdict"] == "PROGRESS"


def test_events_merge_chronologically_with_journal_rows(tmp_path):
    # A journal fail + two dev-cli fails on the same signature must form ONE trailing streak.
    root = str(tmp_path)
    ev = [_event("validation_fail", ts="2026-07-09T00:00:0%dZ" % i, warnings=["boom"])
          for i in (2, 3)]
    _write_events(root, ev)
    events, _ = lj.load_dev_cli_events(root)
    fp = lj._dev_cli_fingerprint(ev[0])
    rows = [{"gate": "fail", "fingerprint": fp, "ts": "2026-07-09T00:00:01Z", "action": "manual"}]
    verdict = lj.analyze(lj.merge_dev_cli(rows, events), 3)
    assert verdict["verdict"] == "STALLED", verdict
    assert verdict["stall_count"] == 3


def test_corrupt_and_foreign_lines_are_tolerated(tmp_path):
    root = str(tmp_path)
    _write_events(root, [_event("validation_fail", warnings=["boom"])],
                  extra_lines=['{"torn json', json.dumps({"schema": "other/v9", "event": "x"}),
                               json.dumps(["not", "a", "dict"])])
    events, corrupt = lj.load_dev_cli_events(root)
    assert len(events) == 1     # only the real dev-cli event
    assert corrupt == 1         # only the torn line counts as corrupt; foreign schema is skipped


def test_stall_cli_consumes_events_via_events_root(tmp_path):
    # End-to-end through the real CLI: copy the worker (+ its sibling imports) into an isolated
    # repo dir, journal EMPTY, only dev-cli events present -> `stall --format json` = STALLED.
    root = str(tmp_path)
    scripts = os.path.join(root, "scripts")
    os.makedirs(scripts)
    for mod in ("loop_journal.py", "toon_codec.py", "_locked_append.py"):
        shutil.copy2(os.path.join(REPO, "scripts", mod), os.path.join(scripts, mod))
    _write_events(root, [
        _event("validation_fail", ts="2026-07-09T00:00:0%dZ" % i, warnings=["pytest failed"])
        for i in (1, 2, 3)
    ])
    r = subprocess.run([sys.executable, os.path.join(scripts, "loop_journal.py"),
                        "stall", "--format", "json"],
                       capture_output=True, stdin=subprocess.DEVNULL, text=True, cwd=root)
    assert r.returncode == 0, r.stdout + r.stderr
    verdict = json.loads(r.stdout)
    assert verdict["verdict"] == "STALLED", verdict
    # and --events-root pointing somewhere empty restores today's behavior
    empty = os.path.join(root, "elsewhere")
    os.makedirs(empty)
    r2 = subprocess.run([sys.executable, os.path.join(scripts, "loop_journal.py"),
                         "stall", "--format", "json", "--events-root", empty],
                        capture_output=True, stdin=subprocess.DEVNULL, text=True, cwd=root)
    assert json.loads(r2.stdout)["verdict"] == "PROGRESS", r2.stdout


# ── half 2: HBP producers (fake / absent binary) ────────────────────────────────────────────


def _fake_simplicio(bin_dir, log_path):
    """A fake `simplicio` binary that appends its argv (one call per line) to log_path."""
    os.makedirs(bin_dir, exist_ok=True)
    if os.name == "nt":  # pragma: no cover — POSIX CI
        path = os.path.join(bin_dir, "simplicio.bat")
        with open(path, "w", encoding="utf-8") as f:
            f.write('@echo off\r\necho %%* >> "%s"\r\n' % log_path)
    else:
        path = os.path.join(bin_dir, "simplicio")
        with open(path, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{}"\n'.format(log_path))
        os.chmod(path, 0o755)
    return path


def _calls(log_path):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()]


SCRATCHPAD = """---
iteration: {iteration}
max_iterations: {max_iter}
completion_promise: "SIMPLICIO_DONE"
evidence_required: true
started_at: "2026-06-24T00:00:00Z"
---
Implement the thing and prove it works.
"""


def _arm(root, iteration=1, max_iter=5):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write(SCRATCHPAD.format(iteration=iteration, max_iter=max_iter))
    return loop


def _write_stalled_journal(root, fp="deadbeef0001", n=3):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "journal.jsonl"), "w", encoding="utf-8") as f:
        for i in range(1, n + 1):
            f.write(json.dumps({"iteration": i, "action": "retry fetch", "gate": "fail",
                                "fingerprint": fp, "ts": "2026-07-09T00:00:0%dZ" % i}) + "\n")


def _tick(root, text, env):
    return subprocess.run([sys.executable, HOOK], input=json.dumps({"text": text}),
                          capture_output=True, text=True, cwd=root, env=env)


def test_stall_detected_appends_hbp_topic(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=3, max_iter=10)
    _write_stalled_journal(root)
    log = os.path.join(root, "hbp_calls.log")
    bin_dir = os.path.join(root, "bin")
    _fake_simplicio(bin_dir, log)
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
    _tick(root, "still failing, no promise", env)
    calls = _calls(log)
    stall = [c for c in calls if "loop-stall-detected" in c]
    assert stall, "a 3-deep same-fingerprint streak must append loop-stall-detected: %s" % calls
    assert "deadbeef0001" in stall[0], stall[0]
    assert "hbp append" in stall[0]


def test_run_blocked_on_cap_appends_hbp_topic(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=5, max_iter=5)  # at the cap -> run blocked
    log = os.path.join(root, "hbp_calls.log")
    bin_dir = os.path.join(root, "bin")
    _fake_simplicio(bin_dir, log)
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
    r = _tick(root, "still working", env)
    assert r.stdout.strip() == "", "cap must stop the loop:\n%s" % r.stdout
    blocked = [c for c in _calls(log) if "loop-run-blocked" in c]
    assert blocked, "cap-reached stop must append loop-run-blocked: %s" % _calls(log)
    assert "max_iterations cap reached" in blocked[0]


def test_run_blocked_on_missing_operator_appends_hbp_topic(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=9)
    skill_dir = os.path.join(root, ".claude", "skills", "simplicio-loop")
    os.makedirs(skill_dir, exist_ok=True)
    open(os.path.join(skill_dir, "SKILL.md"), "w").close()
    log = os.path.join(root, "hbp_calls.log")
    bin_dir = os.path.join(root, "bin")
    _fake_simplicio(bin_dir, log)  # simplicio IS on PATH; mapper/dev-cli are NOT
    env = dict(os.environ, PATH=bin_dir)
    r = _tick(root, "no promise yet", env)
    assert r.stdout.strip() == "", r.stdout
    blocked = [c for c in _calls(log) if "loop-run-blocked" in c]
    assert blocked, "operator-missing block must append loop-run-blocked: %s" % _calls(log)
    assert "bound operator missing" in blocked[0]


def test_gate_blocked_appends_hbp_topic(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, ".simplicio-loop/orchestrator"), exist_ok=True)  # project-relevance marker
    log = os.path.join(root, "hbp_calls.log")
    bin_dir = os.path.join(root, "bin")
    _fake_simplicio(bin_dir, log)
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run([sys.executable, GATE, "check", "--command",
                        "git push --force origin main"],
                       capture_output=True, stdin=subprocess.DEVNULL, text=True, cwd=root, env=env)
    assert r.returncode == 2, "force-push must still be blocked (exit 2)"
    blocked = [c for c in _calls(log) if "loop-gate-blocked" in c]
    assert blocked, "a gate BLOCK must append loop-gate-blocked: %s" % _calls(log)
    assert "fingerprint" in blocked[0]


def test_all_producers_degrade_silently_without_binary(tmp_path):
    # Absent `simplicio`: every path still reaches its own decision — never a crash, no append.
    root = str(tmp_path)
    empty = os.path.join(root, "empty-bin")
    os.makedirs(empty)
    env = dict(os.environ, PATH=empty)

    # stall path (journal stalled, no binary): hook still re-feeds normally
    _arm(root, iteration=3, max_iter=10)
    _write_stalled_journal(root)
    r = _tick(root, "still failing, no promise", env)
    assert r.returncode == 0
    assert "followup_message" in r.stdout, "stall append absent-binary must not break the re-feed"

    # cap path: still a clean stop
    _arm(root, iteration=10, max_iter=10)
    r = _tick(root, "still working", env)
    assert r.returncode == 0 and r.stdout.strip() == ""

    # gate path: still blocks with exit 2 (PATH needs git for the classify-only path — none used)
    r = subprocess.run([sys.executable, GATE, "check", "--command",
                        "git push --force origin main"],
                       capture_output=True, stdin=subprocess.DEVNULL, text=True, cwd=root, env=env)
    assert r.returncode == 2, "gate must still block without the runtime binary"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_hbp_topics")
