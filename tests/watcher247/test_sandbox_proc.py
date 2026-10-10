"""Live check (real bwrap) of the /proc channel: a sandboxed child must not see the watcher's pid (issue #1563).

The service secrets (GH_TOKEN, OPENROUTER_API_KEY ... from the EnvironmentFile) sit in the watcher's own
environment, readable at /proc/<watcher pid>/environ by anything running as the same uid. scrubbed_env only cleans
the CHILD's env. The sandbox must therefore run in its own pid namespace, with /proc remounted for it.

The "watcher" here is a separate process started with a fake secret in ITS environment, because /proc/<pid>/environ
holds the initial environment of that process (setting os.environ in pytest would not show up there).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop import exec_planner
from simplicio_loop.watcher247 import proc, sandbox

from .sandbox_rig import bwrap_skip_reason

pytestmark = pytest.mark.skipif(bool(bwrap_skip_reason()), reason=bwrap_skip_reason() or "bwrap")


def _interpreter_under_tmp() -> bool:
    """True when this Python (or its venv) lives under /tmp, which `sandbox.wrap` hides behind a tmpfs."""
    candidates = (sys.executable, os.path.realpath(sys.executable), sys.prefix, os.path.realpath(sys.prefix))
    return any(Path(path).is_relative_to("/tmp") for path in candidates)


needs_visible_interpreter = pytest.mark.skipif(
    _interpreter_under_tmp(),
    reason="sandbox.wrap mounts a tmpfs on /tmp, which hides a Python interpreter or venv located under /tmp "
           "(test-environment limit, not a product bug; run the gate from a venv outside /tmp)")

# What the watcher does, minus the package: fill {pid} with its own pid, run argv with the scrubbed env, report.
WATCHER = """
import json, os, subprocess, sys
spec = json.load(sys.stdin)
pid = str(os.getpid())
argv = [part.replace("{pid}", pid) for part in spec["argv"]]
done = subprocess.run(argv, env=spec["env"], capture_output=True, text=True, timeout=60)
print(json.dumps({"pid": os.getpid(), "rc": done.returncode, "out": done.stdout, "err": done.stderr}))
"""

# Everything a compromised planner could try against the watcher (pid in $1).
PROBE = r"""
pid=$1
echo "own-environ: $(test -r /proc/self/environ && echo readable || echo MISSING)"
echo "own-pid: $$"
echo "pid-listed: $(ls /proc | grep -qx "$pid" && echo YES || echo no)"
echo "pid-dir: $(test -e /proc/$pid && echo YES || echo no)"
for name in environ cmdline maps status; do
  echo "read-$name: $(cat /proc/$pid/$name >/dev/null 2>&1 && echo YES || echo no)"
done
cat /proc/$pid/environ 2>/dev/null | tr '\0' '\n'
for f in /proc/[0-9]*/environ; do tr '\0' '\n' < "$f" 2>/dev/null; done
exit 0
"""


def run_as_watcher(tmp_path, wrapped_argv, secret):
    """Run argv from a fresh process whose environment holds `secret`; the child gets the scrubbed env."""
    watcher_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_SECRET": secret, "GH_TOKEN": secret}
    spec = {"argv": wrapped_argv, "env": sandbox.scrubbed_env(watcher_env, home=tmp_path)}
    done = subprocess.run([sys.executable, "-I", "-c", WATCHER], input=json.dumps(spec), env=watcher_env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture
def rig(tmp_path):
    clone, state = tmp_path / "clone", tmp_path / "state"
    clone.mkdir()
    state.mkdir()
    return clone, state


def probe_argv(rig, drop=()):
    clone, state = rig
    argv = sandbox.wrap(["sh", "-c", PROBE, "sh", "{pid}"], clone=clone, state_dir=state, platform="linux", environ={})
    return [part for part in argv if part not in drop]


def fields(report):
    pairs = (line.split(": ", 1) for line in report["out"].splitlines() if ": " in line)
    return {key: value for key, value in pairs if " " not in key}


def test_wrap_unshares_the_pid_namespace_and_remounts_proc():
    argv = sandbox.wrap(["true"], clone=Path("/c"), state_dir=Path("/s"), platform="linux", environ={},
                        which=lambda binary: f"/usr/bin/{binary}")
    assert "--unshare-pid" in argv
    proc_at = argv.index("--proc")
    assert argv[proc_at + 1] == "/proc"  # a fresh procfs, mounted for the new pid namespace
    assert argv.index("--unshare-pid") < argv.index("--")


def test_control_without_unshare_pid_the_child_reads_the_watcher_environ(tmp_path, rig):
    """Proves the probe can see the channel: with the flag removed (what main did) the secret leaks."""
    secret = f"ghp_FAKE_{secrets.token_hex(8)}"
    report = run_as_watcher(tmp_path, probe_argv(rig, drop=("--unshare-pid",)), secret)
    assert report["rc"] == 0, report["err"]
    assert fields(report)["read-environ"] == "YES" and fields(report)["pid-dir"] == "YES"
    assert secret in report["out"], report["out"]


def test_sandboxed_child_cannot_read_the_watcher_environ(tmp_path, rig):
    secret = f"ghp_FAKE_{secrets.token_hex(8)}"
    report = run_as_watcher(tmp_path, probe_argv(rig), secret)
    assert report["rc"] == 0, report["err"]
    assert secret not in report["out"] + report["err"], "the watcher's environ is readable from inside the sandbox"
    assert "FAKE_SECRET" not in report["out"]
    assert fields(report)["read-environ"] == "no"


def test_sandboxed_child_cannot_list_or_read_the_watcher_pid(tmp_path, rig):
    report = run_as_watcher(tmp_path, probe_argv(rig), f"ghp_FAKE_{secrets.token_hex(8)}")
    seen = fields(report)
    assert seen["pid-listed"] == "no" and seen["pid-dir"] == "no"
    for name in ("environ", "cmdline", "maps", "status"):
        assert seen[f"read-{name}"] == "no", name


def test_the_new_proc_still_works_for_the_child_itself(tmp_path, rig):
    report = run_as_watcher(tmp_path, probe_argv(rig), f"ghp_FAKE_{secrets.token_hex(8)}")
    seen = fields(report)
    assert seen["own-environ"] == "readable"
    assert int(seen["own-pid"]) < 100  # a pid of the new namespace, not the host's


def test_the_child_environ_is_the_scrubbed_one(tmp_path, rig):
    clone, state = rig
    secret = f"ghp_FAKE_{secrets.token_hex(8)}"
    argv = sandbox.wrap(["sh", "-c", "tr '\\0' '\\n' < /proc/self/environ; tr '\\0' '\\n' < /proc/1/environ"],
                        clone=clone, state_dir=state, platform="linux", environ={})
    report = run_as_watcher(tmp_path, argv, secret)
    assert report["rc"] == 0, report["err"]
    assert "HOME=" in report["out"] and secret not in report["out"]  # pid 1 is bwrap, which got the scrubbed env too


# The existing flows must keep working inside the new namespace.

def sandboxed(argv, rig, **kwargs):
    clone, state = rig
    wrapped = sandbox.wrap(argv, clone=clone, state_dir=state, platform="linux", environ={})
    return asyncio.run(proc.run(wrapped, cwd=clone, env=sandbox.scrubbed_env(os.environ, home=Path.home()), **kwargs))


def test_stdin_reaches_the_sandboxed_command(rig):
    # `turbo --apply -` reads the plan from stdin; --new-session must not cut the pipe.
    done = sandboxed(["cat"], rig, stdin="the plan\n")
    assert (done.returncode, done.stdout) == (0, "the plan\n")


@needs_visible_interpreter
def test_git_and_python_work_in_the_clone(rig):
    clone, _ = rig
    script = ("git init -q . && git -c user.email=a@b -c user.name=n commit -q --allow-empty -m x "
              f"&& git log --oneline | wc -l && {sys.executable} -c 'print(6 * 7)'")
    done = sandboxed(["sh", "-c", script], rig)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["1", "42"]
    assert (clone / ".git").is_dir()


@needs_visible_interpreter
def test_pytest_runs_in_the_clone(rig):
    clone, _ = rig
    (clone / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    done = sandboxed([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_ok.py"], rig)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 passed" in done.stdout


def test_the_planner_stub_runs_through_exec_planner(rig, monkeypatch):
    clone, state = rig
    stub = state / "bin" / "opencode"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\necho \'{"operations": []}\'\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub.parent}:/usr/local/bin:/usr/bin:/bin")
    result = asyncio.run(exec_planner.run_planner(
        "opencode", "planning", "task", cwd=str(clone), repo_root=clone, config_dir=state / "opencode",
        wrap=lambda argv: sandbox.wrap(argv, clone=clone, state_dir=state, platform="linux", environ={})))
    assert result.reason_code == "ok", result


# The child is pid 2 (bwrap is pid 1) in its own namespace: a timeout must still take the whole tree down.

def marker():
    return f"{secrets.randbelow(10**9) + 10**9}.{secrets.randbelow(10**6)}"


def processes_with(needle: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if needle.encode() in (entry / "cmdline").read_bytes():
                    found.append(int(entry.name))
            except OSError:
                continue
    return found


def gone_within(needle: str, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not processes_with(needle):
            return True
        time.sleep(0.1)
    return not processes_with(needle)


def reap(needle: str) -> None:
    for pid in processes_with(needle):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def spawning_command(needle: str) -> list[str]:
    # a child, two grandchildren and a great-grandchild, all in the background
    return ["sh", "-c", f"sleep {needle} & sleep {needle} & sh -c 'sleep {needle} & wait' & echo up; wait"]


def test_proc_run_timeout_kills_the_whole_tree_inside_the_sandbox(rig):
    needle = marker()
    try:
        with pytest.raises(TimeoutError):
            sandboxed(spawning_command(needle), rig, timeout=2)
        assert gone_within(needle), f"survivors: {processes_with(needle)}"
    finally:
        reap(needle)


def test_planner_timeout_kills_the_whole_tree_inside_the_sandbox(rig):
    clone, state = rig
    needle = marker()
    wrapped = sandbox.wrap(spawning_command(needle), clone=clone, state_dir=state, platform="linux", environ={})
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(exec_planner._run_subprocess(wrapped, timeout_sec=2, cwd=str(clone), grace_sec=0.5,
                                                     env=sandbox.scrubbed_env(os.environ, home=Path.home())))
        assert gone_within(needle), f"survivors: {processes_with(needle)}"
    finally:
        reap(needle)


def test_killing_the_watcher_side_takes_the_sandbox_down_with_it(rig):
    """--die-with-parent: SIGKILL of the bwrap the watcher started must not leave the namespace running."""
    clone, state = rig
    needle = marker()
    wrapped = sandbox.wrap(spawning_command(needle), clone=clone, state_dir=state, platform="linux", environ={})
    child = subprocess.Popen(wrapped, stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        assert child.stdout.readline().strip() == "up"
        assert processes_with(needle)
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
        assert gone_within(needle), f"survivors: {processes_with(needle)}"
    finally:
        child.stdout.close()
        reap(needle)
