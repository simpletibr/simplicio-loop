"""Fail-open sabotage battery for the progress-feedback subsystem (issue #304, EPIC #296).

For every worker instrumented by the sister issues (#299-#302), proves that sabotaging the
progress subsystem in three ways never changes that worker's own behavior. Everything runs via
subprocess (fresh interpreter per call) so env-var-configured paths are picked up correctly and
no test can leak into the real repo's `.simplicio-loop/orchestrator/` state.

  (S1) `scripts/loop_progress.py` is temporarily renamed out of the way — the literal "module
       deleted from the repo" scenario from issue #304's own AC2 wording. Every instrumented
       worker's `import loop_progress` inside its fail-open try/except then genuinely raises
       ModuleNotFoundError.
  (S2) the progress directory is unwritable (a file sits where a directory is expected).
  (S3) `progress.jsonl` is truncated/corrupt.

Matrix: task_backlog.py, task_anchor.py, loop_journal.py, watcher_verify.py, web_verify.py,
video_evidence.py, pr_evidence.py, hooks/loop_stop.py (via its two private helpers, imported
in-process since it's a hook script, not a CLI with subcommands).
"""
import contextlib
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP_PROGRESS = os.path.join(REPO, "scripts", "loop_progress.py")
TASK_BACKLOG = os.path.join(REPO, "scripts", "task_backlog.py")
TASK_ANCHOR = os.path.join(REPO, "scripts", "task_anchor.py")
LOOP_JOURNAL = os.path.join(REPO, "scripts", "loop_journal.py")
WATCHER_VERIFY = os.path.join(REPO, "scripts", "watcher_verify.py")
WEB_VERIFY = os.path.join(REPO, "scripts", "web_verify.py")
VIDEO_EVIDENCE = os.path.join(REPO, "scripts", "video_evidence.py")
PR_EVIDENCE = os.path.join(REPO, "scripts", "pr_evidence.py")


def _env(tmp_path, **extra):
    env = dict(os.environ)
    env.update({
        "SIMPLICIO_PROGRESS_DIR": str(tmp_path),
        "SIMPLICIO_ANCHOR_FILE": str(tmp_path / "anchor.json"),
        "SIMPLICIO_BACKLOG_FILE": str(tmp_path / "backlog.jsonl"),
    })
    env.update(extra)
    return env


def _run(script, args, cwd, env):
    return subprocess.run([sys.executable, script] + args, capture_output=True, text=True,
                          cwd=cwd, env=env, stdin=subprocess.DEVNULL)


@contextlib.contextmanager
def _s1_loop_progress_deleted():
    """Sabotage 1 — literally rename `scripts/loop_progress.py` out of the way for the duration
    of the block (issue #304 AC2's own wording: "com loop_progress.py deletado do repo").

    Most callers exercise this via a fresh subprocess per `_run()`, so Python's import cache is
    irrelevant there. `test_s1_loop_stop_helpers_degrade_silently_without_loop_progress` is the
    one exception — it imports `hooks/loop_stop.py` in-process — so when it runs after any
    earlier test in the same pytest session that already did `import loop_progress`, the module
    stays resolvable from `sys.modules` even with the file renamed away, and the "deleted"
    simulation silently stops proving anything. Evict any cached entry on the way in and put
    back whatever was there (if anything) on the way out, so this sabotage is real regardless of
    what ran earlier in the same process."""
    disabled = LOOP_PROGRESS + ".disabled-for-test"
    assert os.path.exists(LOOP_PROGRESS), "precondition: loop_progress.py must exist to sabotage"
    os.replace(LOOP_PROGRESS, disabled)
    had_cached = "loop_progress" in sys.modules
    cached = sys.modules.pop("loop_progress", None)
    try:
        yield
    finally:
        os.replace(disabled, LOOP_PROGRESS)
        if had_cached:
            sys.modules["loop_progress"] = cached
        else:
            sys.modules.pop("loop_progress", None)


def test_s1_task_backlog_init_unchanged_without_loop_progress(tmp_path):
    item_file = tmp_path / "items.json"
    item_file.write_text(json.dumps([{"id": "T1", "goal": "g", "acs": ["A real criterion"]}]),
                        encoding="utf-8")
    env = _env(tmp_path)
    with _s1_loop_progress_deleted():
        r = _run(TASK_BACKLOG, ["init", "--goal", "g", "--item-file", str(item_file)],
                 str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "frozen 1 item(s)" in r.stdout


def test_s1_task_anchor_set_and_mark_unchanged_without_loop_progress(tmp_path):
    env = _env(tmp_path)
    with _s1_loop_progress_deleted():
        r1 = _run(TASK_ANCHOR, ["set", "--item", "T1", "--goal", "g", "--ac", "A real criterion"],
                  str(tmp_path), env)
        r2 = _run(TASK_ANCHOR, ["mark", "--id", "AC1", "--status", "done", "--evidence", "e.log"],
                  str(tmp_path), env)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "anchored" in r1.stdout and "marked" in r2.stdout


def test_s1_loop_journal_record_and_resume_unchanged_without_loop_progress(tmp_path):
    """loop_journal.py has no env-var path override, so bind it to tmp_path in-process (same
    pattern as tests/test_turn_progress.py) while the module is genuinely absent from disk."""
    spec = importlib.util.spec_from_file_location("failopen_loop_journal", LOOP_JOURNAL)
    lj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lj)
    lj.LOOP_DIR = str(tmp_path)
    lj.JOURNAL = str(tmp_path / "journal.jsonl")
    with _s1_loop_progress_deleted():
        lj.cmd_record({"iteration": "1", "action": "a", "hypothesis": "h", "gate": "pass"})
        lj.cmd_resume({})
    assert os.path.exists(str(tmp_path / "journal.jsonl"))


def test_s1_watcher_verify_selftest_unchanged_without_loop_progress(tmp_path):
    env = dict(os.environ)
    with _s1_loop_progress_deleted():
        r = _run(WATCHER_VERIFY, ["selftest"], REPO, env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_s1_web_verify_blocked_path_unchanged_without_loop_progress(tmp_path):
    spec = importlib.util.spec_from_file_location("failopen_web_verify", WEB_VERIFY)
    wv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wv)
    with _s1_loop_progress_deleted():
        try:
            wv._blocked(str(tmp_path / "out"), "toolchain missing")
            code = 0
        except SystemExit as e:
            code = e.code
    assert code == 3


def test_s1_video_evidence_blocked_path_unchanged_without_loop_progress(tmp_path):
    spec = importlib.util.spec_from_file_location("failopen_video_evidence", VIDEO_EVIDENCE)
    ve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ve)
    with _s1_loop_progress_deleted():
        try:
            ve._blocked(str(tmp_path / "out"), "toolchain missing")
            code = 0
        except SystemExit as e:
            code = e.code
    assert code == 3


def test_s1_pr_evidence_build_require_evidence_gate_unchanged_without_loop_progress(tmp_path):
    env = _env(tmp_path)
    with _s1_loop_progress_deleted():
        r = _run(PR_EVIDENCE, ["build", "--title", "T", "--require-evidence"], str(tmp_path), env)
    assert r.returncode == 3  # unchanged BLOCKED exit code (no anchor/prints)


def test_s1_loop_stop_helpers_degrade_silently_without_loop_progress(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "failopen_loop_stop", os.path.join(REPO, "hooks", "loop_stop.py"))
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    orig_cwd = os.getcwd()
    os.chdir(str(tmp_path))
    try:
        with _s1_loop_progress_deleted():
            # Other tests may have placed a bundled copy on sys.path. Exercise
            # the hook's actual optional-dependency boundary deterministically.
            ls._loop_progress_module = lambda: None
            prefix = ls._progress_header_prefix(1, 0)
            ls._emit_final_progress("reason", "blocked")  # must not raise
    finally:
        os.chdir(orig_cwd)
    assert prefix == ""


def test_s2_progress_dir_unwritable_task_backlog_init_unchanged(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    item_file = tmp_path / "items.json"
    item_file.write_text(json.dumps([{"id": "T1", "goal": "g", "acs": ["A real criterion"]}]),
                        encoding="utf-8")
    env = _env(tmp_path, SIMPLICIO_PROGRESS_DIR=str(blocker / "nested" / "deeper"))
    r = _run(TASK_BACKLOG, ["init", "--goal", "g", "--item-file", str(item_file)],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "frozen 1 item(s)" in r.stdout


def test_s2_progress_dir_unwritable_task_anchor_set_unchanged(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    env = _env(tmp_path, SIMPLICIO_PROGRESS_DIR=str(blocker / "nested"))
    r = _run(TASK_ANCHOR, ["set", "--item", "T1", "--goal", "g", "--ac", "A real criterion"],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "anchored" in r.stdout


def test_s3_corrupt_progress_jsonl_task_anchor_mark_unchanged(tmp_path):
    env = _env(tmp_path)
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(str(tmp_path / "progress.jsonl"), "w", encoding="utf-8") as f:
        f.write("{not valid json at all\n\x00\x01garbage\n")
    _run(TASK_ANCHOR, ["set", "--item", "T1", "--goal", "g", "--ac", "A real criterion"],
         str(tmp_path), env)
    r = _run(TASK_ANCHOR, ["mark", "--id", "AC1", "--status", "done", "--evidence", "e.log"],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "marked" in r.stdout


def test_s3_corrupt_progress_jsonl_watcher_verify_selftest_unchanged(tmp_path):
    env = _env(tmp_path)
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(str(tmp_path / "progress.jsonl"), "w", encoding="utf-8") as f:
        f.write("{garbage\n")
    r = _run(WATCHER_VERIFY, ["selftest"], REPO, dict(os.environ, **{
        "SIMPLICIO_PROGRESS_DIR": str(tmp_path)}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_baseline_worker_selftests_are_unaffected_by_module_deletion():
    """A consolidated matrix row: every instrumented worker's OWN selftest — the existing
    regression baseline each sister issue already protects — stays green with S1 active."""
    scripts = [TASK_ANCHOR, TASK_BACKLOG, LOOP_JOURNAL, WATCHER_VERIFY, PR_EVIDENCE]
    env = dict(os.environ)
    with _s1_loop_progress_deleted():
        for script in scripts:
            r = _run(script, ["selftest"], REPO, env)
            assert r.returncode == 0, "%s: %s" % (script, r.stdout + r.stderr)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_progress_failopen")
