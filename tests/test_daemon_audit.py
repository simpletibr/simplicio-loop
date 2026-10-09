"""What the post-merge audit of the daemon found (issue #1590, audit of PR #1602): each finding has a test that
fails without its fix, and each hole the audit found in the suite has a test that kills the mutant.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pty
import resource
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from simplicio_loop import operator_exec
from simplicio_loop.daemon import client, protocol, runner

# The fixtures and helpers of the main daemon suite (pytest imports test files by path here, not by name).
_spec = importlib.util.spec_from_file_location("daemon_suite", Path(__file__).with_name("test_daemon.py"))
_suite = importlib.util.module_from_spec(_spec)
sys.modules["daemon_suite"] = _suite
_spec.loader.exec_module(_suite)
KEY, call, daemons, paths_of, run_dir, serve = (  # noqa: F401 - the fixtures are used by name
    _suite.KEY, _suite.call, _suite.daemons, _suite.paths_of, _suite.run_dir, _suite.serve)

pytestmark = pytest.mark.skipif(not protocol.supported(), reason="needs AF_UNIX, fork and fd passing")
LAUNCH = "import sys; from simplicio_loop.daemon.client import main; sys.exit(main())"
CALLER = ("import os, sys; from simplicio_loop.daemon import client; "
          "sys.exit(client.exec_program(sys.argv[1], sys.argv[2:], run_dir=os.environ['RUN_DIR'], key=os.environ['KEY'], "
          "autostart=False))")
PTY_CALLER = "import fcntl, os, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n" + CALLER


def gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except FileNotFoundError:
        return True
    return state in ("Z", "X")


def wait_until(check, seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.03)
    return check()


def hold(run_dir: Path, program: str, *args: str, env: dict | None = None):
    """Start a command and keep its connection: returns (socket, closer of the descriptors we made)."""
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    try:
        sock = client.open_exec(program, list(args), run_dir=run_dir, key=KEY, cwd=str(run_dir),
                                env=dict(os.environ) if env is None else env, stdio=(in_r, out_w, out_w), autostart=False)
    except BaseException:
        for fd in (in_r, in_w, out_r, out_w):
            os.close(fd)
        raise

    def close() -> None:
        for fd in (in_r, in_w, out_r, out_w):
            os.close(fd)
    return sock, close


def kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# ---- finding 1: a nested request that meets a replaced daemon must not crash the running command -----------


def _nested(monkeypatch, code: str):
    def refuse(*args, **options):
        raise protocol.DaemonError(code, "refused")

    monkeypatch.setattr(protocol, "CURRENT", protocol.Current("/nowhere", KEY))
    monkeypatch.setattr(operator_exec, "warm_name", lambda binary: "simplicio-mapper")
    monkeypatch.setattr(client, "run_captured", refuse)
    return asyncio.run(operator_exec.run([sys.executable, "-c", "print('plain process')"], timeout=30))


@pytest.mark.parametrize("code", ["stale", "not_running"])
def test_a_nested_request_that_meets_a_replaced_daemon_runs_as_a_plain_process(monkeypatch, code):
    assert _nested(monkeypatch, code) == (0, "plain process\n", "")


@pytest.mark.parametrize("code", ["busy", "socket_mode", "peer_uid", "lost"])
def test_a_nested_request_the_daemon_refused_for_another_reason_still_fails_loudly(monkeypatch, code):
    with pytest.raises(protocol.DaemonError) as caught:
        _nested(monkeypatch, code)
    assert caught.value.code == code


@pytest.mark.parametrize("code", ["stale", "not_running", "busy"])
def test_the_top_level_command_never_falls_back_it_exits_69_and_says_why(monkeypatch, capsys, code):
    def refuse(*args, **options):
        raise protocol.DaemonError(code, "refused by the test")

    monkeypatch.delenv(protocol.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(client, "open_exec", refuse)
    assert client.main(["--version"]) == protocol.EX_UNAVAILABLE
    err = capsys.readouterr().err
    assert f"[{code}]" in err and protocol.OPT_OUT_HINT in err


# ---- finding 2: bytes that are not UTF-8 in argv or the environment ------------------------------------------


def test_the_wire_format_carries_bytes_that_are_not_utf8():
    message = {"argv": ["a\udcffb"], "env": {"BAD": "v\udcff"}}
    assert json.loads(protocol.encode(message)) == message


def test_a_command_with_undecodable_argv_and_environment_runs_like_in_process(daemons, run_dir):
    serve(daemons, run_dir)
    done = call(run_dir, "state", "a\udcffb", env={**os.environ, "REQ_VAR": "v\udcff"})
    seen = json.loads(done.out)
    assert done.rc == 0 and seen["argv"][1] == "a\udcffb" and seen["var"] == "v\udcff"


def test_the_console_script_exits_0_with_undecodable_argv_and_environment(tmp_path):
    directory = tmp_path / "d"
    directory.mkdir(mode=0o700)
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON_DIR": str(directory), "SIMPLICIO_LOOP_DAEMON_IDLE_S": "60",
           "SIMPLICIO_LOOP_DAEMON": "1", "PYTHONDONTWRITEBYTECODE": "1", "BADENV": "v\udcff"}
    try:
        done = subprocess.run([sys.executable, "-c", LAUNCH, "--version", "a\udcffb"], env=env, capture_output=True,
                              timeout=120)
        plain = subprocess.run([sys.executable, "-c", LAUNCH, "--version", "a\udcffb"],
                               env={**env, "SIMPLICIO_LOOP_DAEMON": "0"}, capture_output=True, timeout=120)
    finally:
        client.stop(run_dir=directory, key=protocol.daemon_key())
    assert done.returncode == plain.returncode == 0, done.stderr
    assert done.stdout == plain.stdout


# ---- finding 3: Ctrl-C and hang-up reach the command as an interrupt, so finally and atexit run -------------


def _until_lines(path: Path, words: set[str], seconds: float = 20.0) -> set[str]:
    def seen() -> set[str]:
        return set(path.read_text().split()) if path.exists() else set()

    wait_until(lambda: words <= seen(), seconds)
    return seen()


def test_ctrl_c_in_a_terminal_runs_finally_and_atexit_in_the_command(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    marks = tmp_path / "marks"
    master, slave = pty.openpty()
    env = {**os.environ, "RUN_DIR": str(run_dir), "KEY": KEY}
    process = subprocess.Popen([sys.executable, "-c", PTY_CALLER, "cleanup", str(marks)], env=env, stdin=slave,
                               stdout=slave, stderr=slave)
    os.close(slave)
    try:
        assert "ready" in _until_lines(marks, {"ready"})
        os.write(master, b"\x03")  # the terminal turns this into SIGINT for the client
        assert process.wait(30) == 130
        assert {"finally", "atexit"} <= _until_lines(marks, {"finally", "atexit"})
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
            process.wait()


def test_a_client_that_dies_lets_the_command_run_finally_and_atexit(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    marks = tmp_path / "marks"
    process = subprocess.Popen([sys.executable, "-c", CALLER, "cleanup", str(marks)],
                               env={**os.environ, "RUN_DIR": str(run_dir), "KEY": KEY}, stdin=subprocess.DEVNULL)
    try:
        assert "ready" in _until_lines(marks, {"ready"})
        process.kill()  # a hang-up: the terminal went away
        process.wait()
        assert {"finally", "atexit"} <= _until_lines(marks, {"finally", "atexit"})
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_a_command_that_ignores_the_interrupt_is_killed_after_the_grace_period(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_KILL_GRACE="0.5")
    pid_file = tmp_path / "pid"
    sock, close = hold(run_dir, "ignore-term", str(pid_file))
    assert wait_until(lambda: pid_file.exists() and pid_file.read_text().isdigit())
    pid = int(pid_file.read_text())
    try:
        sock.close()
        assert wait_until(lambda: gone(pid), 10), "SIGKILL never followed the ignored SIGTERM"
    finally:
        kill_quietly(pid)
        close()


def test_a_hang_up_stops_what_the_command_started_and_leaves_the_daemon_alone(daemons, run_dir, tmp_path):
    daemon = serve(daemons, run_dir)
    pid_file = tmp_path / "pids"
    sock, close = hold(run_dir, "grandchild", str(pid_file))
    assert wait_until(lambda: pid_file.exists() and pid_file.read_text().endswith("}"))
    pids = json.loads(pid_file.read_text())
    try:
        sock.close()
        assert wait_until(lambda: gone(pids["child"]) and gone(pids["grandchild"]), 10), "the process group survived"
        assert daemon.poll() is None and client.status(run_dir=run_dir, key=KEY)["pid"] == daemon.pid
    finally:
        kill_quietly(pids["grandchild"])
        close()


# ---- finding 4: priority, limits and cpus are the caller's, never the first caller's ------------------------


def born(nice: int | None = None, nofile_soft: int | None = None, cpus: set[int] | None = None):
    """A preexec function that makes a process start with this priority, open-files limit and cpu set."""
    def apply() -> None:
        if nice is not None:
            os.setpriority(os.PRIO_PROCESS, 0, nice)
        if nofile_soft is not None:
            resource.setrlimit(resource.RLIMIT_NOFILE, (nofile_soft, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
        if cpus is not None:
            os.sched_setaffinity(0, cpus)
    return apply


def run_as(run_dir: Path, preexec=None) -> dict:
    """What the `limits` command sees when the caller is started with ``preexec``."""
    done = subprocess.run([sys.executable, "-c", CALLER, "limits"], env={**os.environ, "RUN_DIR": str(run_dir), "KEY": KEY},
                          preexec_fn=preexec, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


BASE_NICE = os.getpriority(os.PRIO_PROCESS, 0)
LOWER_NICE = min(BASE_NICE + 10, 19)  # the highest value is 19, and the test may itself run under `nice`
IS_ROOT = os.geteuid() == 0
needs_room = pytest.mark.skipif(LOWER_NICE == BASE_NICE, reason="this process already has the lowest priority")


@needs_room
def test_nice_n_10_in_front_of_the_command_lowers_its_priority(daemons, run_dir):
    serve(daemons, run_dir)
    assert run_as(run_dir)["nice"] == BASE_NICE
    assert run_as(run_dir, born(nice=LOWER_NICE))["nice"] == LOWER_NICE


@needs_room
@pytest.mark.skipif(not IS_ROOT, reason="an unprivileged process cannot give a command more priority than its daemon has")
def test_a_caller_with_the_normal_priority_does_not_inherit_the_nice_of_the_first_caller(daemons, run_dir):
    serve(daemons, run_dir, preexec=born(nice=LOWER_NICE))
    assert run_as(run_dir)["nice"] == BASE_NICE


def test_the_open_files_limit_of_the_caller_applies_and_that_of_the_first_caller_does_not(daemons, run_dir):
    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    assert soft > 64
    serve(daemons, run_dir, preexec=born(nofile_soft=64))
    assert run_as(run_dir)["nofile"][0] == soft
    assert run_as(run_dir, born(nofile_soft=48))["nofile"][0] == 48


@pytest.mark.skipif(len(os.sched_getaffinity(0)) < 2, reason="needs two cpus")
def test_the_cpu_set_of_the_caller_applies_and_that_of_the_first_caller_does_not(daemons, run_dir):
    everything = sorted(os.sched_getaffinity(0))
    serve(daemons, run_dir, preexec=born(cpus={everything[0]}))
    assert run_as(run_dir)["cpus"] == everything
    assert run_as(run_dir, born(cpus={everything[-1]}))["cpus"] == [everything[-1]]


def test_what_a_command_cannot_have_is_said_on_its_stderr_not_hidden(monkeypatch, capsys):
    def denied(*args):
        raise PermissionError(13, "Operation not permitted")

    monkeypatch.setattr(os, "setpriority", denied)
    monkeypatch.setattr(resource, "setrlimit", denied)
    monkeypatch.setattr(os, "sched_setaffinity", denied)
    runner.apply_process({"nice": -3, "rlimits": {"NOFILE": [1, 2]}, "cpus": [0]})
    err = capsys.readouterr().err
    assert "nice" in err and "NOFILE" in err and "cpus" in err and "daemon stop" in err


def _raw_exec(run_dir: Path, extra: dict) -> dict:
    request = {"op": "exec", "proto": protocol.PROTOCOL, "program": "no-read", "argv": [], "cwd": str(run_dir),
               "env": dict(os.environ), **extra}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(paths_of(run_dir, KEY).sock))
        protocol.send_request(sock, request, [0, 1, 2])
        return protocol.read_message(sock, bytearray()) or {}


def test_a_request_with_a_malformed_process_state_is_refused(daemons, run_dir):
    serve(daemons, run_dir)
    for proc in ({"nice": "high"}, {"rlimits": {"BOGUS": [1, 2]}}, {"rlimits": {"NOFILE": [1]}}, {"cpus": ["x"]}, "x"):
        assert _raw_exec(run_dir, {"proc": proc}).get("error") == "bad_request", proc


# ---- finding 5: PYTHONUNBUFFERED of the caller ---------------------------------------------------------------


def _read_available(fd: int) -> bytes:
    try:
        return os.read(fd, 4096)
    except BlockingIOError:
        return b""


def test_python_unbuffered_in_the_callers_environment_streams_output_as_it_is_written(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    release = tmp_path / "release"
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    sock = client.open_exec("unbuffered", [str(release)], run_dir=run_dir, key=KEY, cwd=str(tmp_path),
                            env={**os.environ, "PYTHONUNBUFFERED": "1"}, stdio=(in_r, out_w, out_w), autostart=False)
    try:
        os.set_blocking(out_r, False)
        seen = [b""]

        def got_first_line() -> bool:
            seen[0] += _read_available(out_r)
            return b"LINE1" in seen[0]

        assert wait_until(got_first_line, 10), "LINE1 stayed in the buffer of a command that asked for unbuffered output"
        release.write_text("go")
        assert client.wait_exit(sock) == 0
    finally:
        for fd in (in_r, in_w, out_r, out_w):
            os.close(fd)


# ---- minor findings -------------------------------------------------------------------------------------------


def test_a_command_dies_with_the_daemon_so_a_retry_cannot_make_two_writers(daemons, run_dir, tmp_path):
    daemon = serve(daemons, run_dir)
    marks = tmp_path / "marks"
    sock, close = hold(run_dir, "sleeper", str(marks), "60")
    assert wait_until(lambda: marks.exists() and marks.read_text().endswith("\n"))
    pid = json.loads(marks.read_text().splitlines()[0])["pid"]
    try:
        daemon.kill()  # the out-of-memory killer, say
        daemon.wait()
        assert wait_until(lambda: gone(pid), 10), "the command outlived its daemon"
    finally:
        kill_quietly(pid)
        sock.close()
        close()


def test_a_long_run_directory_still_gets_a_socket(daemons, tmp_path):
    long_dir = tmp_path
    while len(os.fsencode(str(long_dir))) < 130:
        long_dir = long_dir / ("d" * 30)
    long_dir.mkdir(parents=True, mode=0o700)
    long_dir.chmod(0o700)
    serve(daemons, long_dir)
    where = protocol.paths(long_dir, KEY)
    assert len(os.fsencode(where.sock)) <= protocol.MAX_SOCKET_PATH and not where.sock.startswith(str(long_dir))
    assert stat.S_IMODE(os.stat(os.path.dirname(where.sock)).st_mode) == 0o700
    assert call(long_dir, "no-read").out.strip() == "did not read stdin"


def test_the_socket_of_a_short_run_directory_stays_in_it(run_dir):
    assert protocol.paths(run_dir, KEY).sock == str(run_dir / f"{KEY}.sock")


def test_the_parent_of_the_run_directory_must_belong_to_this_user_or_to_root(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    mine.mkdir(mode=0o700)
    real = os.lstat

    def lstat(path, *args, **options):
        info = real(path, *args, **options)
        if os.fspath(path) != str(tmp_path):
            return info
        fields = list(info)
        fields[4] = 4242  # st_uid
        return os.stat_result(fields)

    monkeypatch.setattr(protocol.os, "lstat", lstat)
    with pytest.raises(protocol.DaemonError) as caught:
        protocol.secure_dir(mine)
    assert caught.value.code == "dir_parent_owner"


def test_a_parent_others_can_write_is_refused_unless_it_is_sticky(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o777)
    with pytest.raises(protocol.DaemonError) as caught:
        protocol.secure_dir(parent / "run")
    assert caught.value.code == "dir_parent"
    parent.chmod(0o1777)
    assert protocol.secure_dir(parent / "run").endswith("run")


def test_the_client_refuses_a_socket_that_belongs_to_another_user(tmp_path, monkeypatch):
    path = tmp_path / "s.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    os.chmod(path, 0o600)
    monkeypatch.setattr(client.os, "geteuid", lambda: os.stat(path).st_uid + 1)
    try:
        with pytest.raises(protocol.DaemonError) as caught:
            client._connect(protocol.Paths(str(path), "", ""))
        assert caught.value.code == "socket_owner"
    finally:
        listener.close()


def test_nested_requests_have_a_ceiling_too(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")
    nested = {**os.environ, protocol.NESTED_ENV: "1"}
    held = []
    try:
        for _ in range(4):  # NESTED_FACTOR times the one slot
            held.append(hold(run_dir, "sleeper", str(tmp_path / "n"), "30", env=nested))
        with pytest.raises(protocol.DaemonError) as caught:
            hold(run_dir, "sleeper", str(tmp_path / "n"), "30", env=nested)
        assert caught.value.code == "busy"
    finally:
        for sock, close in held:
            sock.close()
            close()


def test_a_command_that_waits_for_a_slot_is_told_so_and_then_runs(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1", DAEMON_TEST_WAIT_NOTICE="0.3")
    first, close = hold(run_dir, "sleeper", str(tmp_path / "m"), "1.5")
    err_r, err_w = os.pipe()
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    try:
        started = time.monotonic()
        waiting = client.open_exec("no-read", [], run_dir=run_dir, key=KEY, cwd=str(tmp_path), env=dict(os.environ),
                                   stdio=(in_r, out_w, err_w), autostart=False)
        assert time.monotonic() - started >= 1.0, "it did not wait for the slot"
        assert client.wait_exit(waiting) == 0
        os.set_blocking(err_r, False)
        assert b"waiting for a free slot" in os.read(err_r, 4096)
    finally:
        first.close()
        for fd in (err_r, err_w, in_r, in_w, out_r, out_w):
            os.close(fd)
        close()


def test_a_command_that_waits_too_long_for_a_slot_is_refused_with_the_reason(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1", DAEMON_TEST_WAIT_NOTICE="0.2", DAEMON_TEST_MAX_WAIT="1")
    first, close = hold(run_dir, "sleeper", str(tmp_path / "m"), "30")
    try:
        started = time.monotonic()
        with pytest.raises(protocol.DaemonError) as caught:
            call(run_dir, "no-read")
        assert caught.value.code == "busy" and "waited" in str(caught.value)
        assert time.monotonic() - started < 10
    finally:
        first.close()
        close()


# ---- the sandbox of the 24/7 watcher cannot turn the daemon back on -----------------------------------------


def test_a_variable_kept_for_the_sandbox_cannot_reactivate_the_daemon():
    from simplicio_loop.watcher247 import sandbox

    env = sandbox.scrubbed_env({protocol.OPT_OUT_ENV: "1"}, home=Path("/h"), keep=(protocol.OPT_OUT_ENV,))
    assert env[protocol.OPT_OUT_ENV] == "0"


# ---- the refusal that raced the request (test_a_peer_of_another_user_is_refused failed 4.3% of runs) ----------


def test_a_refusal_sent_before_the_request_is_read_is_reported_as_the_refusal(run_dir, monkeypatch):
    path = protocol.paths(run_dir, KEY).sock
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    os.chmod(path, 0o600)
    listener.listen(1)
    refused = threading.Event()

    def refuse() -> None:  # what the daemon does with a peer of another user: answer and close, reading nothing
        connection, _ = listener.accept()
        connection.sendall(b'{"error":"peer_uid","message":"this socket serves another user"}\n')
        connection.close()
        refused.set()

    threading.Thread(target=refuse, daemon=True).start()
    real = protocol.send_request

    def late(*args, **options):  # the request goes out after the daemon has closed: the worst ordering
        refused.wait(10)
        return real(*args, **options)

    monkeypatch.setattr(protocol, "send_request", late)
    try:
        with pytest.raises(protocol.DaemonError) as caught:
            client.open_exec("state", [], run_dir=run_dir, key=KEY, cwd=str(run_dir), env=dict(os.environ), autostart=False)
        assert caught.value.code == "peer_uid"
    finally:
        listener.close()
