"""``simplicio-loop daemon serve|status|stop``: run and manage the daemon."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Optional, Sequence

from . import client, protocol

USAGE = "usage: simplicio-loop daemon serve|status|stop"


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise protocol.DaemonError("bad_option", f"{name} must be a number, not {raw!r}") from None


def serve() -> int:
    """Run the daemon in the foreground. Its output goes to the log file next to the socket."""
    from . import server
    from .server import Daemon

    directory = protocol.run_dir()
    key = protocol.daemon_key()
    where = protocol.paths(directory, key)
    log = os.open(where.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    os.dup2(log, 1)
    os.dup2(log, 2)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.close(log)
    daemon = Daemon(directory, key=key, idle_s=_number("SIMPLICIO_LOOP_DAEMON_IDLE_S", 900.0),
                    max_children=int(_number("SIMPLICIO_LOOP_DAEMON_MAX_CHILDREN", 0)) or None,
                    max_wait_s=_number("SIMPLICIO_LOOP_DAEMON_WAIT_S", server.MAX_WAIT_S))
    return asyncio.run(daemon.serve())


def main(arguments: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    command = arguments[0] if arguments else ""
    try:
        if command == "serve":
            return serve()
        if command == "status":
            try:
                print(json.dumps(client.status(), indent=2, sort_keys=True))
            except protocol.DaemonError as error:
                if error.code != "not_running":
                    raise
                print(json.dumps({"running": False}))
                return 3
            return 0
        if command == "stop":
            print("stopped" if client.stop() else "not running")
            return 0
    except protocol.DaemonError as error:
        print(f"simplicio-loop daemon: {error} [{error.code}]", file=sys.stderr)
        return protocol.EX_UNAVAILABLE
    print(USAGE, file=sys.stderr)
    return 2


DAEMON_VERBS = ("serve", "status", "stop")
DAEMON_NOT_USED = "simplicio-loop: the daemon is not used on this platform (Windows); commands run in this process"


def daemon_command(arguments: Sequence[str]) -> int:
    """``simplicio-loop daemon serve|status|stop`` when ``cli.main`` gets the verb (issue #1633).

    Windows has no daemon client, so the verb reaches ``cli.main``, and the parser would take ``daemon status`` for
    the prose of a task and survey the current directory. Where the platform has a daemon (``SIMPLICIO_LOOP_DAEMON=0``
    also lands here) the verb goes to ``main``. Elsewhere one line says that no daemon runs: ``status`` exits 3 (not
    running), ``stop`` 0 (nothing to stop) and ``serve`` 69 (it cannot serve). Any other verb is refused with the valid ones.
    """
    verb = arguments[0] if arguments else ""
    if verb not in DAEMON_VERBS:
        print(f"usage: simplicio-loop daemon {'|'.join(DAEMON_VERBS)}", file=sys.stderr)
        return 2
    if protocol.supported():
        return main(list(arguments))
    print(DAEMON_NOT_USED, file=sys.stderr if verb == "serve" else sys.stdout)
    return {"status": 3, "stop": 0}.get(verb, protocol.EX_UNAVAILABLE)
