"""The per-repo config lives in `.simplicio-loop/loop.toml` and nowhere else (the Runtime owns `.simplicio/`).

No fallback, no migration: a repo that only has the old file is not opted in, and the log says the exact new path.
A plan cannot change the config through the PR: `.simplicio-loop/` is loop state, never staged.
"""
from __future__ import annotations

import asyncio
import base64
import subprocess

import pytest

from simplicio_loop import intake_gate
from simplicio_loop.watcher247 import config, events, tick

from .fakes import FakeRun, baseline, issue, read_json, run_tick

NEW = ".simplicio-loop/loop.toml"
OLD = ".simplicio/loop.toml"


class _Gh:
    """intake_gate's gh runner: answers only the paths in `files`, records every path asked."""

    def __init__(self, files):
        self.files, self.asked = files, []

    async def __call__(self, *args):
        route = args[1]
        self.asked.append(route)
        for path, text in self.files.items():
            if route.endswith("/contents/" + path):
                return 0, base64.b64encode(text.encode()), b""
        return 1, b"", b"gh: Not Found (HTTP 404)"


def test_the_gate_reads_the_new_path_only():
    gh = _Gh({NEW: "enabled = true\n"})
    assert asyncio.run(intake_gate.repo_opted_in("org/repo", run=gh)) is True
    assert gh.asked == [f"repos/org/repo/contents/{NEW}"]
    assert intake_gate.CONFIG_PATH == NEW


def test_a_repo_with_only_the_old_file_is_not_opted_in_and_the_old_path_is_never_asked():
    gh = _Gh({OLD: "enabled = true\n"})
    assert asyncio.run(intake_gate.repo_opted_in("org/repo", run=gh)) is False
    assert gh.asked == [f"repos/org/repo/contents/{NEW}"]


def test_errors_name_the_new_path():
    gh = _Gh({NEW: "enabled = [\n"})
    with pytest.raises(intake_gate.IntakeGateError) as bad:
        asyncio.run(intake_gate.repo_config("org/repo", run=gh))
    assert NEW in str(bad.value) and OLD not in str(bad.value) and bad.value.reason_code == "invalid_toml"

    async def slow(*_args):
        await asyncio.sleep(1)

    old_timeout = intake_gate.REPO_OPTED_IN_TIMEOUT
    intake_gate.REPO_OPTED_IN_TIMEOUT = 0.01
    try:
        with pytest.raises(intake_gate.IntakeGateError) as slow_error:
            asyncio.run(intake_gate.repo_config("org/repo", run=slow))
    finally:
        intake_gate.REPO_OPTED_IN_TIMEOUT = old_timeout
    assert NEW in str(slow_error.value) and OLD not in str(slow_error.value)


def test_the_tick_skips_a_repo_without_the_new_file_and_says_where_to_put_it(env, capsys):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}, opted_in=[]))
    baseline()
    run_tick()
    assert read_json(config.STATUS)["skipped_repos"] == {"simplicio-a": "not_opted_in"}
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "not opted in simplicio-a" in line)
    assert NEW in line and "enabled = true" in line and OLD not in line
    assert fake.turbo_argv == []
    asked = [argv[argv.index("api") + 1:] for argv in fake.ran("gh", "api")]
    assert all(OLD not in " ".join(argv) for argv in asked)


def _repo_with_tracked_config(tmp_path):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp_path, check=True,
                       capture_output=True)

    git("init", "-q")
    (tmp_path / ".gitignore").write_text(".simplicio-loop/*\n!.simplicio-loop/loop.toml\n")
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "loop.toml").write_text("enabled = true\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "seed")
    return git


def test_a_plan_cannot_change_the_config_through_the_pr(tmp_path):
    git = _repo_with_tracked_config(tmp_path)
    (tmp_path / ".simplicio-loop" / "loop.toml").write_text('enabled = true\nverify = "true"\nallowed_authors = ["x"]\n')
    assert asyncio.run(tick.dirty(tmp_path)) is False  # only loop state changed: no diff, no PR
    (tmp_path / "a.py").write_text("x = 2\n")
    assert asyncio.run(tick.dirty(tmp_path)) is True
    git("add", "-A")
    git("reset", "-q", "--", ".simplicio-loop")  # what commit_and_pr does before it commits
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True)
    assert staged.stdout.split() == ["a.py"]


def test_the_loop_state_dir_stays_writable_next_to_the_tracked_config(tmp_path):
    _repo_with_tracked_config(tmp_path)
    run_id = events.open_run(tmp_path, "simplicio-a", 1)
    assert run_id and (tmp_path / ".simplicio-loop" / "orchestrator" / "runs" / run_id).is_dir()
