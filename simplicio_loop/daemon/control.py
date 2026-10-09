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
                    max_children=int(_number("SIMPLICIO_LOOP_DAEMON_MAX_CHILDREN", 0)) or None)
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
