"""The forked child of the daemon: runs one program with the cwd, environment, arguments and stdio of its caller.

The daemon parent never runs program code. Everything below runs in a child that dies after one request, so
nothing a program changes (environment, cwd, ``sys.argv``, module globals, open files) reaches the next one.
"""
from __future__ import annotations

import importlib
import io
import os
import signal
import sys
import time
from typing import Any, Mapping, Sequence

from . import protocol

# The programs a request may name, as console-script entry points. The operators ship in the same wheel as the
# loop; tests/test_daemon_programs.py keeps this table equal to pyproject.toml.
PROGRAMS = {
    "simplicio-loop": "simplicio_loop.cli:main",
    "simplicio-mapper": "simplicio_mapper.cli:main",
    "simplicio-dev-cli": "simplicio.cli:main",
}
# Modules the hot path imports inside its commands; the daemon imports them once so the children inherit them.
PRELOAD = (
    "asyncio", "ctypes", "simplicio_loop.turbo", "simplicio_loop.turbo_cli", "simplicio_loop.turbo_run",
    "simplicio_loop.map_service_mapper", "simplicio_loop.exec_planner", "simplicio_loop.operator_exec",
)


def resolve(spec: str) -> Any:
    module, _, attribute = spec.partition(":")
    return getattr(importlib.import_module(module), attribute)


def _text_stream(fd: int, mode: str, encoding: str, errors: str, unbuffered: bool = False) -> io.TextIOWrapper:
    raw = open(fd, mode + "b", buffering=0 if unbuffered and mode == "w" else -1, closefd=False)
    line_buffered = mode == "w" and (fd == 2 or os.isatty(fd))  # python's own rule for stdout and stderr
    return io.TextIOWrapper(raw, encoding=encoding, errors=errors, line_buffering=line_buffered,
                            write_through=unbuffered and mode == "w")


def _attach_stdio(encodings: Mapping[str, Any], unbuffered: bool = False) -> None:
    """Make ``sys.stdin/stdout/stderr`` fresh wrappers over fds 0, 1 and 2, with the caller's encodings."""
    def enc(name: str) -> tuple[str, str]:
        found = encodings.get(name) or {}
        return str(found.get("encoding") or "utf-8"), str(found.get("errors") or "strict")

    sys.stdin = sys.__stdin__ = _text_stream(0, "r", *enc("stdin"))
    sys.stdout = sys.__stdout__ = _text_stream(1, "w", *enc("stdout"), unbuffered)
    sys.stderr = sys.__stderr__ = _text_stream(2, "w", enc("stderr")[0], "backslashreplace", unbuffered)


SHIELDED = (signal.SIGTERM,)  # blocked from the fork of the child until its program starts


def _raise_interrupt(signum: int, frame: Any) -> None:
    """SIGTERM, the hang-up of the caller, reaches the command as Ctrl-C does in a process: ``finally`` and
    ``atexit`` run. A command that ignores it is killed after the grace period."""
    raise KeyboardInterrupt


def _die_with_the_daemon(parent: int) -> None:
    """Linux: the kernel kills this process when the daemon dies, so a command never outlives its daemon and a
    retry in-process cannot meet a second writer. Elsewhere only the check below applies (UNVERIFIED on macOS)."""
    if sys.platform.startswith("linux"):
        import ctypes

        if ctypes.CDLL(None, use_errno=True).prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), "cannot ask the kernel to stop this command with its daemon")
    if os.getppid() != parent:
        raise RuntimeError("the daemon is gone")  # it died between the fork and the request above


def apply_process(proc: Mapping[str, Any]) -> None:
    """Give this command the priority, limits and cpus of its caller. What the system refuses (an unprivileged
    daemon cannot give more priority or higher limits than it started with) is said on stderr, never hidden."""
    import resource

    refused: list[str] = []

    def attempt(what: str, action: Any, *arguments: Any) -> None:
        try:
            action(*arguments)
        except (OSError, ValueError, OverflowError) as error:
            refused.append(f"{what} ({error})")

    if "nice" in proc:
        attempt(f"nice {proc['nice']}", os.setpriority, os.PRIO_PROCESS, 0, proc["nice"])
    for name, limits in proc.get("rlimits", {}).items():
        attempt(f"{name} limit {limits[0]}/{limits[1]}", resource.setrlimit, getattr(resource, "RLIMIT_" + name), tuple(limits))
    if proc.get("cpus"):
        attempt(f"cpus {proc['cpus']}", os.sched_setaffinity, 0, proc["cpus"])
    if refused:
        print("simplicio-loop: daemon: this command runs with the daemon's own priority, limits and cpus, not its "
              f"caller's: the system refused {', '.join(refused)}; run `simplicio-loop daemon stop` and start the "
              "next command from the shell that should set them", file=sys.stderr)


def _exit_code(value: Any) -> int:
    """What ``sys.exit(value)`` would leave as the exit code of a process."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value & 0xFF
    print(value, file=sys.stderr)
    return 1


def _call(entry: Any) -> int:
    import traceback

    try:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, SHIELDED)  # a SIGTERM that came during the start-up arrives now
        return _exit_code(entry())
    except SystemExit as stop:
        return _exit_code(stop.code)
    except KeyboardInterrupt:
        return 130
    except BaseException:  # noqa: BLE001 - a program crash is reported like python reports it
        traceback.print_exc()
        return 1


def _finish(code: int) -> None:
    """What the interpreter does at exit, then leave without running the daemon's own unwinding."""
    import atexit
    import threading

    for step in (atexit._run_exitfuncs, getattr(threading, "_shutdown", lambda: None)):
        try:
            step()
        except BaseException:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


def serve_request(request: Mapping[str, Any], fds: Sequence[int], entry: Any, run_dir: str, key: str,
                  parent: int) -> None:
    """Run in the child, right after the fork; ``parent`` is the pid of the daemon. Never returns."""
    code = 70  # EX_SOFTWARE: the child failed before the program ran
    try:
        os.setsid()  # its own process group: a hang-up kills the program and what it started, never the daemon
        _die_with_the_daemon(parent)
        signal.set_wakeup_fd(-1)  # the daemon's loop wrote to it
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, _raise_interrupt)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        for target, source in enumerate(fds):
            os.dup2(source, target)
        os.closerange(3, 1 << 16)
        os.environ.clear()
        os.environ.update(request["env"])
        os.environ[protocol.NESTED_ENV] = "1"
        time.tzset()
        os.umask(int(request.get("umask", 0o022)))
        _attach_stdio(request.get("enc") or {}, bool(request["env"].get("PYTHONUNBUFFERED")))
        apply_process(request.get("proc") or {})
        sys.argv = [request["program"], *request["argv"]]
        protocol.CURRENT = protocol.Current(run_dir, key)
        import asyncio

        asyncio.events._set_running_loop(None)  # the daemon's loop was running when it forked
        try:
            os.chdir(request["cwd"])
        except OSError as error:
            print(f"{request['program']}: cannot use the working directory {request['cwd']}: {error.strerror}",
                  file=sys.stderr)
            code = 1
        else:
            if request["env"].get("SIMPLICIO_CORE_NO_NETWORK") == "1":
                from ..core_network_guard import install

                install()
            code = _call(entry)
    except BaseException:  # noqa: BLE001
        try:
            import traceback

            traceback.print_exc()
        except BaseException:  # noqa: BLE001
            pass
    _finish(code)
