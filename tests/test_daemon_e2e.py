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


def cli(daemon_dir: Path, args: list[str], *, via_daemon: bool, cwd: Path, stdin: str = "",
        extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "1" if via_daemon else "0", "SIMPLICIO_LOOP_DAEMON_DIR": str(daemon_dir),
           "SIMPLICIO_LOOP_DAEMON_IDLE_S": "120", "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
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
    ("preflight strict", ["preflight", "--strict", "--json"], None),
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


FAMILIES = [
    ("auth status", ["auth", "status", "--json"]),
    ("logout with nothing to delete", ["logout", "--yes", "--json"]),
    ("login usage", ["login", "--help"]),
    ("update usage", ["update", "--help"]),
    ("install dry run", ["install", "--dry-run", "--json", "--target", "."]),
    ("doctor login", ["doctor", "login"]),
    ("setup check", ["setup", "--check", "--json"]),
]


def hostless_path(directory: Path) -> str:
    """A PATH with the tools the commands need and none of the host CLIs (claude, codex, ...) that `setup` probes.

    `setup --check` runs each host it finds with a time limit. Under load one probe timed out in one of the two runs
    and not in the other, and the answers differed (version and login of that host): the test compared the speed of
    the machine, not the daemon. Without hosts on PATH both runs see the same thing."""
    directory.mkdir(exist_ok=True)
    for tool in ("git", "python3", "python", "simplicio-loop", "simplicio-dev-cli", "simplicio-mapper"):
        found = shutil.which(tool)
        if found and not (directory / tool).exists():
            (directory / tool).symlink_to(found)
    return str(directory)


@pytest.mark.parametrize("name,args", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_the_command_families_of_the_binary_release_behave_the_same_through_the_daemon(daemon_dir, tmp_path, name, args):
    """login, logout, auth, update, install, doctor and setup read HOME and write files there; the HOME of the
    daemon is the real one, so a command that took it instead of the HOME of its caller would differ."""
    results = []
    for label, via_daemon in (("plain", False), ("warm", True)):
        home = tmp_path / f"home_{label}"
        home.mkdir()
        repo = make_repo(tmp_path / f"repo_{label}")
        done = cli(daemon_dir, args, via_daemon=via_daemon, cwd=repo,
                   extra_env={"HOME": str(home), "PATH": hostless_path(tmp_path / "bin")})
        text = lambda value: value.replace(str(home), "<home>").replace(str(repo), "<repo>")  # noqa: E731
        # the host programs that `setup` probes write their own logs in HOME; only what the loop wrote counts
        written = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file() and "simplicio" in str(p))
        results.append((done.returncode, text(done.stdout), text(done.stderr), written))
    assert results[0] == results[1]


def test_strict_mode_armed_by_one_command_does_not_stay_armed_for_the_next(daemon_dir, tmp_path):
    """`preflight --strict` sets SIMPLICIO_LOOP_STRICT in its own process; in the daemon that must die with the child."""
    plain, warm = make_repo(tmp_path / "plain"), make_repo(tmp_path / "warm")
    armed = cli(daemon_dir, ["preflight", "--strict", "--json"], via_daemon=True, cwd=warm)
    assert json.loads(armed.stdout)["strict"] is True
    later = cli(daemon_dir, ["preflight", "--json"], via_daemon=True, cwd=warm)
    expected = cli(daemon_dir, ["preflight", "--json"], via_daemon=False, cwd=plain)
    assert json.loads(later.stdout)["strict"] is json.loads(expected.stdout)["strict"]
    assert normal(later.stdout.replace(str(warm), "<repo>")) == normal(expected.stdout.replace(str(plain), "<repo>"))


def own_environment_first() -> dict[str, str]:
    """PATH with the scripts directory of this Python first: the daemon forks only the Mapper that is the console
    script of the loop's own environment (docs/DAEMON.md, "Operator shortcut"), never one found elsewhere on PATH
    (an old /usr/local/bin/simplicio-mapper ahead of the venv made this test depend on who ran it)."""
    scripts = os.path.dirname(sys.executable)
    if not (Path(scripts) / "simplicio-mapper").exists():
        pytest.skip(f"UNVERIFIED|mapper_old: no simplicio-mapper console script next to {sys.executable}; "
                    "the daemon forks only the mapper of the loop's own environment")
    return {"PATH": scripts + os.pathsep + os.environ.get("PATH", "")}


def test_own_environment_first_uses_the_script_next_to_the_interpreter_or_skips(tmp_path, monkeypatch):
    fake_python = tmp_path / "bin" / "python"
    fake_python.parent.mkdir()
    monkeypatch.setattr(sys, "executable", str(fake_python))
    with pytest.raises(pytest.skip.Exception, match=r"UNVERIFIED\|mapper_old"):
        own_environment_first()
    (fake_python.parent / "simplicio-mapper").write_text("#!/bin/sh\n")
    assert own_environment_first()["PATH"].startswith(str(fake_python.parent) + os.pathsep)


def test_the_orient_step_runs_the_mapper_through_the_daemon_too(daemon_dir, tmp_path):
    repo = make_repo(tmp_path / "repo")
    args = ["turbo", "--repo", ".", "--task", "In pkg/mod.py replace hello with hi"]
    environment = own_environment_first()
    expected = cli(daemon_dir, args, via_daemon=False, cwd=make_repo(tmp_path / "plain"), extra_env=environment)
    got = cli(daemon_dir, args, via_daemon=True, cwd=repo, extra_env=environment)
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
