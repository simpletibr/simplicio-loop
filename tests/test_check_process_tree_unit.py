"""Real child-process contracts for the hermetic core gate."""
from __future__ import annotations

from io import StringIO
import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux process-tree containment contract"
)

from scripts import check, check_runtime
from scripts.check_runtime import CommandReason, _visible_namespace_pid


def _assert_pid_gone(pid: int) -> None:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        running = check_runtime._pid_is_running(pid)
        if running is False:
            return
        time.sleep(0.02)
    raise AssertionError("timed-out process %d was not reaped" % pid)


def _long_interpreter(tmp_path, length: int = 150) -> str:
    """A symlink to this interpreter whose path is at least ``length`` characters.

    A venv path of about 100 characters plus a long TMPDIR gives the same shape in a
    release-gate run.  The link keeps the base interpreter working (``-c`` code only).
    """
    directory = tmp_path / ("v" * 60) / ("e" * 60) / "bin"
    directory.mkdir(parents=True)
    link = directory / "python"
    link.symlink_to(os.path.realpath(sys.executable))
    assert len(str(link)) >= length
    return str(link)


# Time a phase gets for its Python leader (and a forked child) to start and write
# its pid file before the timeout under test fires.  A loaded host starts an
# interpreter in seconds, not milliseconds; with a sub-second budget these tests
# measured interpreter start-up speed instead of process-tree reaping.
START_BUDGET_SECONDS = 4.0

# Leader that starts a detached (setsid) child and exits only after the child has
# written its pid file, so the assertions never depend on how fast an interpreter
# starts.  argv: pid file, child code, child interpreter.
DETACHED_CHILD_LEADER = """import pathlib, subprocess, sys, time
subprocess.Popen([sys.argv[3], '-c', sys.argv[2], sys.argv[1]], start_new_session=True,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not pathlib.Path(sys.argv[1]).exists():
    time.sleep(.01)
time.sleep(.15)
"""

def test_descendant_scanner_uses_callers_namespace_level() -> None:
    assert _visible_namespace_pid(42000, [42000, 37, 1], 1) == 37
    assert _visible_namespace_pid(42000, [42000], 1) is None
    assert _visible_namespace_pid(42000, None, 1) is None


def test_descendant_scanner_fails_closed_for_unmapped_relevant_child(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_caller_namespace_depth", lambda: 0)
    monkeypatch.setattr(check_runtime.os, "listdir", lambda _path: ["100", "101"])
    monkeypatch.setattr(
        check_runtime,
        "_nspid_values",
        lambda path: [100] if path.endswith("/100/status") else None,
    )

    def fake_open(path, *_args, **_kwargs):
        parent = "0" if "/100/" in path else "100"
        return StringIO("1 (worker) S %s 0 0 0\n" % parent)

    monkeypatch.setattr("builtins.open", fake_open)
    result = check_runtime._posix_descendants(100)
    assert isinstance(result, check_runtime._DescendantDiscoveryError)
    assert result.descendants == set()


def test_descendant_scanner_fails_closed_for_live_unmapped_root(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_caller_namespace_depth", lambda: 0)
    monkeypatch.setattr(check_runtime.os, "listdir", lambda _path: ["100"])
    monkeypatch.setattr(check_runtime, "_nspid_values", lambda _path: None)
    monkeypatch.setattr(check_runtime.os, "kill", lambda _pid, _signal: None)
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: StringIO("1 (worker) S 0 0\n"))
    result = check_runtime._posix_descendants(100)
    assert isinstance(result, check_runtime._DescendantDiscoveryError)
    assert result.descendants == set()


@pytest.mark.skipif(os.name == "nt", reason="Linux NSpid descendant-discovery contract")
def test_descendant_scanner_retains_safe_sibling_before_unmapped_child(monkeypatch) -> None:
    monkeypatch.setattr(check_runtime, "_caller_namespace_depth", lambda: 0)
    monkeypatch.setattr(check_runtime.os, "listdir", lambda _path: ["100", "101", "102"])

    def nspid(path):
        if path.endswith("/100/status"):
            return [100]
        if path.endswith("/101/status"):
            return [101]
        return None

    def fake_open(path, *_args, **_kwargs):
        parent = "0" if "/100/" in path else "100"
        return StringIO("1 (worker) S %s 0 0 0\n" % parent)

    monkeypatch.setattr(check_runtime, "_nspid_values", nspid)
    monkeypatch.setattr("builtins.open", fake_open)
    result = check_runtime._posix_descendants(100)
    assert isinstance(result, check_runtime._DescendantDiscoveryError)
    assert result.descendants == {101}


def test_core_network_guard_reaches_python_subprocess() -> None:
    program = (
        "import errno,socket; "
        "\ntry:\n socket.create_connection(('198.51.100.7', 9))\n"
        "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH\n"
        "else:\n raise AssertionError('INET connection was not blocked')\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[raw_socket]: Windows runner")
def test_core_network_guard_blocks_raw_socket_and_public_bind() -> None:
    program = (
        "import _socket, errno; "
        "raw = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM); "
        "\ntry:\n raw.connect(('198.51.100.7', 9))\n"
        "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH\n"
        "else:\n raise AssertionError('raw INET connection was not blocked')\n"
        "\ntry:\n raw.bind(('0.0.0.0', 0))\n"
        "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH\n"
        "else:\n raise AssertionError('wildcard bind was not blocked')\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[raw_socket]: Windows runner")
def test_core_network_guard_covers_socket_type_aliases_raw_dns_and_sendmsg() -> None:
    program = (
        "import _socket,errno,socket; "
        "factories=(_socket.socket,_socket.SocketType,socket.SocketType); "
        "\nfor factory in factories:\n"
        " raw=factory(_socket.AF_INET,_socket.SOCK_DGRAM)\n"
        " try:\n  raw.sendmsg([b'x'],(),0,('198.51.100.7',9))\n"
        " except OSError as exc:\n  assert exc.errno == errno.ENETUNREACH\n"
        " else:\n  raise AssertionError('SocketType sendmsg bypass was not blocked')\n"
        " raw.close()\n"
        "\ntry:\n _socket.getaddrinfo('example.invalid',443)\n"
        "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH\n"
        "else:\n raise AssertionError('_socket.getaddrinfo bypass was not blocked')\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[raw_socket]: Windows runner")
def test_core_network_guard_covers_public_mros_and_keeps_popen_contract() -> None:
    program = (
        "import _socket,errno,inspect,subprocess,socket; "
        "assert isinstance(subprocess.Popen,type); "
        "assert issubclass(subprocess.Popen, subprocess.Popen.__mro__[1]); "
        "assert 'bufsize' in str(inspect.signature(subprocess.Popen)); "
        "assert socket.SocketType is _socket.SocketType; "
        "assert hasattr(socket.SocketType,'connect'); "
        "factories=(_socket.socket,_socket.SocketType,socket.socket,socket.SocketType,"
        "socket.socket.__mro__[1]); "
        "\nfor factory in factories:\n"
        " raw=factory(_socket.AF_INET,_socket.SOCK_STREAM)\n"
        " assert isinstance(raw,socket.SocketType)\n"
        " try:\n  raw.bind(('0.0.0.0',0))\n"
        " except OSError as exc:\n  assert exc.errno == errno.ENETUNREACH\n"
        " else:\n  raise AssertionError('public MRO route allowed INET bind')\n"
        " raw.close()\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


def test_core_network_guard_rejects_python_no_site_child_bypass() -> None:
    program = (
        "import errno, os, subprocess, sys; "
        "commands = ["
        "lambda: subprocess.Popen([sys.executable, '-S', '-c', 'pass']), "
        "lambda: os.spawnv(os.P_WAIT, sys.executable, [sys.executable, '-I', '-c', 'pass'])"
        "]; "
        "\nfor command in commands:\n"
        " try:\n  command()\n"
        " except OSError as exc:\n  assert exc.errno == errno.EPERM\n"
        " else:\n  raise AssertionError('Python -S/-I bypass was launched')\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


def test_core_network_guard_parses_split_python_option_arguments() -> None:
    program = (
        "import errno,subprocess,sys; "
        "blocked=["
        "[sys.executable,'-X','dev','-S','-c','pass'],"
        "[sys.executable,'-W','ignore','-S','-c','pass']]; "
        "\nfor argv in blocked:\n"
        " try:\n  subprocess.Popen(argv)\n"
        " except OSError as exc:\n  assert exc.errno == errno.EPERM\n"
        " else:\n  raise AssertionError('split option bypass launched')\n"
        "normal=["
        "[sys.executable,'-X','dev','-c','pass'],"
        "[sys.executable,'-W','ignore','-c','pass'],"
        "[sys.executable,'-Xdev','-c','pass'],"
        "[sys.executable,'-Wignore','-c','pass']]; "
        "\nfor argv in normal:\n assert subprocess.run(argv).returncode == 0\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[symlink]: Windows privilege")
def test_core_network_guard_rejects_all_python_child_delivery_bypasses(tmp_path) -> None:
    alias = tmp_path / "not-python-name"
    alias.symlink_to(sys.executable)
    program = (
        "import errno,os,subprocess,sys; "
        "commands=["
        "lambda: subprocess.Popen([sys.executable,'-IS','-c','pass']),"
        "lambda: subprocess.Popen(['different-argv0','-E','-c','pass'],executable=sys.executable),"
        "lambda: subprocess.Popen(sys.executable+' -S -c pass',shell=True),"
        "lambda: os.execve(sys.executable,['different-argv0','-S','-c','pass'],{'PATH':os.environ['PATH']}),"
        "lambda: subprocess.Popen([sys.argv[1],'-S','-c','pass'])"
        "]; "
        "\nfor command in commands:\n"
        " try:\n  command()\n"
        " except OSError as exc:\n  assert exc.errno == errno.EPERM\n"
        " else:\n  raise AssertionError('Python child bypass was launched')\n"
        "assert subprocess.run(['/bin/sh','-c','exit 0'],cwd='/tmp').returncode == 0\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program, str(alias)], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="CAPABILITY_UNAVAILABLE[windows_sockets]: Windows runner")
def test_core_network_guard_injects_delivery_for_minimal_python_child_envs() -> None:
    child = (
        "import errno,socket; "
        "\ntry:\n socket.create_connection(('198.51.100.7',9))\n"
        "except OSError as exc:\n assert exc.errno == errno.ENETUNREACH\n"
        "else:\n raise AssertionError('child network was not blocked')"
    )
    program = (
        "import asyncio,os,subprocess,sys; "
        "env={'PATH':os.environ['PATH']}; "
        "commands=["
        "lambda: subprocess.run([sys.executable,'-c',sys.argv[1]],env=env,check=True).returncode,"
        "lambda: subprocess.Popen([sys.executable,'-c',sys.argv[1]],-1,None,None,None,None,None,True,False,None,env).wait(),"
        "lambda: os.spawnve(os.P_WAIT,sys.executable,[sys.executable,'-c',sys.argv[1]],env)"
        "]; "
        "\nfor command in commands:\n assert command() == 0\n"
        "\nif hasattr(os,'posix_spawn'):\n"
        " pid=os.posix_spawn(sys.executable,[sys.executable,'-c',sys.argv[1]],env)\n"
        " assert os.waitpid(pid,0)[1] == 0\n"
        "\nasync def run_async():\n"
        " process=await asyncio.create_subprocess_exec(sys.executable,'-c',sys.argv[1],env=env)\n"
        " assert await process.wait() == 0\n"
        "\nasyncio.run(run_async())\n"
        "print('blocked')"
    )
    result = check._run_bounded(
        [sys.executable, "-c", program, child], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "blocked"


def test_core_network_guard_reaches_python_multiprocessing_spawn(tmp_path) -> None:
    script = tmp_path / "spawn_attempt.py"
    script.write_text("""
import errno
import multiprocessing
import socket

def attempt(queue):
    try:
        socket.create_connection(('198.51.100.7', 9))
    except OSError as exc:
        queue.put(exc.errno)
    else:
        queue.put(None)

if __name__ == '__main__':
    context = multiprocessing.get_context('spawn')
    queue = context.Queue()
    child = context.Process(target=attempt, args=(queue,))
    child.start()
    child.join(60)
    assert child.exitcode == 0
    assert queue.get(timeout=30) == errno.ENETUNREACH
    print('blocked')
""")
    result = check._run_bounded(
        [sys.executable, str(script)], phase="stdlib_test", capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "SIMPLICIO_CORE_NO_NETWORK": "1"},
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "blocked"


@pytest.mark.skipif(os.name == "nt", reason="POSIX setsid process-tree contract")
def test_successful_leader_with_closed_pipes_and_setsid_child_fails_and_reaps(tmp_path) -> None:
    child_pid = tmp_path / "closed-pipes-child.pid"
    child = (
        "import pathlib,sys,time,os; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = DETACHED_CHILD_LEADER
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(child_pid), child, sys.executable],
        phase="stdlib_test",
        capture_output=True, timeout_seconds=30.0,
    )

    assert result.returncode != 0
    assert result.timed_out is False
    assert result.reason == CommandReason.DESCENDANT_LEAK
    assert check._gate_result("stdlib_test", result).reason_code == "stdlib_test_descendant_leak"
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(os.name == "nt", reason="Linux subreaper process-tree contract")
def test_noncapturing_timeout_rescans_and_reaps_double_fork(tmp_path) -> None:
    child_pid = tmp_path / "noncapture-double-fork.pid"
    program = """import os, pathlib, sys, time
pid = os.fork()
if not pid:
    os.setsid()
    grandchild = os.fork()
    if grandchild:
        os._exit(0)
    pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
    time.sleep(30)
time.sleep(30)
"""
    result = check._run_bounded(
        [sys.executable, "-c", program, str(child_pid)], phase="stdlib_test",
        timeout_seconds=START_BUDGET_SECONDS,
    )

    assert result.timed_out is True
    assert child_pid.exists()
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(os.name == "nt", reason="POSIX setsid process-tree contract")
def test_timeout_rescans_sigterm_handler_setsids_grandchild(tmp_path) -> None:
    child_pid = tmp_path / "late-sigterm-grandchild.pid"
    program = """import os, pathlib, signal, sys, time
def on_term(_sig, _frame):
    child = os.fork()
    if not child:
        os.setsid()
        pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
        time.sleep(30)
    os._exit(0)
signal.signal(signal.SIGTERM, on_term)
time.sleep(30)
"""
    result = check._run_bounded(
        [sys.executable, "-c", program, str(child_pid)], phase="stdlib_test",
        timeout_seconds=START_BUDGET_SECONDS,
    )
    assert result.timed_out is True
    assert child_pid.exists()
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(os.name == "nt", reason="POSIX setsid process-tree contract")
def test_descendant_exiting_within_grace_period_is_not_a_leak(tmp_path) -> None:
    """A descendant still alive right after the leader exits, but that goes
    away on its own shortly after (the ``multiprocessing.resource_tracker``
    shutdown shape: it only exits once it observes its parent's pipe close),
    must not be reported as a leak -- ``run_bounded`` gives it a bounded
    grace period before declaring one."""
    child_pid = tmp_path / "self-exiting-child.pid"
    child = (
        "import pathlib,sys,time,os; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(0.5)"
    )
    leader = DETACHED_CHILD_LEADER
    result = check._run_bounded(
        [sys.executable, "-c", leader, str(child_pid), child, sys.executable],
        phase="stdlib_test",
        capture_output=True, timeout_seconds=30.0,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.reason == CommandReason.OK
    assert check._gate_result("stdlib_test", result).ok is True
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(os.name == "nt", reason="POSIX setsid process-tree contract")
@pytest.mark.parametrize("long_interpreter", [False, True], ids=["short-path", "path-150-chars"])
def test_descendant_still_alive_past_grace_period_is_reported_as_leak(
    tmp_path, long_interpreter
) -> None:
    """A descendant that is genuinely still running once the whole bounded
    grace window has elapsed is a real leak, not just a slow shutdown --
    ``run_bounded`` must wait out the full grace period (proving it is not
    short-circuited back to the old near-instant check) before reporting it,
    and must still terminate and reap it afterwards.  The diagnostic must name
    the leaked process even when the interpreter path is very long (a venv path
    plus the gate TMPDIR), so the command line is clipped without losing its tail."""
    interpreter = _long_interpreter(tmp_path) if long_interpreter else sys.executable
    child_pid = tmp_path / "truly-leaked-child.pid"
    child = (
        "import pathlib,sys,time,os; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    leader = DETACHED_CHILD_LEADER
    started = time.monotonic()
    result = check._run_bounded(
        [interpreter, "-c", leader, str(child_pid), child, interpreter],
        phase="stdlib_test", capture_output=True, timeout_seconds=10.0,
    )
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert result.timed_out is False
    assert result.reason == CommandReason.DESCENDANT_LEAK
    assert check._gate_result("stdlib_test", result).reason_code == "stdlib_test_descendant_leak"
    # The leaked process is named in stderr so a gate failure is diagnosable.
    leaked = int(child_pid.read_text())
    assert "descendant_leak pid=%d" % leaked in result.stderr
    assert "truly-leaked-child.pid" in result.stderr
    # The grace period (>= 1.5s, comfortably below the 2.0s budget) must
    # actually have been honored, not skipped.
    assert elapsed >= 1.5
    _assert_pid_gone(int(child_pid.read_text()))


@pytest.mark.skipif(os.name == "nt", reason="POSIX /proc command-line contract")
def test_leak_diagnostic_clips_a_long_command_line_but_keeps_both_ends(tmp_path) -> None:
    """``descendant_leak`` lines stay bounded, and the clipped text keeps the
    interpreter (start) and the last arguments (end), where the name that
    identifies the leaked process usually is."""
    interpreter = _long_interpreter(tmp_path)
    tail = str(tmp_path / "unique-tail-marker.pid")
    proc = subprocess.Popen(
        [interpreter, "-c", "import time; time.sleep(30)  # " + "x" * 200, tail],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            with open("/proc/%d/cmdline" % proc.pid, "rb") as handle:
                if tail.encode() in handle.read():  # exec has happened
                    break
            time.sleep(0.02)
        line = check_runtime._describe_leaked({proc.pid})
    finally:
        proc.kill()
        proc.wait()

    assert line.startswith("descendant_leak pid=%d cmd=" % proc.pid)
    assert line.endswith("\n") and line.count("\n") == 1
    command = line.split("cmd=", 1)[1].rstrip("\n")
    assert len(command) <= check_runtime.LEAK_COMMAND_LIMIT
    head, _, end = command.partition(" ... ")
    assert interpreter[:20] in head, command  # the start of the interpreter path survives
    assert end.endswith("unique-tail-marker.pid"), command  # and so does the last argument


def test_leak_diagnostic_keeps_a_short_command_line_whole() -> None:
    assert check_runtime._clip_command("python -c pass /x/y.pid") == "python -c pass /x/y.pid"
    exact = "a" * check_runtime.LEAK_COMMAND_LIMIT
    assert check_runtime._clip_command(exact) == exact
    clipped = check_runtime._clip_command(exact + "b")
    assert len(clipped) == check_runtime.LEAK_COMMAND_LIMIT
    assert clipped.endswith("b")


def test_package_gate_step_reports_descendant_leak_reason(tmp_path) -> None:
    """A package-gate step whose tool exits 0 but leaves a descendant running
    must fail with a typed ``_descendant_leak`` reason, not a generic
    ``_failed`` that hides why a fully green test run was rejected."""
    child = "import time; time.sleep(30)"
    leader = (
        "import subprocess,sys,time; "
        "sys.argv[1:2] == ['--version'] and sys.exit(0); "
        "subprocess.Popen([sys.executable, '-c', %r], start_new_session=True, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(.15)" % child
    )
    fail = check._run_step(
        [sys.executable, "-c", leader], [], phase="package_gate_tests", cwd=str(tmp_path),
        missing_reason="pkg_missing", fail_reason="pkg_pytest_failed",
    )
    assert fail is not None
    assert fail.reason_code == "pkg_pytest_failed_descendant_leak"
