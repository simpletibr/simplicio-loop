"""Regression tests for issue #1291: task_backlog.py / task_anchor.py / loop_progress.py must
answer --help/-h (top level and after a verb) without touching state files, and must fail closed
on an unknown flag instead of silently ignoring it (the original bug: `next --owner w1` recorded
the lease as `__anonymous__` because the real flag is `--worker`).
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = {
    "task_backlog": os.path.join(REPO, "scripts", "task_backlog.py"),
    "task_anchor": os.path.join(REPO, "scripts", "task_anchor.py"),
    "loop_progress": os.path.join(REPO, "scripts", "loop_progress.py"),
}


def _run(script, args, cwd, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, script] + args, capture_output=True, text=True,
                          cwd=cwd, env=full_env, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_top_level_help_prints_doc_and_exits_zero(name, tmp_path):
    for flag in ("--help", "-h"):
        r = _run(SCRIPTS[name], [flag], cwd=tmp_path)
        assert r.returncode == 0, (flag, r.stdout, r.stderr)
        assert r.stdout.strip(), (flag, "empty usage output")
        assert not list(tmp_path.iterdir()), "help must not touch state files"


@pytest.mark.parametrize("name, verb", [
    ("task_backlog", "next"),
    ("task_backlog", "status"),
    ("task_anchor", "check"),
    ("task_anchor", "status"),
    ("loop_progress", "status"),
    ("loop_progress", "render"),
])
def test_per_verb_help_prints_doc_and_exits_zero_without_state(name, verb, tmp_path):
    env = {
        "SIMPLICIO_BACKLOG_FILE": str(tmp_path / "backlog.jsonl"),
        "SIMPLICIO_ANCHOR_FILE": str(tmp_path / "anchor.json"),
        "SIMPLICIO_PROGRESS_DIR": str(tmp_path / "progress"),
    }
    for flag in ("--help", "-h"):
        r = _run(SCRIPTS[name], [verb, flag], cwd=tmp_path, env=env)
        assert r.returncode == 0, (name, verb, flag, r.stdout, r.stderr)
        assert r.stdout.strip()
        # no state files created by a --help/-h invocation
        assert not os.path.exists(env["SIMPLICIO_BACKLOG_FILE"])
        assert not os.path.exists(env["SIMPLICIO_ANCHOR_FILE"])
        assert not os.path.exists(env["SIMPLICIO_PROGRESS_DIR"])


def test_backlog_next_rejects_unknown_flag_instead_of_silently_ignoring_it(tmp_path):
    """The original bug report: `next --owner w1` used to silently succeed and record the lease
    as __anonymous__ because --owner is not a real flag (the real one is --worker)."""
    backlog_file = tmp_path / "backlog.jsonl"
    env = {"SIMPLICIO_BACKLOG_FILE": str(backlog_file)}
    # freeze one ready item first
    item = json.dumps({"id": "T1", "goal": "do the thing", "acs": ["do the real thing"]})
    r_init = _run(SCRIPTS["task_backlog"],
                 ["init", "--goal", "Drain", "--item", item], cwd=tmp_path, env=env)
    assert r_init.returncode == 0, (r_init.stdout, r_init.stderr)

    r = _run(SCRIPTS["task_backlog"], ["next", "--owner", "w1"], cwd=tmp_path, env=env)
    assert r.returncode != 0, r.stdout
    assert "--owner" in r.stderr
    assert "--worker" in r.stderr
    # the claim must not have gone through under an anonymous lease
    assert "__anonymous__" not in backlog_file.read_text()


@pytest.mark.parametrize("name, verb, bad_flag", [
    ("task_backlog", "status", "--bogus"),
    ("task_anchor", "status", "--bogus"),
    ("loop_progress", "status", "--bogus"),
])
def test_unknown_flag_fails_closed_and_names_accepted_flags(name, verb, bad_flag, tmp_path):
    r = _run(SCRIPTS[name], [verb, bad_flag, "x"], cwd=tmp_path)
    assert r.returncode != 0
    assert bad_flag in r.stderr
    describe = _run(SCRIPTS[name], ["--describe-cli"], cwd=tmp_path)
    flags = json.loads(describe.stdout)["flags"]
    for f in flags:
        assert f in r.stderr, "accepted-flags message should list %s" % f


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_describe_cli_flags_include_help(name):
    r = _run(SCRIPTS[name], ["--describe-cli"], cwd=REPO)
    assert r.returncode == 0
    flags = json.loads(r.stdout)["flags"]
    assert "--help" in flags
