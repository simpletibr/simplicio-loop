"""Process groups for the children this loop starts and must be able to stop together with everything they started.

A child started with ``start_new_session`` (POSIX ``setsid``) leads a process group whose id is its own pid. That id keeps
naming the group while any member lives, even after the leader was reaped, so the group is signalled by the leader's pid.
``getpgid`` is never used: it fails once the leader is gone, which is exactly when a helper that still holds the leader's
pipes is running.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

POSIX = os.name != "nt"


def session_kwargs() -> dict[str, bool]:
    """Spawn kwargs that make the child the leader of its own session and process group (POSIX; Windows ignores it)."""
    return {"start_new_session": POSIX}


def kill_group(leader_pid: int, sig: int = signal.SIGKILL) -> bool:
    """Send ``sig`` to every member of the group ``leader_pid`` leads. False when there was no group to signal."""
    if not POSIX:
        return False
    try:
        os.killpg(leader_pid, sig)
    except OSError:  # ESRCH: no member is left; EPERM: a member we may not signal, which this cannot change
        return False
    return True


def kill_tree(proc) -> None:
    """SIGKILL the group ``proc`` leads, then ``proc`` itself: the second signal covers a child the group signal missed."""
    kill_group(proc.pid)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


def group_alive(pgid: int) -> bool:
    """Whether any member of group ``pgid`` still exists. EPERM means members exist that we may not signal: alive."""
    if not POSIX:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def reap(proc, timeout: float) -> bool:
    """Wait at most ``timeout`` seconds for asyncio to report ``proc`` finished. False when it did not."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except TimeoutError:
        return False
    return True
