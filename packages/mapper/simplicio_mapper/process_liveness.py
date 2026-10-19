"""Cross-platform process-liveness primitives (extracted, issue #268).

These two functions used to be private, duplicated-in-place helpers inside
``simplicio_mapper.cli._index_engine`` (the mature, battle-tested index-lock
reclaim logic: ``O_CREAT|O_EXCL`` lock + PID liveness + process-start-identity
to reject PID reuse, see that module's ``_inspect_index_lock``). Issue #268
(``canonical gc``) needs the exact same "provably dead" bar to decide whether
an interrupted canonical-map promotion directory can be safely reclaimed, but
``simplicio_mapper.mapper`` must not import from ``simplicio_mapper.cli``
(the dependency runs the other way: ``cli`` already imports from ``mapper``).

This module is the shared home every liveness check imports from, so there is a
single implementation instead of copies drifting apart. It sits at the top of the
package, not in ``simplicio_mapper.mapper``, so importing it does not load the
mapper package (about 0.6 s). No behavior change versus the previous inline
versions in ``_index_engine.py``.
"""

from __future__ import annotations

import os
import subprocess

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def process_exists(pid: int) -> bool:
    """Return whether the OS still has a process for ``pid``, zombies included.

    This is the Windows-safe form of ``os.kill(pid, 0)``, the probe that liveness checks used to make directly. On
    Windows that call is TerminateProcess (any signal other than the console events), so it must not be made there.
    Windows: ``OpenProcess``/``GetExitCodeProcess`` via ``ctypes``. POSIX: signal 0 probes existence without sending
    a real signal; ``PermissionError`` still means the process exists (just owned by someone else), and
    ``ProcessLookupError`` means it is gone.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_process_exists(pid: int) -> bool:
    """The Windows answer to ``process_exists``. A probe that cannot run reports the process as present: never a
    fallback to ``os.kill``, which on Windows would terminate the process it was asked about."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            # Access denied still means a process owns the PID.
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                return True
            return exit_code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(process)
    except (AttributeError, OSError):
        return True


def process_is_alive(pid: int) -> bool:
    """Return whether ``pid`` currently identifies a live OS process.

    A process that exists is alive unless it has exited: on Linux its procfs state is ``Z``, and an exited child of
    ours that nobody has reaped is a zombie. Built on ``process_exists``; a Windows answer is final there.
    """
    if not process_exists(pid):
        return False
    if pid == os.getpid() or os.name == "nt":
        return True
    if os.path.exists(f"/proc/{pid}/stat"):
        # POSIX signal 0 also succeeds for a zombie that has not yet been
        # reaped by its parent.  A zombie has finished executing and must not
        # keep Mapper locks or background jobs classified as live.
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                raw = handle.read()
            state = raw[raw.rfind(")") + 2 :].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
    return not _is_unreaped_zombie_child(pid)


def _is_unreaped_zombie_child(pid: int) -> bool:
    """Return whether ``pid`` is our own child that has exited but is not reaped yet.

    ``kill(pid, 0)`` still succeeds for such a zombie, and macOS has no procfs state
    that tells it apart from a live process. ``waitid(WNOWAIT)`` reports the exit
    without consuming the status, so the ``Popen`` that owns the child can still
    collect the real return code. A pid that is not our child raises
    ``ChildProcessError``, which counts as not a zombie child here.
    """
    if not hasattr(os, "waitid"):
        return False
    try:
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except OSError:
        return False


def process_start_token(pid: int) -> str | None:
    """Return an OS process-start identity, used to reject PID reuse.

    Linux: ``/proc/<pid>/stat`` field 22 (starttime). Windows:
    ``GetProcessTimes`` creation time. Fallback for other POSIX platforms:
    ``ps -o lstart=``. Returns ``None`` when no identity could be resolved.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return None
            try:
                created = wintypes.FILETIME()
                exited = wintypes.FILETIME()
                kernel = wintypes.FILETIME()
                user = wintypes.FILETIME()
                ok = kernel32.GetProcessTimes(
                    process,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                )
                if ok:
                    return f"win-filetime:{(created.dwHighDateTime << 32) | created.dwLowDateTime}"
            finally:
                kernel32.CloseHandle(process)
        except (AttributeError, OSError):
            return None
    proc_stat = f"/proc/{pid}/stat"
    try:
        with open(proc_stat, encoding="utf-8") as handle:
            raw = handle.read()
        # Field 22 is starttime; split after the parenthesized comm field.
        fields = raw[raw.rfind(")") + 2 :].split()
        if len(fields) > 19:
            return f"proc-start:{fields[19]}"
    except OSError:
        pass
    return _ps_start_token(pid)


# ``ps`` is a subprocess spawn on every call. A process's own start time is fixed while it
# runs, so it is resolved once per process. Other pids are never cached: a pid can be reused
# after its process exits, and the start token is what detects that reuse.
_own_ps_start_tokens: dict[int, str] = {}


def _ps_start_token(pid: int) -> str | None:
    cacheable = pid == os.getpid()
    if cacheable and pid in _own_ps_start_tokens:
        return _own_ps_start_tokens[pid]
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=1,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    token = f"ps-start:{value}"
    if cacheable:
        _own_ps_start_tokens[pid] = token
    return token


__all__ = ["process_exists", "process_is_alive", "process_start_token"]
