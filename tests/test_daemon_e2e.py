"""The real console script through the real daemon, against the same command run in-process (issue #1590).

Every command of the battery runs twice, once with ``SIMPLICIO_LOOP_DAEMON=0`` and once through a daemon that
the first call starts by itself. The exit code, stdout and stderr must be the same, and the files they leave.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.daemon import client, protocol


def paths_of(directory, key):
    found = protocol.paths(directory, key)
    return type(found)(*(Path(p) for p in found))

pytestmark = [
    pytest.mark.skipif(not protocol.supported(), reason="needs AF_UNIX, fork and fd passing"),
    pytest.mark.skipif(not (shutil.which("simplicio-dev-cli") and shutil.which("simplicio-mapper") and shutil.which("git")),
                       reason="needs the operators and git on PATH"),
]

LAUNCH = "import sys; from simplicio_loop.daemon.client import main; sys.exit(main())"
VOLATILE = ("run_id", "wall_s", "execution_report", "receipts", "repo", "map")


@pytest.fixture(scope="module")
def daemon_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("d")
    directory.chmod(0o700)
    yield directory
    key = protocol.daemon_key()
    client.stop(run_dir=directory, key=key)


def cli(daemon_dir: Path, args: list[str], *, via_daemon: bool, cwd: Path, stdin: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "1" if via_daemon else "0", "SIMPLICIO_LOOP_DAEMON_DIR": str(daemon_dir),
           "SIMPLICIO_LOOP_DAEMON_IDLE_S": "120", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-c", LAUNCH, *args], cwd=cwd, env=env, input=stdin, text=True,
                          capture_output=True, timeout=300)


def make_repo(path: Path) -> Path:
    (path / "pkg").mkdir(parents=True)
    (path / "pkg" / "mod.py").write_text('def greet(name):\n    return "hello " + name\n', encoding="utf-8")
    for command in (["init", "-q"], ["config", "user.email", "t@t.t"], ["config", "user.name", "t"], ["add", "-A"],
                    ["commit", "-qm", "init"]):
        subprocess.run(["git", *command], cwd=path, check=True, capture_output=True)
    return path


def normal(text: str) -> object:
    """JSON stdout without the fields that differ by run (ids, durations, paths)."""
    text = re.sub(r"turbo-\d{8}T\d{6}-[0-9a-f]{6}", "<run>", text)
    try:
        document = json.loads(text)
    except ValueError:
        return text
    return {k: v for k, v in document.items() if k not in VOLATILE}


PLAN = json.dumps({"operations": [{"path": "pkg/mod.py", "find": '"hello "', "replace": '"hi "'}]})
BATTERY = [
    ("version", ["--version"], None),
    ("no tasks", ["turbo", "--repo", "."], None),
    ("missing repo", ["turbo", "--repo", "/nonexistent-repo-for-the-daemon-test", "--task", "x"], None),
    ("a first word that is no command is a task", ["frobnicate"], None),
    ("unknown option", ["turbo", "--bogus"], None),
    ("apply ok", ["turbo", "--repo", ".", "--apply", "-", "--verify", "true"], PLAN),
    ("apply verify fails", ["turbo", "--repo", ".", "--apply", "-", "--verify", "false"], PLAN),
    ("apply find misses", ["turbo", "--repo", ".", "--apply", "-"],
     json.dumps({"operations": [{"path": "pkg/mod.py", "find": "NOT THERE", "replace": "x"}]})),
    ("apply malformed", ["turbo", "--repo", ".", "--apply", "-"], "this is not json"),
    ("apply into .git is refused", ["turbo", "--repo", ".", "--apply", "-"],
     json.dumps({"operations": [{"path": ".git/hooks/pre-commit", "find": "", "replace": "#!/bin/sh\nexit 0\n"}]})),
]


@pytest.mark.parametrize("name,args,stdin", BATTERY, ids=[b[0] for b in BATTERY])
def test_the_daemon_gives_the_same_answer_as_running_in_process(daemon_dir, tmp_path, name, args, stdin):
    plain, warm = make_repo(tmp_path / "plain"), make_repo(tmp_path / "warm")
    expected = cli(daemon_dir, args, via_daemon=False, cwd=plain, stdin=stdin or "")
    got = cli(daemon_dir, args, via_daemon=True, cwd=warm, stdin=stdin or "")
    assert got.returncode == expected.returncode, (got.stderr, expected.stderr)
    assert normal(got.stdout.replace(str(warm), "<repo>")) == normal(expected.stdout.replace(str(plain), "<repo>"))
    assert got.stderr.replace(str(warm), "<repo>") == expected.stderr.replace(str(plain), "<repo>")
    for relative in ("pkg/mod.py", ".git/hooks/pre-commit"):
        a, b = plain / relative, warm / relative
        assert a.exists() == b.exists() and (not a.exists() or a.read_text() == b.read_text())


def test_the_orient_step_runs_the_mapper_through_the_daemon_too(daemon_dir, tmp_path):
    repo = make_repo(tmp_path / "repo")
    args = ["turbo", "--repo", ".", "--task", "In pkg/mod.py replace hello with hi"]
    expected = cli(daemon_dir, args, via_daemon=False, cwd=make_repo(tmp_path / "plain"))
    got = cli(daemon_dir, args, via_daemon=True, cwd=repo)
    assert got.returncode == expected.returncode == 0, got.stderr
    first, second = json.loads(got.stdout), json.loads(expected.stdout)
    assert first["status"] == second["status"] == "needs_plan"
    assert first["tasks"] == second["tasks"] and list(first["files"]) == list(second["files"]) == ["pkg/mod.py"]
    log = paths_of(daemon_dir, protocol.daemon_key()).log.read_text()
    assert "simplicio-mapper" in log, "the Mapper was not started through the daemon"


def test_the_apply_step_runs_dev_cli_through_the_daemon(daemon_dir, tmp_path):
    repo = make_repo(tmp_path / "repo")
    done = cli(daemon_dir, ["turbo", "--repo", ".", "--apply", "-"], via_daemon=True, cwd=repo, stdin=PLAN)
    assert done.returncode == 0 and '"hi "' in (repo / "pkg" / "mod.py").read_text()
    assert "simplicio-dev-cli" in paths_of(daemon_dir, protocol.daemon_key()).log.read_text()


def test_status_and_stop_through_the_console_script(daemon_dir, tmp_path):
    cli(daemon_dir, ["--version"], via_daemon=True, cwd=tmp_path)
    running = cli(daemon_dir, ["daemon", "status"], via_daemon=True, cwd=tmp_path)
    assert running.returncode == 0 and json.loads(running.stdout)["protocol"] == protocol.PROTOCOL
    assert cli(daemon_dir, ["daemon", "stop"], via_daemon=True, cwd=tmp_path).stdout.strip() == "stopped"
    gone = cli(daemon_dir, ["daemon", "status"], via_daemon=True, cwd=tmp_path)
    assert gone.returncode == 3 and json.loads(gone.stdout) == {"running": False}
