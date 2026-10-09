"""Shared helpers of the daemon tests: test programs the daemon can run, and a launcher for a test daemon.

The test programs are plain ``main()`` functions that read ``sys.argv`` like a console script.
Run this file as a script to serve a test daemon: ``python daemon_helpers.py serve <run_dir>``.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

COUNTER = 0  # module state that must never leak from one request to the next


def state() -> int:
    """Print what this request sees, then dirty the process-wide state."""
    global COUNTER
    seen = {
        "cwd": os.getcwd(), "argv": sys.argv, "pid": os.getpid(), "counter": COUNTER,
        "var": os.environ.get("REQ_VAR"), "leak": os.environ.get("LEAK"),
        "daemon_only": os.environ.get("DAEMON_ONLY"), "has_path": "PATH" in os.environ,
    }
    print(json.dumps(seen))
    if os.environ.get("HOLD_S"):
        time.sleep(float(os.environ["HOLD_S"]))
        seen["woke"] = time.time()
    os.environ["LEAK"] = "leaked"
    os.environ["REQ_VAR"] = "mutated"
    COUNTER += 1
    sys.argv.append("dirty")
    os.chdir("/")
    return 0


def exit_with() -> int:
    print("to stdout")
    print("to stderr", file=sys.stderr)
    return int(sys.argv[1])


def exit_text() -> int:
    raise SystemExit("goodbye")


def boom() -> int:
    raise RuntimeError("kaboom")


def sleeper() -> int:
    """argv: <file> <seconds>. Records start and end times in the file, one JSON line each."""
    path, seconds = sys.argv[1], float(sys.argv[2])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "start", "pid": os.getpid(), "t": time.time()}) + "\n")
    time.sleep(seconds)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "end", "pid": os.getpid(), "t": time.time()}) + "\n")
    return 0


def upper() -> int:
    sys.stdout.write(sys.stdin.read().upper())
    return 0


def no_read() -> int:
    print("did not read stdin")
    return 0


def aio() -> int:
    async def work() -> int:
        await asyncio.sleep(0.01)
        return 7
    print(asyncio.run(work()))
    return 0


def killed_by_signal() -> int:
    import signal
    os.kill(os.getpid(), signal.SIGKILL)
    return 0


def tty_info() -> int:
    print(json.dumps({"in": sys.stdin.isatty(), "out": sys.stdout.isatty(), "enc": sys.stdout.encoding}))
    return 0


def nested() -> int:
    """Ask the daemon for another program from inside this command, as the loop does for Mapper and dev-cli."""
    from simplicio_loop.daemon import client, protocol

    here = protocol.CURRENT
    code, out, _err = client.run_captured("no-read", [], run_dir=here.run_dir, key=here.key, timeout=20)
    sys.stdout.write(out.decode())
    return code


PROGRAMS = {
    "nested": "daemon_helpers:nested",
    "state": "daemon_helpers:state", "exit-with": "daemon_helpers:exit_with", "exit-text": "daemon_helpers:exit_text",
    "boom": "daemon_helpers:boom", "sleeper": "daemon_helpers:sleeper", "upper": "daemon_helpers:upper",
    "no-read": "daemon_helpers:no_read", "aio": "daemon_helpers:aio", "killed": "daemon_helpers:killed_by_signal",
    "tty-info": "daemon_helpers:tty_info",
}


def serve(run_dir: str) -> int:
    """Serve a test daemon. Options come from the environment so a test can vary them."""
    from simplicio_loop.daemon.server import Daemon

    env = os.environ
    allowed_uid = int(env["DAEMON_TEST_ALLOWED_UID"]) if env.get("DAEMON_TEST_ALLOWED_UID") else None
    roots = [r for r in env.get("DAEMON_TEST_ROOTS", "").split(os.pathsep) if r]
    daemon = Daemon(
        run_dir, key=env.get("DAEMON_TEST_KEY", "testkey"), programs=PROGRAMS,
        roots=roots, idle_s=float(env.get("DAEMON_TEST_IDLE", "60")),
        max_children=int(env.get("DAEMON_TEST_MAX_CHILDREN", "4")),
        max_waiting=int(env.get("DAEMON_TEST_MAX_WAITING", "16")),
        allowed_uid=allowed_uid, preload=(),
    )
    return asyncio.run(daemon.serve())


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        sys.exit(serve(sys.argv[2]))
