"""Run an operator (Mapper, dev-cli) from inside a command.

Inside a command the daemon runs, the operator is forked from the daemon's already-imported modules instead of
starting a new interpreter: about 0.6 s less per call (issue #1590). Anywhere else it is a normal subprocess.
The operator must belong to the environment of the loop (the console script next to its interpreter): a
foreign one on PATH is a different program and is started as before.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sysconfig
from typing import Optional, Sequence

from .daemon import protocol

WARM = {"simplicio-mapper": "simplicio-mapper", "simplicio-dev-cli": "simplicio-dev-cli",
        "simplicio-cli": "simplicio-dev-cli", "simplicio-py": "simplicio-dev-cli"}


def warm_name(binary: str) -> Optional[str]:
    """The daemon program that stands for ``binary``, or None when it must be started as a process."""
    if protocol.CURRENT is None:
        return None
    name = WARM.get(os.path.basename(binary))
    if name is None:
        return None
    here = os.path.realpath(sysconfig.get_path("scripts"))
    return name if os.path.dirname(os.path.realpath(binary)) == here else None


async def run(argv: Sequence[str], *, timeout: float, cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Run ``argv`` with no stdin; return (exit code, stdout, stderr). A timeout kills the whole process group
    and raises ``subprocess.TimeoutExpired``."""
    name = warm_name(argv[0])
    if name is not None:
        from .daemon import client

        current = protocol.CURRENT
        try:
            code, out, err = await asyncio.to_thread(
                client.run_captured, name, list(argv[1:]), run_dir=current.run_dir, key=current.key,
                cwd=cwd or os.getcwd(), env=dict(os.environ), timeout=timeout)
        except protocol.DaemonError as error:
            # The code under the daemon changed while this command runs (an update, a checkout): the daemon of the
            # command left. Failing the whole command for that would be worse than the process this call always was.
            if error.code not in ("stale", "not_running"):
                raise
        else:
            return code, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
    from .exec_planner import _kill_process_tree

    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)
        raise subprocess.TimeoutExpired(list(argv), timeout) from None
    except BaseException:
        await _kill_process_tree(proc)
        raise
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
