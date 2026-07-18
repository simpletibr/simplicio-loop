"""Cross-platform process-liveness primitives (extracted, issue #268).

These two functions used to be private, duplicated-in-place helpers inside
``simplicio_mapper.cli._index_engine`` (the mature, battle-tested index-lock
reclaim logic: ``O_CREAT|O_EXCL`` lock + PID liveness + process-start-identity
to reject PID reuse, see that module's ``_inspect_index_lock``). Issue #268
(``canonical gc``) needs the exact same "provably dead" bar to decide whether
an interrupted canonical-map promotion directory can be safely reclaimed, but
``simplicio_mapper.mapper`` must not import from ``simplicio_mapper.cli``
(the dependency runs the other way: ``cli`` already imports from ``mapper``).

This module is the shared home both call sites import from, so there is a
single implementation instead of two copies drifting apart. No behavior
change versus the previous inline versions in ``_index_engine.py``.
"""

from __future__ import annotations

import os
import subprocess


def process_is_alive(pid: int) -> bool:
    """Return whether ``pid`` currently identifies a live OS process.

    Windows: uses ``OpenProcess``/``GetExitCodeProcess`` via ``ctypes``.
    POSIX: ``os.kill(pid, 0)`` (signal 0 probes existence without sending a
    real signal); ``PermissionError`` still means the process exists (just
    owned by someone else).
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
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
            process = kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                # Access denied still means a process owns the PID.
                return ctypes.get_last_error() == 5
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(process)
        except (AttributeError, OSError):
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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
    return f"ps-start:{value}" if result.returncode == 0 and value else None


__all__ = ["process_is_alive", "process_start_token"]
