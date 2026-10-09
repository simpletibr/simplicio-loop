"""What the post-merge audits of the daemon found (issue #1590, audits of PR #1602 and PR #1645): each finding has a
test that fails without its fix, and each hole the audits found in the suite has a test that kills the mutant.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pty
import resource
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
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


def hold(run_dir: Path, program: str, *args: str, env: dict | None = None, key: str = KEY):
    """Start a command and keep its connection: returns (socket, closer of the descriptors we made)."""
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    try:
        sock = client.open_exec(program, list(args), run_dir=run_dir, key=key, cwd=str(run_dir),
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


# ---- audit of PR #1645, finding A: a queued command whose caller gave up must not run --------------------------


def _queued(run_dir: Path, marker: Path) -> subprocess.Popen:
    """A caller in a process of its own whose command (``sleeper``: it writes its start to ``marker``) waits for a slot."""
    return subprocess.Popen([sys.executable, "-c", CALLER, "sleeper", str(marker), "0.1"], stdin=subprocess.DEVNULL,
                            env={**os.environ, "RUN_DIR": str(run_dir), "KEY": KEY})


def _waiting(run_dir: Path) -> int:
    return client.status(run_dir=run_dir, key=KEY)["waiting"]


def _drained(run_dir: Path) -> bool:
    status = client.status(run_dir=run_dir, key=KEY)
    return status["waiting"] == 0 and status["active"] == 0


def test_a_queued_command_whose_caller_gave_up_does_not_run_when_the_slot_frees(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")
    first, close = hold(run_dir, "sleeper", str(tmp_path / "first"), "3")
    marker = tmp_path / "queued"
    queued = _queued(run_dir, marker)
    try:
        assert wait_until(lambda: _waiting(run_dir) == 1), "the command did not queue"
        queued.kill()  # Ctrl-C or a closed terminal: nobody wants this command any more
        queued.wait()
        assert wait_until(lambda: _drained(run_dir), 30), "the slot never freed"
        assert not wait_until(marker.exists, 1.5), "the command of a caller that was gone ran when the slot freed"
        assert client.status(run_dir=run_dir, key=KEY)["served"] == 1, "the daemon started the command of a caller that was gone"
        assert call(run_dir, "no-read").out.strip() == "did not read stdin"  # and the daemon goes on serving
    finally:
        kill_quietly(queued.pid)
        first.close()
        close()


def test_a_live_caller_in_the_queue_still_runs_when_the_slot_frees(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")
    first, close = hold(run_dir, "sleeper", str(tmp_path / "first"), "2")
    marker = tmp_path / "queued"
    queued = _queued(run_dir, marker)
    try:
        assert wait_until(lambda: _waiting(run_dir) == 1), "the command did not queue"
        assert queued.wait(60) == 0
        assert [json.loads(line)["event"] for line in marker.read_text().splitlines()] == ["start", "end"]
    finally:
        kill_quietly(queued.pid)
        first.close()
        close()


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="counts the descriptors of the daemon in /proc")
def test_a_queued_command_that_gave_up_leaves_no_descriptor_open_in_the_daemon(daemons, run_dir, tmp_path):
    daemon = serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")

    def open_fds() -> int:
        return len(os.listdir(f"/proc/{daemon.pid}/fd"))

    assert call(run_dir, "no-read").rc == 0
    assert wait_until(lambda: _waiting(run_dir) == 0)
    idle = open_fds()
    first, close = hold(run_dir, "sleeper", str(tmp_path / "first"), "3")
    gone = [_queued(run_dir, tmp_path / f"queued{n}") for n in range(2)]
    try:
        assert wait_until(lambda: _waiting(run_dir) == 2), "the commands did not queue"
        for process in gone:
            process.kill()
            process.wait()
        assert wait_until(lambda: _waiting(run_dir) == 0, 30), "the slot never freed"
        first.close()
        assert wait_until(lambda: open_fds() == idle, 10), f"{open_fds() - idle} descriptors leaked in the daemon"
    finally:
        for process in gone:
            kill_quietly(process.pid)
        first.close()
        close()


# ---- audit of PR #1645, finding B: the short socket is the same path for every caller ---------------------------


def _long(base: Path, tag: str) -> Path:
    """A run directory whose ``<key>.sock`` does not fit in a unix socket path (it need not exist)."""
    directory = base / tag
    while len(os.fsencode(str(directory))) < 130:
        directory = directory / ("d" * 30)
    return directory


def _fixed_dir() -> str:
    return f"/tmp/simplicio-loop-{os.geteuid()}"


@pytest.fixture
def tmpdirs():
    """Two short temporary directories of our own, like the ones a CI sets per task (a long TMPDIR would fail anyway)."""
    made = [Path(tempfile.mkdtemp(prefix="tm", dir="/tmp")) for _ in range(2)]
    yield made
    for directory in made:  # exactly the two we made, never a shared name
        shutil.rmtree(directory, ignore_errors=True)


def test_two_long_run_directories_get_two_sockets(tmp_path):
    one, two = protocol.paths(_long(tmp_path, "a"), KEY), protocol.paths(_long(tmp_path, "b"), KEY)
    assert one.sock != two.sock and one.pid != two.pid and one.log != two.log
    assert os.path.dirname(one.sock) == os.path.dirname(two.sock)
    assert protocol.paths(_long(tmp_path, "a"), KEY).sock == one.sock, "the same directory must give the same socket"
    assert protocol.paths(_long(tmp_path, "a"), "otherkey").sock != one.sock


def test_the_short_socket_is_the_same_path_whatever_the_tmpdir_of_the_caller(tmp_path, monkeypatch, tmpdirs):
    socks = set()
    for elsewhere in tmpdirs:
        monkeypatch.setenv("TMPDIR", str(elsewhere))
        monkeypatch.setattr(tempfile, "tempdir", None)  # tempfile caches the first answer
        socks.add(protocol.paths(_long(tmp_path, "run"), KEY).sock)
    assert len(socks) == 1 and os.path.dirname(socks.pop()) == _fixed_dir()


def _fake_euid(monkeypatch) -> int:
    fake = 4_000_000 + os.getpid()  # a name of our own: /tmp/simplicio-loop-<real uid> is shared with every run
    monkeypatch.setattr(os, "geteuid", lambda: fake)
    return fake


def test_the_fixed_socket_directory_is_refused_when_it_is_a_symlink(tmp_path, monkeypatch):
    fixed = Path(f"/tmp/simplicio-loop-{_fake_euid(monkeypatch)}")
    fixed.symlink_to(tmp_path)
    try:
        with pytest.raises(protocol.DaemonError) as caught:
            protocol.paths(_long(tmp_path, "a"), KEY)
    finally:
        fixed.unlink()
    assert caught.value.code == "dir_symlink"


def test_the_fixed_socket_directory_is_refused_when_another_user_owns_it(tmp_path, monkeypatch):
    fixed = Path(f"/tmp/simplicio-loop-{_fake_euid(monkeypatch)}")
    fixed.mkdir(mode=0o700)  # ours, but the euid the code sees is another one
    try:
        with pytest.raises(protocol.DaemonError) as caught:
            protocol.paths(_long(tmp_path, "a"), KEY)
    finally:
        fixed.rmdir()
    assert caught.value.code == "dir_owner"


def test_callers_with_different_tmpdirs_share_one_daemon_for_a_long_run_directory(tmp_path, tmpdirs):
    directory = _long(tmp_path, "run")
    directory.mkdir(parents=True)
    directory.chmod(0o700)
    env = {**os.environ, protocol.DIR_ENV: str(directory), "SIMPLICIO_LOOP_DAEMON_IDLE_S": "60",
           protocol.OPT_OUT_ENV: "1", "PYTHONDONTWRITEBYTECODE": "1"}

    def launch(*arguments: str, tmpdir: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", LAUNCH, *arguments], env={**env, "TMPDIR": str(tmpdir)},
                              capture_output=True, timeout=90)

    try:
        first = launch("--version", tmpdir=tmpdirs[0])
        assert first.returncode == 0, first.stderr
        started = time.monotonic()
        status = launch("daemon", "status", tmpdir=tmpdirs[1])
        assert status.returncode == 0, f"the second caller found no daemon: {status.stdout!r}"
        assert json.loads(status.stdout)["socket"] == json.loads(launch("daemon", "status", tmpdir=tmpdirs[0]).stdout)["socket"]
        second = launch("--version", tmpdir=tmpdirs[1])
        assert second.returncode == 0 and second.stdout == first.stdout, second.stderr
        assert time.monotonic() - started < 5, "the second caller started a daemon of its own and waited"
    finally:
        launch("daemon", "stop", tmpdir=tmpdirs[0])


# ---- found while testing finding A: a caller that hangs up right after the fork must not stop the daemon -------------


def test_a_caller_that_hangs_up_right_after_the_daemon_forked_cannot_stop_the_daemon(daemons, run_dir):
    """The daemon signals the child of a caller that is gone. Before the child has its own handlers, that signal
    used to reach the daemon through the wakeup descriptor they share: 1 immediate hang-up in 5 stopped it."""
    daemon = serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="8")
    for attempt in range(60):
        try:
            sock, close = hold(run_dir, "no-read")
        except protocol.DaemonError as error:
            pytest.fail(f"the daemon was gone after {attempt} immediate hang-ups: {error}")
        sock.close()
        close()
    time.sleep(0.5)
    assert daemon.poll() is None and client.status(run_dir=run_dir, key=KEY)["pid"] == daemon.pid
    assert call(run_dir, "no-read").out.strip() == "did not read stdin"


def test_the_daemon_still_stops_on_sigterm_after_it_ran_commands(daemons, run_dir):
    daemon = serve(daemons, run_dir)
    assert call(run_dir, "no-read").rc == 0
    daemon.send_signal(signal.SIGTERM)  # the signals held back around the fork are the child's, never the daemon's
    assert daemon.wait(10) == 0


# ---- audit of PR #1645, minor: a huge number from a caller of the same user -----------------------------------


@pytest.mark.parametrize("proc", [{"nice": 10**30}, {"rlimits": {"NOFILE": [10**30, 10**30]}}, {"cpus": [10**30]}],
                         ids=["nice", "rlimit", "cpus"])
def test_a_number_too_big_for_the_system_is_refused_in_words_not_with_a_traceback(capsys, proc):
    assert protocol.valid_process_state(proc)  # the wire format allows it: the system call is what refuses
    runner.apply_process(proc)
    err = capsys.readouterr().err
    assert "the system refused" in err and "Traceback" not in err


def test_a_command_whose_caller_sent_a_huge_number_still_runs(daemons, run_dir, monkeypatch):
    serve(daemons, run_dir)
    monkeypatch.setattr(protocol, "process_state", lambda: {"nice": 10**30})
    done = call(run_dir, "no-read")
    assert done.rc == 0 and "did not read stdin" in done.out
    assert "nice" in done.err and "Traceback" not in done.err


# ---- audit of PR #1645, mutant N20: the wait limit of the environment reaches the daemon `daemon serve` starts --------


SERVE_TEST_PROGRAMS = (  # `daemon serve` as the console script runs it, with the test programs added to the daemon
    "import sys; sys.path.insert(0, sys.argv[1]); import daemon_helpers\n"
    "from simplicio_loop.daemon import control, server\n"
    "real = server.Daemon\n"
    "server.Daemon = lambda *a, **k: real(*a, programs=daemon_helpers.PROGRAMS, preload=(), **k)\n"
    "sys.exit(control.main(['serve']))")


def test_the_wait_limit_of_the_environment_reaches_the_daemon_that_daemon_serve_starts(daemons, run_dir, tmp_path):
    key = protocol.daemon_key()
    env = {**os.environ, protocol.DIR_ENV: str(run_dir), "SIMPLICIO_LOOP_DAEMON_MAX_CHILDREN": "1",
           "SIMPLICIO_LOOP_DAEMON_WAIT_S": "6", "SIMPLICIO_LOOP_DAEMON_IDLE_S": "60", "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen([sys.executable, "-c", SERVE_TEST_PROGRAMS, str(_suite.HELPERS.parent)], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    daemons.append(process)
    assert wait_until(paths_of(run_dir, key).sock.exists, 30), f"daemon serve did not start: {process.poll()}"
    first, close = hold(run_dir, "sleeper", str(tmp_path / "first"), "30", key=key)
    outcome: list = []

    def second() -> None:
        try:
            outcome.append(call(run_dir, "no-read", key=key))
        except protocol.DaemonError as error:
            outcome.append(error)

    thread = threading.Thread(target=second, daemon=True)
    thread.start()
    try:
        thread.join(25)
        assert outcome, "the second command still waits after 25 s: WAIT_S=6 never reached the daemon"
        assert isinstance(outcome[0], protocol.DaemonError) and outcome[0].code == "busy"
        assert "waited 6s" in str(outcome[0])
    finally:
        first.close()
        close()
