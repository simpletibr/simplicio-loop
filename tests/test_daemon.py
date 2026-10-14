"""The asyncio daemon (issue #1590): socket security, handshake, isolation between requests, lifecycle, limits.

Each test starts a real daemon process (``daemon_helpers.py serve``) in its own run directory, so the
checks cover the real socket, the real fork and the real exit codes. Nothing here touches the network.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from simplicio_loop.daemon import client, protocol

pytestmark = pytest.mark.skipif(not protocol.supported(), reason="needs AF_UNIX, fork and fd passing")

HELPERS = Path(__file__).with_name("daemon_helpers.py")
KEY = "testkey"


def paths_of(directory, key):
    """protocol.paths with real Path objects, for exists() and stat()."""
    found = protocol.paths(directory, key)
    return type(found)(*(Path(p) for p in found))


@dataclass
class Result:
    rc: int
    out: str
    err: str


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "r"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def daemons():
    started: list[subprocess.Popen] = []
    yield started
    for proc in started:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def serve(daemons, run_dir: Path, wait: bool = True, preexec=None, **env: str) -> subprocess.Popen:
    """Start a test daemon; ``preexec`` runs in it before exec (to be born under a nice value or a limit)."""
    full = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "1", "PYTHONDONTWRITEBYTECODE": "1", **env}
    proc = subprocess.Popen([sys.executable, str(HELPERS), "serve", str(run_dir)], env=full, preexec_fn=preexec,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    daemons.append(proc)
    if wait:
        sock = paths_of(run_dir, env.get("DAEMON_TEST_KEY", KEY)).sock
        deadline = time.monotonic() + 30
        while not sock.exists():
            if proc.poll() is not None:
                raise AssertionError(f"daemon died: {proc.stderr.read().decode()}")
            assert time.monotonic() < deadline, "daemon did not create its socket"
            time.sleep(0.02)
    return proc


def call(run_dir: Path, program: str, *args: str, cwd=None, env=None, stdin: bytes | None = b"",
         key: str = KEY) -> Result:
    """Run one program through the daemon with captured stdio. ``stdin=None`` leaves stdin open and silent."""
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    if stdin is not None:
        os.write(in_w, stdin)
        os.close(in_w)
    try:
        request_env = dict(os.environ) if env is None else env
        rc = client.exec_program(program, list(args), run_dir=run_dir, key=key, cwd=str(cwd or os.getcwd()),
                                 env=request_env, stdio=(in_r, out_w, err_w), autostart=False)
    finally:
        for fd in (in_r, out_w, err_w):
            os.close(fd)
        if stdin is None:
            os.close(in_w)
    out, err = os.read(out_r, 1 << 20), os.read(err_r, 1 << 20)
    os.close(out_r)
    os.close(err_r)
    return Result(rc, out.decode(), err.decode())


# ---- the run directory and the socket -------------------------------------------------------------------


def test_secure_dir_creates_a_private_directory(tmp_path):
    made = protocol.secure_dir(tmp_path / "new" / "run")
    assert stat.S_IMODE(os.stat(made).st_mode) == 0o700


def test_secure_dir_refuses_a_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(protocol.DaemonError) as caught:
        protocol.secure_dir(link)
    assert caught.value.code == "dir_symlink"


def test_secure_dir_refuses_a_directory_others_can_open(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o775)
    with pytest.raises(protocol.DaemonError) as caught:
        protocol.secure_dir(loose)
    assert caught.value.code == "dir_mode"


def test_secure_dir_refuses_a_directory_of_someone_else(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    mine.mkdir(mode=0o700)
    monkeypatch.setattr(protocol.os, "geteuid", lambda: os.stat(mine).st_uid + 1)
    with pytest.raises(protocol.DaemonError) as caught:
        protocol.secure_dir(mine)
    assert caught.value.code == "dir_owner"


def test_socket_and_pid_file_are_private(daemons, run_dir):
    serve(daemons, run_dir)
    paths = paths_of(run_dir, KEY)
    assert stat.S_ISSOCK(paths.sock.stat().st_mode)
    assert stat.S_IMODE(paths.sock.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.pid.stat().st_mode) == 0o600
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700


def test_client_refuses_a_socket_other_users_can_write(run_dir):
    sock_path = protocol.paths(run_dir, KEY).sock
    loose = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    loose.bind(sock_path)
    loose.listen(1)
    os.chmod(sock_path, 0o666)

    def answer() -> None:  # a server that would run anything it is sent, so only the client check can stop it
        try:
            connection, _ = loose.accept()
        except OSError:
            return
        with connection:
            connection.sendall(b'{"ok":true}\n{"exit":0}\n')

    threading.Thread(target=answer, daemon=True).start()
    try:
        with pytest.raises(protocol.DaemonError) as caught:
            call(run_dir, "state")
        assert caught.value.code == "socket_mode"
    finally:
        loose.close()


def test_client_refuses_a_socket_in_a_loose_directory(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)
    with pytest.raises(protocol.DaemonError) as caught:
        call(loose, "state")
    assert caught.value.code == "dir_mode"


def test_a_peer_of_another_user_is_refused(daemons, run_dir):
    serve(daemons, run_dir, DAEMON_TEST_ALLOWED_UID=str(os.geteuid() + 1))
    with pytest.raises(protocol.DaemonError) as caught:
        call(run_dir, "state")
    assert caught.value.code == "peer_uid"


def test_the_daemon_runs_for_the_user_it_serves(daemons, run_dir):
    serve(daemons, run_dir)
    assert call(run_dir, "no-read").out.strip() == "did not read stdin"


# ---- handshake ------------------------------------------------------------------------------------------


def raw(run_dir: Path, line: bytes, key: str = KEY) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(paths_of(run_dir, key).sock))
        sock.sendall(line)
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.splitlines()[0])


def test_a_request_with_the_wrong_protocol_is_refused(daemons, run_dir):
    serve(daemons, run_dir)
    reply = raw(run_dir, b'{"op":"status","proto":999}\n')
    assert reply["error"] == "protocol"
    assert raw(run_dir, b'{"op":"status","proto":%d}\n' % protocol.PROTOCOL)["ok"] is True


def test_a_request_without_a_protocol_is_refused(daemons, run_dir):
    serve(daemons, run_dir)
    assert raw(run_dir, b'{"op":"status"}\n')["error"] == "protocol"


def test_malformed_and_unknown_requests_are_refused(daemons, run_dir):
    serve(daemons, run_dir)
    assert raw(run_dir, b"not json\n")["error"] == "bad_request"
    assert raw(run_dir, b'{"op":"rm-rf","proto":%d}\n' % protocol.PROTOCOL)["error"] == "bad_request"
    with pytest.raises(protocol.DaemonError) as caught:
        call(run_dir, "no-such-program")
    assert caught.value.code == "unknown_program"


def test_status_reports_identity_and_limits(daemons, run_dir):
    proc = serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="3")
    info = client.status(run_dir=run_dir, key=KEY)
    assert info["pid"] == proc.pid
    assert info["max_children"] == 3
    assert info["protocol"] == protocol.PROTOCOL
    assert "fingerprint" in info and "uptime_s" in info and "active" in info
    assert info["threads"] == 1, "the parent must be single-threaded at the point of the fork"
    assert info["rss_mb"] > 0


def test_code_changed_on_disk_makes_the_daemon_refuse_and_exit(daemons, run_dir, tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    module = package / "a.py"
    module.write_text("X = 1\n")
    proc = serve(daemons, run_dir, DAEMON_TEST_ROOTS=str(package))
    assert call(run_dir, "no-read").rc == 0
    time.sleep(0.05)
    module.write_text("X = 22\n")  # an update or an edit: the daemon holds the old code
    with pytest.raises(protocol.DaemonError) as caught:
        call(run_dir, "no-read")
    assert caught.value.code == "stale"
    assert proc.wait(10) == 0
    assert not paths_of(run_dir, KEY).sock.exists()


# ---- isolation between requests -------------------------------------------------------------------------


def test_two_concurrent_requests_keep_their_own_cwd_and_env(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    repos = []
    for name in ("repo_a", "repo_b"):
        repo = tmp_path / name
        repo.mkdir()
        repos.append(repo)
    results: dict[str, Result] = {}

    def go(name: str, repo: Path) -> None:
        env = {"PATH": os.environ["PATH"], "REQ_VAR": name, "HOLD_S": "0.6"}
        results[name] = call(run_dir, "state", cwd=repo, env=env)

    threads = [threading.Thread(target=go, args=(n, r)) for n, r in zip(("a", "b"), repos)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert time.monotonic() - started < 1.15, "the two requests did not run at the same time"
    for name, repo in zip(("a", "b"), repos):
        seen = json.loads(results[name].out)
        assert seen["cwd"] == str(repo.resolve()) and seen["var"] == name
        assert seen["leak"] is None and seen["counter"] == 0


def test_state_set_by_one_request_never_reaches_the_next(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    env = {"PATH": os.environ["PATH"], "REQ_VAR": "first"}
    first = json.loads(call(run_dir, "state", cwd=tmp_path, env=env).out)
    second = json.loads(call(run_dir, "state", cwd=tmp_path, env={"PATH": os.environ["PATH"]}).out)
    assert first["counter"] == 0 and second["counter"] == 0
    assert second["leak"] is None and second["var"] is None
    assert second["argv"] == ["state"]


def test_the_environment_of_the_daemon_never_reaches_a_command(daemons, run_dir):
    serve(daemons, run_dir, DAEMON_ONLY="secret-of-the-first-caller")
    seen = json.loads(call(run_dir, "state", env={"PATH": os.environ["PATH"]}).out)
    assert seen["daemon_only"] is None


def test_the_parent_never_runs_command_code(daemons, run_dir):
    proc = serve(daemons, run_dir)
    seen = json.loads(call(run_dir, "state").out)
    assert seen["pid"] != proc.pid
    assert client.status(run_dir=run_dir, key=KEY)["pid"] == proc.pid


def test_the_command_gets_the_client_environment_even_when_empty(daemons, run_dir):
    serve(daemons, run_dir)
    seen = json.loads(call(run_dir, "state", env={}).out)
    assert seen["has_path"] is False


# ---- stdio and exit codes -------------------------------------------------------------------------------


def test_exit_code_stdout_and_stderr_are_kept(daemons, run_dir):
    serve(daemons, run_dir)
    result = call(run_dir, "exit-with", "3")
    assert (result.rc, result.out, result.err) == (3, "to stdout\n", "to stderr\n")


def test_system_exit_with_a_message_and_an_uncaught_error_behave_like_python(daemons, run_dir):
    serve(daemons, run_dir)
    text = call(run_dir, "exit-text")
    assert text.rc == 1 and text.err.strip() == "goodbye"
    boom = call(run_dir, "boom")
    assert boom.rc == 1 and "RuntimeError: kaboom" in boom.err and "Traceback" in boom.err


def test_a_command_killed_by_a_signal_reports_128_plus_the_signal(daemons, run_dir):
    serve(daemons, run_dir)
    assert call(run_dir, "killed").rc == 128 + signal.SIGKILL


def test_stdin_reaches_the_command(daemons, run_dir):
    serve(daemons, run_dir)
    assert call(run_dir, "upper", stdin="plano ação\n".encode()).out == "PLANO AÇÃO\n"


def test_a_command_that_ignores_stdin_does_not_wait_for_it(daemons, run_dir):
    serve(daemons, run_dir)
    started = time.monotonic()
    result = call(run_dir, "no-read", stdin=None)  # stdin stays open and silent
    assert result.rc == 0 and time.monotonic() - started < 5


def test_asyncio_run_works_inside_a_command(daemons, run_dir):
    serve(daemons, run_dir)
    assert call(run_dir, "aio").out.strip() == "7"


def test_the_stdio_of_the_command_is_the_stdio_of_the_client(daemons, run_dir):
    serve(daemons, run_dir)
    seen = json.loads(call(run_dir, "tty-info").out)
    assert seen["in"] is False and seen["out"] is False


# ---- lifecycle and limits -------------------------------------------------------------------------------


def test_the_daemon_exits_when_idle_and_cleans_up(daemons, run_dir):
    proc = serve(daemons, run_dir, DAEMON_TEST_IDLE="0.6")
    paths = paths_of(run_dir, KEY)
    assert proc.wait(15) == 0
    assert not paths.sock.exists() and not paths.pid.exists()


def test_a_running_command_keeps_the_daemon_alive(daemons, run_dir, tmp_path):
    proc = serve(daemons, run_dir, DAEMON_TEST_IDLE="0.5")
    marks = tmp_path / "marks"
    result = call(run_dir, "sleeper", str(marks), "1.6")
    assert result.rc == 0 and len(marks.read_text().splitlines()) == 2
    assert proc.poll() is None or proc.returncode == 0


def test_stop_ends_the_daemon_and_removes_its_files(daemons, run_dir):
    proc = serve(daemons, run_dir)
    assert client.stop(run_dir=run_dir, key=KEY) is True
    assert proc.wait(15) == 0
    paths = paths_of(run_dir, KEY)
    assert not paths.sock.exists() and not paths.pid.exists()
    assert client.stop(run_dir=run_dir, key=KEY) is False


def test_a_second_daemon_for_the_same_key_leaves_quietly(daemons, run_dir):
    first = serve(daemons, run_dir)
    second = serve(daemons, run_dir, wait=False)
    assert second.wait(15) == 0
    assert first.poll() is None
    assert call(run_dir, "no-read").rc == 0


def test_concurrent_commands_are_capped_and_the_rest_wait(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")
    marks = tmp_path / "marks"
    threads = [threading.Thread(target=call, args=(run_dir, "sleeper", str(marks), "0.5")) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    events = [json.loads(line) for line in marks.read_text().splitlines()]
    running = peak = 0
    for event in sorted(events, key=lambda e: e["t"]):
        running += 1 if event["event"] == "start" else -1
        peak = max(peak, running)
    assert len(events) == 6 and peak == 1


def test_a_request_from_inside_a_command_takes_no_slot_so_the_pool_cannot_deadlock(daemons, run_dir):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1")  # the one slot is held by the command that asks
    outcome: list[Result] = []
    thread = threading.Thread(target=lambda: outcome.append(call(run_dir, "nested")), daemon=True)
    thread.start()
    thread.join(30)
    assert not thread.is_alive(), "the nested request waited for a slot its own parent holds"
    assert outcome[0].rc == 0 and outcome[0].out.strip() == "did not read stdin"


def test_a_full_queue_is_refused_instead_of_growing_without_bound(daemons, run_dir, tmp_path):
    serve(daemons, run_dir, DAEMON_TEST_MAX_CHILDREN="1", DAEMON_TEST_MAX_WAITING="1")
    marks = tmp_path / "marks"
    outcomes: list[object] = []

    def go() -> None:
        try:
            outcomes.append(call(run_dir, "sleeper", str(marks), "1.0").rc)
        except protocol.DaemonError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
        time.sleep(0.15)
    for t in threads:
        t.join(30)
    assert outcomes.count("busy") >= 1 and outcomes.count(0) >= 2


def test_a_client_that_hangs_up_stops_its_command(daemons, run_dir, tmp_path):
    serve(daemons, run_dir)
    marks = tmp_path / "marks"
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    sock = client.open_exec(
        "sleeper", [str(marks), "30"], run_dir=run_dir, key=KEY, cwd=str(tmp_path),
        env=dict(os.environ), stdio=(in_r, out_w, out_w), autostart=False)
    deadline = time.monotonic() + 15
    while not marks.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    pid = json.loads(marks.read_text().splitlines()[0])["pid"]
    sock.close()  # the client went away
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, signal.SIGKILL)
        pytest.fail("the command outlived its client")
    for fd in (in_r, in_w, out_r, out_w):
        os.close(fd)


# ---- starting the daemon --------------------------------------------------------------------------------


def test_the_first_call_starts_the_daemon_and_waits_for_the_socket(daemons, run_dir):
    start = [sys.executable, str(HELPERS), "serve", str(run_dir)]
    env = dict(os.environ)
    out_r, out_w = os.pipe()
    rc = client.exec_program("no-read", [], run_dir=run_dir, key=KEY, cwd=os.getcwd(), env=env,
                             stdio=(os.open(os.devnull, os.O_RDONLY), out_w, out_w), autostart=True,
                             start_command=start, wait_s=30)
    os.close(out_w)
    assert rc == 0 and os.read(out_r, 100).decode().strip() == "did not read stdin"
    os.close(out_r)
    info = client.status(run_dir=run_dir, key=KEY)
    os.kill(info["pid"], signal.SIGTERM)


def test_a_daemon_that_cannot_start_is_a_clear_error_not_a_silent_fallback(run_dir):
    start = [sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)"]
    with pytest.raises(protocol.DaemonError) as caught:
        client.exec_program("no-read", [], run_dir=run_dir, key=KEY, cwd=os.getcwd(), env=dict(os.environ),
                            stdio=(0, 1, 2), autostart=True, start_command=start, wait_s=10)
    assert caught.value.code == "start_failed"
    assert "SIMPLICIO_LOOP_DAEMON=0" in str(caught.value)


def test_without_autostart_a_missing_daemon_is_an_error(run_dir):
    with pytest.raises(protocol.DaemonError) as caught:
        call(run_dir, "no-read")
    assert caught.value.code == "not_running"


def test_the_daemon_key_separates_installations_and_environments(tmp_path):
    base = protocol.daemon_key({"PYTHONPATH": ""}, exe="/a/python", package_dir="/x/simplicio_loop")
    assert base == protocol.daemon_key({"PYTHONPATH": ""}, exe="/a/python", package_dir="/x/simplicio_loop")
    assert base != protocol.daemon_key({"PYTHONPATH": ""}, exe="/b/python", package_dir="/x/simplicio_loop")
    assert base != protocol.daemon_key({"PYTHONPATH": ""}, exe="/a/python", package_dir="/y/simplicio_loop")
    assert base != protocol.daemon_key({"PYTHONPATH": "/p"}, exe="/a/python", package_dir="/x/simplicio_loop")
    assert base != protocol.daemon_key({"SIMPLICIO_CORE_NO_NETWORK": "1"}, exe="/a/python", package_dir="/x/simplicio_loop")


# ---- the launcher ---------------------------------------------------------------------------------------


def test_the_opt_out_runs_in_process_and_never_touches_the_daemon(run_dir):
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "0", "SIMPLICIO_LOOP_DAEMON_DIR": str(run_dir)}
    done = subprocess.run([sys.executable, "-c", "from simplicio_loop.daemon.client import main; import sys; sys.exit(main(['--version']))"],
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.startswith("simplicio-loop ")
    assert list(run_dir.iterdir()) == []


def test_the_launcher_does_not_import_the_command_surface():
    code = ("import sys; import simplicio_loop.daemon.client; "
            "heavy = [m for m in ('simplicio_loop.cli_impl', 'asyncio', 'jsonschema', 'simplicio_mapper') if m in sys.modules]; "
            "print(heavy)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "[]", done.stdout + done.stderr


# ---- what the daemon keeps and what it prints -----------------------------------------------------------


def test_the_log_never_holds_arguments_or_environment(daemons, run_dir):
    proc = serve(daemons, run_dir)
    env = {"PATH": os.environ["PATH"], "SECRET_ENV": "secret-env-456"}
    assert call(run_dir, "no-read", "secret-arg-123", env=env).rc == 0
    assert client.stop(run_dir=run_dir, key=KEY)
    proc.wait(15)
    log = proc.stderr.read().decode()
    assert "no-read exit=0" in log
    assert "secret" not in log


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="needs /proc")
def test_the_started_daemon_does_not_keep_the_environment_of_its_first_caller(run_dir):
    start = [sys.executable, str(HELPERS), "serve", str(run_dir)]
    env = {**os.environ, "SECRET_TOKEN": "secret-token-789"}
    sink = os.open(os.devnull, os.O_WRONLY)
    try:
        assert client.exec_program("no-read", [], run_dir=run_dir, key=KEY, cwd=os.getcwd(), env=env,
                                   stdio=(os.open(os.devnull, os.O_RDONLY), sink, sink), autostart=True,
                                   start_command=start, wait_s=30) == 0
    finally:
        os.close(sink)
    pid = client.status(run_dir=run_dir, key=KEY)["pid"]
    try:
        held = Path(f"/proc/{pid}/environ").read_bytes()
        assert b"secret-token-789" not in held and b"PATH=" in held
    finally:
        os.kill(pid, signal.SIGTERM)


def test_the_console_script_exits_69_and_names_the_opt_out_when_the_daemon_cannot_serve(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "1", "SIMPLICIO_LOOP_DAEMON_DIR": str(loose)}
    done = subprocess.run([sys.executable, "-c", "import sys; from simplicio_loop.daemon.client import main; sys.exit(main(['--version']))"],
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == protocol.EX_UNAVAILABLE
    assert "SIMPLICIO_LOOP_DAEMON=0" in done.stderr and "dir_mode" in done.stderr
    assert done.stdout == ""


# ---- the standalone binary ------------------------------------------------------------------------------


def test_a_frozen_build_has_no_daemon():
    """The binary starts differently (UNVERIFIED with a daemon): it runs in-process, by platform, not by fallback."""
    assert protocol.supported() is True
    sys.frozen = True  # type: ignore[attr-defined]
    try:
        assert protocol.supported() is False
    finally:
        del sys.frozen  # type: ignore[attr-defined]


def test_the_frozen_shim_reaches_the_thin_client_and_runs_in_process(tmp_path):
    """frozen.dispatch resolves `simplicio-loop` through the console scripts of pyproject, which name the client."""
    import tomllib

    scripts = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o777)  # a daemon directory like this one would make the thin client stop with exit 69
    code = ("import sys, json\nsys.frozen = True\nfrom simplicio_loop import frozen\n"
            f"sys.exit(frozen.dispatch(['simplicio-loop', '--version'], scripts=json.loads({json.dumps(scripts)!r})))")
    env = {**os.environ, "SIMPLICIO_LOOP_DAEMON": "1", "SIMPLICIO_LOOP_DAEMON_DIR": str(loose)}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.startswith("simplicio-loop "), done.stderr
    assert list(loose.iterdir()) == []
