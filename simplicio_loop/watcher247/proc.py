"""The single subprocess entry point of the watcher.

Every gh, git and simplicio-loop call goes through run(); tests replace
proc.run with a fake that answers by argv.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


async def run(argv: list[str], timeout: float = 120, cwd: Path | None = None,
              env: Mapping[str, str] | None = None, stdin: str | None = None) -> Result:
    """Run argv, return its output. On timeout (or cancellation) kill the whole process group."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,  # None inherits the service env
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(None if stdin is None else stdin.encode()), timeout=timeout)
    except asyncio.TimeoutError as exc:
        _kill_group(proc)
        await proc.wait()
        raise TimeoutError(f"{argv[0]} timed out after {timeout}s") from exc
    except BaseException:
        _kill_group(proc)
        await proc.wait()
        raise
    return Result(
        proc.returncode if proc.returncode is not None else -1,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )
