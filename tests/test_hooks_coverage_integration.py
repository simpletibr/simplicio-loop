"""#78: coverage for the previously-untested small hooks — orient_clamp.py, orient_rewrite.py,
loop_capture.py, simplicio_watch.py. (learn_stop.py, also on the original list, was removed
entirely by #69 — see tests/test_learn_pipeline_removed.py.)
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_hook(name, args=None, stdin_data=None, cwd=None, env=None):
    cmd = [sys.executable, os.path.join(REPO, "hooks", name)] + (args or [])
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "cwd": cwd or REPO,
        "env": full_env,
    }
    if stdin_data is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_data
    return subprocess.run(cmd, **kwargs)


# ── orient_clamp.py ─────────────────────────────────────────────────────────


def test_orient_clamp_usage_error_without_double_dash(tmp_path):
    r = _run_hook("orient_clamp.py", args=["echo", "hi"], cwd=str(tmp_path))
    assert r.returncode == 2
    assert "usage" in r.stderr.lower()


def test_orient_clamp_propagates_real_exit_code(tmp_path):
    r = _run_hook("orient_clamp.py",
                  args=["--", sys.executable, "-c", "import sys; sys.exit(7)"],
                  cwd=str(tmp_path))
    assert r.returncode == 7, "must propagate the REAL exit code, never swallow it"


def test_orient_clamp_collapses_clean_output_to_one_line(tmp_path):
    # success-collapse fires when the first line matches CLEAN_RE ("ok", "done", "passed", ...)
    # and the run had no error/warning signal — the noisy detail lines are dropped entirely.
    r = _run_hook(
        "orient_clamp.py",
        args=["--", sys.executable, "-c",
              "print('passed'); print('42 examples, 0 failures'); print('done in 1.2s')"],
        cwd=str(tmp_path),
    )
    assert r.returncode == 0
    assert r.stdout.count("\n") <= 2, r.stdout


def test_orient_clamp_keeps_error_signal_and_tees_on_failure(tmp_path):
    r = _run_hook(
        "orient_clamp.py",
        args=["--", sys.executable, "-c",
              "import sys; print('starting'); print('Error: boom'); sys.exit(1)"],
        cwd=str(tmp_path),
    )
    assert r.returncode == 1
    assert "Error: boom" in r.stdout
    tee_dir = tmp_path / ".simplicio-loop/orchestrator" / "tee"
    assert tee_dir.is_dir() and list(tee_dir.iterdir()), "a failing command should tee full output"


def test_orient_clamp_excluded_command_runs_raw_unclamped(tmp_path):
    # `less` is in DEFAULT_EXCLUDES — must run through subprocess.call unchanged (no clamp text,
    # no tee, no reduction), whatever its own exit behavior is on this machine.
    r = _run_hook("orient_clamp.py", args=["--", "less", "--version"], cwd=str(tmp_path))
    assert r.returncode in (0, 1, 127), r.stdout + r.stderr
    assert not (tmp_path / ".simplicio-loop/orchestrator" / "tee").exists(), "an excluded command must never be teed"


def test_orient_clamp_json_mode_reports_reduction(tmp_path):
    r = _run_hook(
        "orient_clamp.py",
        args=["--json", "--", sys.executable, "-c", "print('a'); print('b'); print('c')"],
        cwd=str(tmp_path),
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["exit"] == 0
    assert "reduced" in payload and "raw_chars" in payload


# ── orient_rewrite.py ────────────────────────────────────────────────────────


def _rewrite(tool_input, cwd, env=None):
    r = _run_hook("orient_rewrite.py", stdin_data=json.dumps({"tool_input": tool_input}),
                  cwd=cwd, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_orient_rewrite_noop_outside_a_simplicio_loop_project(tmp_path):
    out = _rewrite({"command": "git status"}, cwd=str(tmp_path))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "updatedInput" not in out["hookSpecificOutput"], \
        "outside a project the command must be left unchanged"


def test_orient_rewrite_wraps_allowed_readonly_command_inside_project(tmp_path):
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    out = _rewrite({"command": "git status"}, cwd=str(tmp_path))
    updated = out["hookSpecificOutput"].get("updatedInput", {}).get("command", "")
    assert "orient_clamp.py" in updated and "git status" in updated


def test_orient_rewrite_env_var_gate_without_orchestrator_dir(tmp_path):
    out = _rewrite({"command": "git log"}, cwd=str(tmp_path), env={"SIMPLICIO_LOOP": "1"})
    updated = out["hookSpecificOutput"].get("updatedInput", {}).get("command", "")
    assert "orient_clamp.py" in updated, "the env-var opt-in gate should also enable rewriting"


def test_orient_rewrite_leaves_compound_command_unchanged(tmp_path):
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    out = _rewrite({"command": "git status && rm -rf /tmp/x"}, cwd=str(tmp_path))
    assert "updatedInput" not in out["hookSpecificOutput"], \
        "a compound/unsafe-shaped command must never be rewritten"


def test_orient_rewrite_leaves_non_allowlisted_command_unchanged(tmp_path):
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    out = _rewrite({"command": "npm install left-pad"}, cwd=str(tmp_path))
    assert "updatedInput" not in out["hookSpecificOutput"], \
        "a write command outside the read-only allowlist must never be rewritten"


def test_orient_rewrite_leaves_already_wrapped_command_unchanged(tmp_path):
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    out = _rewrite({"command": 'python3 "hooks/orient_clamp.py" -- git status'}, cwd=str(tmp_path))
    assert "updatedInput" not in out["hookSpecificOutput"]


# ── loop_capture.py ──────────────────────────────────────────────────────────


def _arm_capture(root, promise="SIMPLICIO_DONE", evidence_required=True):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write("---\niteration: 1\nmax_iterations: 5\ncompletion_promise: \"%s\"\n"
                 "evidence_required: %s\n---\ngoal\n" % (promise, str(evidence_required).lower()))
    return loop


def _done_flag_exists(root):
    return os.path.exists(os.path.join(root, ".simplicio-loop/orchestrator", "loop", "done"))


def test_loop_capture_does_not_raise_done_flag_with_evidence(tmp_path):
    root = str(tmp_path)
    _arm_capture(root)
    r = _run_hook("loop_capture.py",
                  stdin_data=json.dumps({"text": "All good. <promise>SIMPLICIO_DONE</promise> "
                                                  "tests pass ✓ https://github.com/o/r/pull/1"}),
                  cwd=root)
    assert r.returncode == 0
    assert not _done_flag_exists(root), "capture hook must only stash the response, never decide completion"


def test_loop_capture_no_flag_without_evidence(tmp_path):
    root = str(tmp_path)
    _arm_capture(root)
    r = _run_hook("loop_capture.py",
                  stdin_data=json.dumps({"text": "<promise>SIMPLICIO_DONE</promise>"}),
                  cwd=root)
    assert r.returncode == 0
    assert not _done_flag_exists(root), "a bare promise without evidence must not raise done"


def test_loop_capture_no_flag_with_pending_anchor(tmp_path):
    root = str(tmp_path)
    _arm_capture(root)
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    with open(os.path.join(loop, "anchor.json"), "w", encoding="utf-8") as f:
        json.dump({"goal_fp": "x", "criteria": [{"id": "AC1", "status": "pending"}]}, f)
    r = _run_hook("loop_capture.py",
                  stdin_data=json.dumps({"text": "<promise>SIMPLICIO_DONE</promise> ok ✓ "
                                                  "https://github.com/o/r/pull/1"}),
                  cwd=root)
    assert r.returncode == 0
    assert not _done_flag_exists(root), "capture hook must not raise done even when an anchor exists"


def test_loop_capture_noop_without_scratchpad(tmp_path):
    root = str(tmp_path)
    r = _run_hook("loop_capture.py", stdin_data=json.dumps({"text": "<promise>X</promise>"}),
                  cwd=root)
    assert r.returncode == 0
    assert not _done_flag_exists(root)


def test_loop_capture_stashes_last_response(tmp_path):
    root = str(tmp_path)
    _run_hook("loop_capture.py", stdin_data=json.dumps({"text": "hello world"}), cwd=root)
    last_resp = os.path.join(root, ".simplicio-loop/orchestrator", "loop", "last_response.txt")
    assert os.path.exists(last_resp)
    assert open(last_resp, encoding="utf-8").read() == "hello world"


# ── simplicio_watch.py ───────────────────────────────────────────────────────


def test_simplicio_watch_unknown_command_prints_usage():
    r = _run_hook("simplicio_watch.py", args=["bogus-command"])
    assert r.returncode == 1
    assert "usage" in (r.stdout + r.stderr).lower()


def test_simplicio_watch_status_does_not_crash_without_a_running_proxy(tmp_path):
    # No proxy is running in this sandbox — status must report cleanly, not throw.
    r = _run_hook("simplicio_watch.py", args=["status"], cwd=str(tmp_path))
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "Simplicio proxy" in r.stdout


def test_simplicio_watch_start_prints_instructions_without_crashing():
    r = _run_hook("simplicio_watch.py", args=["start"])
    assert r.returncode == 0
    assert "proxy" in r.stdout.lower()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_hooks_coverage")
