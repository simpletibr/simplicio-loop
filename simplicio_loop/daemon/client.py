"""The thin client: ``simplicio-loop`` as the console script runs it.

It sends the command to the daemon and exits with the daemon's answer. Standard library only, and nothing
heavy at import: this is the code every command pays for. Without a running daemon it starts one and waits for
its socket, or stops with a clear error. It never runs the command in-process by itself; that is the explicit
opt-out ``SIMPLICIO_LOOP_DAEMON=0`` (and the platforms that have no daemon).
"""
from __future__ import annotations

import os
import socket
import stat
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Mapping, Optional, Sequence

from . import protocol
from .protocol import DaemonError

START_WAIT_S = 30.0
# What a started daemon gets from the environment of the first caller. Each command brings its own environment.
DAEMON_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TZ", "TMPDIR", "PYTHONPATH", "PYTHONHOME", "PYTHONUTF8",
              "VIRTUAL_ENV", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "SIMPLICIO_CORE_NO_NETWORK",
              "SIMPLICIO_LOOP_DAEMON_DIR", "SIMPLICIO_LOOP_DAEMON_IDLE_S", "SIMPLICIO_LOOP_DAEMON_MAX_CHILDREN")


def _daemon_env(environ: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in environ.items() if k in DAEMON_ENV or k.startswith("LC_")}


def _connect(where: protocol.Paths) -> socket.socket:
    try:
        info = os.lstat(where.sock)
    except FileNotFoundError:
        raise DaemonError("not_running", "no daemon is running") from None
    if not stat.S_ISSOCK(info.st_mode):
        raise DaemonError("socket_type", f"{where.sock} is not a socket")
    if info.st_uid != os.geteuid():
        raise DaemonError("socket_owner", f"{where.sock} belongs to another user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise DaemonError("socket_mode", f"{where.sock} is open to group or others; remove it")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(os.fspath(where.sock))
    except (ConnectionRefusedError, FileNotFoundError):
        sock.close()
        raise DaemonError("not_running", "no daemon is running") from None
    return sock


def _log_tail(where: protocol.Paths) -> str:
    try:
        with open(where.log, encoding="utf-8", errors="replace") as handle:
            return handle.read()[-400:].strip()
    except OSError:
        return ""


def _start(where: protocol.Paths, directory: str, command: Optional[Sequence[str]], environ: Mapping[str, str],
           wait_s: float) -> socket.socket:
    """Start the daemon in its own session, then wait until its socket answers."""
    import subprocess

    log = os.open(where.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        process = subprocess.Popen(
            list(command or [sys.executable, "-P", "-m", "simplicio_loop.daemon", "serve"]),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=directory, env=_daemon_env(environ),
            start_new_session=True, close_fds=True)
    finally:
        os.close(log)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return _connect(where)
        except DaemonError as error:
            if error.code != "not_running":
                raise
        code = process.poll()
        if code not in (None, 0):  # 0 is a daemon that lost the start race to another one: its socket comes soon
            raise DaemonError("start_failed", f"the daemon exited with code {code} ({_log_tail(where)}); "
                                              f"see {where.log}; or {protocol.OPT_OUT_HINT}")
        if time.monotonic() > deadline:
            raise DaemonError("start_timeout", f"the daemon did not answer in {wait_s:g}s; see {where.log}; "
                                               f"or {protocol.OPT_OUT_HINT}")
        time.sleep(0.02)


def _where(run_dir: os.PathLike[str] | str | None, key: Optional[str], create: bool = True) -> tuple[str, protocol.Paths]:
    directory = protocol.secure_dir(run_dir, create) if run_dir else protocol.run_dir()
    return directory, protocol.paths(directory, key or protocol.daemon_key())


def _stdio(stdio: Sequence[int]) -> list[int]:
    """The three descriptors to hand over; a closed one becomes /dev/null."""
    fds = []
    for number, fd in enumerate(stdio):
        try:
            os.fstat(fd)
            fds.append(fd)
        except OSError:
            fds.append(os.open(os.devnull, os.O_RDONLY if number == 0 else os.O_WRONLY))
    return fds


def _encoding(stream: object) -> dict[str, str]:
    return {"encoding": getattr(stream, "encoding", None) or "utf-8", "errors": getattr(stream, "errors", None) or "strict"}


def open_exec(program: str, args: Sequence[str], *, run_dir: os.PathLike[str] | str | None = None,
              key: Optional[str] = None, cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
              stdio: Sequence[int] = (0, 1, 2), autostart: bool = True, start_command: Optional[Sequence[str]] = None,
              wait_s: float = START_WAIT_S) -> socket.socket:
    """Ask the daemon to run ``program``; return the connection once the program has started.

    The answer ``{"exit": code}`` arrives on it later (``wait_exit``); closing it stops the program.
    Raises DaemonError for everything that stops the request: no daemon, a stale one, a full queue, a bad socket.
    """
    environ = dict(os.environ if env is None else env)
    for attempt in (0, 1):
        directory, where = _where(run_dir, key)
        try:
            sock = _connect(where)
        except DaemonError as error:
            if error.code != "not_running" or not autostart:
                raise
            sock = _start(where, directory, start_command, environ, wait_s)
        previous = os.umask(0)
        os.umask(previous)
        request = {
            "op": "exec", "proto": protocol.PROTOCOL, "program": program, "argv": list(args),
            "nested": environ.get(protocol.NESTED_ENV) == "1",
            "cwd": cwd if cwd is not None else os.getcwd(), "env": environ, "umask": previous,
            "enc": {"stdin": _encoding(sys.stdin), "stdout": _encoding(sys.stdout), "stderr": _encoding(sys.stderr)},
        }
        try:
            protocol.send_request(sock, request, _stdio(stdio))
            reply = protocol.read_message(sock, bytearray())
        except OSError as error:
            sock.close()
            raise DaemonError("lost", f"the connection to the daemon failed: {error}") from None
        if reply is not None and reply.get("ok"):
            return sock
        sock.close()
        if reply is None:
            raise DaemonError("lost", "the daemon closed the connection without an answer")
        error = DaemonError(str(reply.get("error", "internal")), str(reply.get("message", "")))
        if error.code == "stale" and autostart and attempt == 0:
            _wait_gone(where, wait_s)  # the old daemon freed the key; the next attempt starts the new one
            continue
        raise error
    raise AssertionError("unreachable")


def _wait_gone(where: protocol.Paths, wait_s: float) -> None:
    deadline = time.monotonic() + wait_s
    while os.path.exists(where.sock) and time.monotonic() < deadline:
        time.sleep(0.02)


def wait_exit(sock: socket.socket) -> int:
    """The exit code the daemon reports. Ctrl-C hangs up, which stops the program, and exits 130."""
    buffer = bytearray()
    try:
        while True:
            reply = protocol.read_message(sock, buffer)
            if reply is None:
                raise DaemonError("lost", "the daemon closed the connection before the program ended")
            if "exit" in reply:
                return int(reply["exit"])
    except KeyboardInterrupt:
        return 130
    finally:
        sock.close()


def exec_program(program: str, args: Sequence[str], **options) -> int:
    """Run ``program`` through the daemon on the given stdio and return its exit code."""
    return wait_exit(open_exec(program, args, **options))


def run_captured(program: str, args: Sequence[str], *, run_dir: os.PathLike[str] | str, key: str,
                 cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
                 timeout: Optional[float] = None) -> tuple[int, bytes, bytes]:
    """Run ``program`` through the daemon with no stdin and return (exit code, stdout, stderr)."""
    import selectors
    import subprocess

    devnull = os.open(os.devnull, os.O_RDONLY)
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    try:
        sock = open_exec(program, args, run_dir=run_dir, key=key, cwd=cwd, env=env, stdio=(devnull, out_w, err_w),
                         autostart=False)
    except BaseException:
        os.close(out_r)
        os.close(err_r)
        raise
    finally:
        for fd in (devnull, out_w, err_w):
            os.close(fd)
    deadline = None if timeout is None else time.monotonic() + timeout
    chunks: dict[int, bytearray] = {out_r: bytearray(), err_r: bytearray()}
    code: Optional[int] = None
    buffer = bytearray()
    selector = selectors.DefaultSelector()
    for source in (out_r, err_r, sock):
        selector.register(source, selectors.EVENT_READ)
    try:
        while code is None or any(k.fileobj is not sock for k in selector.get_map().values()):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired([program, *args], timeout)
            for found, _ in selector.select(remaining):
                source = found.fileobj
                if source is sock:
                    reply = protocol.read_message(sock, buffer)
                    if reply is None:
                        raise DaemonError("lost", "the daemon closed the connection before the program ended")
                    if "exit" in reply:
                        code = int(reply["exit"])
                        selector.unregister(sock)
                else:
                    data = os.read(source, 65536)
                    if data:
                        chunks[source] += data
                    else:
                        selector.unregister(source)
        return code if code is not None else 1, bytes(chunks[out_r]), bytes(chunks[err_r])
    finally:
        selector.close()
        sock.close()  # a program still running is stopped by the hang-up
        os.close(out_r)
        os.close(err_r)


def _roundtrip(operation: str, run_dir, key) -> dict:
    try:
        _, where = _where(run_dir, key, create=False)
    except DaemonError as error:
        if error.code == "dir_missing":
            raise DaemonError("not_running", "no daemon is running") from None
        raise
    sock = _connect(where)
    try:
        protocol.send_request(sock, {"op": operation, "proto": protocol.PROTOCOL})
        reply = protocol.read_message(sock, bytearray())
    finally:
        sock.close()
    if reply is None or not reply.get("ok"):
        raise DaemonError(str((reply or {}).get("error", "lost")), str((reply or {}).get("message", "")))
    return reply


def status(*, run_dir=None, key: Optional[str] = None) -> dict:
    """The daemon's status. Raises DaemonError('not_running') when there is none."""
    reply = _roundtrip("status", run_dir, key)
    reply.pop("ok", None)
    return reply


def stop(*, run_dir=None, key: Optional[str] = None) -> bool:
    """Ask the daemon to stop. False when none was running."""
    try:
        _roundtrip("stop", run_dir, key)
    except DaemonError as error:
        if error.code == "not_running":
            return False
        raise
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The ``simplicio-loop`` console script."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get(protocol.OPT_OUT_ENV) == "0" or not protocol.supported():
        from .. import cli

        return cli.main(arguments)
    if arguments[:1] == ["daemon"]:
        from .control import main as control

        return control(arguments[1:])
    try:
        return exec_program("simplicio-loop", arguments)
    except DaemonError as error:
        print(f"simplicio-loop: daemon: {error} [{error.code}]; {protocol.OPT_OUT_HINT}", file=sys.stderr)
        return protocol.EX_UNAVAILABLE
