"""task_operator.py — monitored execution of shelled-out provider subprocesses.

Issue #210: `simplicio.providers._shell_out` used to make a single blocking
``subprocess.run(cmd, timeout=600)`` call. That gives no heartbeat while the
child is alive, cannot distinguish "the child never produced a byte of
output" (provider failed to start / stuck on login / network) from "the
child is actively running past the deadline", cannot be cancelled from the
outside, and — on timeout — only kills the direct child, leaving any
grandchild process (a shell, a nested tool call) orphaned.

:func:`run_bounded_subprocess` replaces that single call. It:

- spawns the child in its own process group/session so the whole descendant
  tree can be killed at once (POSIX: ``os.killpg``; Windows: ``taskkill
  /T /F``, falling back to ``Popen.kill()``);
- emits a heartbeat via :func:`simplicio.observability.emit_event` every
  ``heartbeat_interval`` seconds while the child is alive;
- emits a separate long-running-process review event after 30 minutes by
  default, including the child PID, without stopping useful work;
- supports opt-in startup/total deadlines for callers that explicitly need a
  cancellation policy;
- supports cooperative cancellation via an optional ``threading.Event``;
- returns a structured :class:`BoundedRunResult` instead of raising, so
  callers keep full control over how a stall is reported.

This module has no dependency on any specific provider CLI — it operates on
an arbitrary ``cmd`` list, exactly like ``subprocess.run`` would.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Configuration. Commands run without a deadline by default. A caller may opt
# into a deadline through the existing environment variables, while the normal
# path emits a review receipt after thirty minutes instead of killing work.
# --------------------------------------------------------------------------- #

DEFAULT_STARTUP_TIMEOUT_S: float | None = None
DEFAULT_TOTAL_TIMEOUT_S: float | None = None
DEFAULT_LONG_RUNNING_REVIEW_S = 30.0 * 60.0
DEFAULT_HEARTBEAT_INTERVAL_S = 15.0
_POLL_INTERVAL_S = 0.2

PHASE_COMPLETED = "completed"
PHASE_STARTUP_TIMEOUT = "startup_timeout"
PHASE_TOTAL_TIMEOUT = "total_timeout"
PHASE_CANCELLED = "cancelled"
PHASE_FAILED = "failed"

_RECOVERY_HINTS = {
    PHASE_STARTUP_TIMEOUT: (
        "No provider output arrived before the startup deadline "
        "(SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S). Check that the CLI is "
        "logged in and reachable, then retry."
    ),
    PHASE_TOTAL_TIMEOUT: (
        "The provider produced output but ran past the total deadline "
        "(SIMPLICIO_PROVIDER_TOTAL_TIMEOUT_S). Narrow the task scope or "
        "raise the deadline, then retry."
    ),
    PHASE_CANCELLED: "The task was cancelled; no automatic retry was attempted.",
}


def startup_timeout_s() -> float | None:
    return _optional_timeout_s("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S")


def total_timeout_s() -> float | None:
    return _optional_timeout_s("SIMPLICIO_PROVIDER_TOTAL_TIMEOUT_S")


def long_running_review_s() -> float:
    return _env_float("SIMPLICIO_PROVIDER_LONG_RUNNING_REVIEW_S", DEFAULT_LONG_RUNNING_REVIEW_S)


def heartbeat_interval_s() -> float:
    return _env_float("SIMPLICIO_PROVIDER_HEARTBEAT_INTERVAL_S", DEFAULT_HEARTBEAT_INTERVAL_S)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_timeout_s(name: str) -> float | None:
    raw = os.environ.get(name, "").strip().lower()
    if not raw or raw in {"0", "off", "none", "unlimited"}:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass
class BoundedRunResult:
    """Structured outcome of :func:`run_bounded_subprocess`."""

    phase: str
    elapsed_s: float
    returncode: int | None
    stdout: str
    stderr: str
    recovery: str
    label: str = ""
    cmd: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.phase == PHASE_COMPLETED and self.returncode == 0


def _popen_kwargs_for_new_process_group() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _windows_descendant_pids(root_pid: int) -> list[int]:
    """Return descendants of *root_pid*, deepest first, when Windows exposes them.

    ``taskkill /T`` normally walks this tree itself.  Taking a snapshot first
    closes the small race where the direct parent exits while ``taskkill`` is
    being scheduled and its child is then re-parented before the tree walk.
    The helper is best effort: ``taskkill`` and the direct ``Popen.kill``
    fallback remain available when the Windows API cannot be read.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _ProcessEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if snapshot == invalid_handle:
            return []
        try:
            entry = _ProcessEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            parents: dict[int, int] = {}
            if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
            descendants: list[int] = []
            pending = [root_pid]
            while pending:
                parent = pending.pop()
                children = [pid for pid, candidate_parent in parents.items() if candidate_parent == parent]
                descendants.extend(children)
                pending.extend(children)
            return list(reversed(descendants))
        finally:
            kernel32.CloseHandle(snapshot)
    except (AttributeError, OSError):
        return []


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill *proc* and every descendant it spawned.

    POSIX: the child was started in its own session (``start_new_session=
    True``), so its process group id equals its pid; ``os.killpg`` reaches
    every descendant in one call.

    Windows: the child was started with ``CREATE_NEW_PROCESS_GROUP``. A
    pre-kill Toolhelp snapshot lets us address descendants directly before
    asking ``taskkill`` to terminate the root tree. If ``taskkill`` is
    unavailable for any reason, fall back to killing only the direct child
    (still better than leaking the whole call).
    """
    if os.name == "nt":
        taskkill_succeeded = False
        try:
            # Descendant-first termination survives a parent that exits and
            # is re-parented while Windows schedules the root /T traversal.
            for pid in [*_windows_descendant_pids(proc.pid), proc.pid]:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
                taskkill_succeeded = taskkill_succeeded or result.returncode == 0
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
        if taskkill_succeeded:
            return
        try:
            proc.kill()
        except OSError:
            pass
        return

    try:
        # getpgid/killpg/SIGKILL are POSIX-only; this branch only runs when
        # os.name != "nt" (checked above), but typeshed's Windows-flavored
        # `os`/`signal` stubs still don't expose them, hence the ignores and
        # the getattr fallback (SIGTERM exists everywhere `signal` does).
        pgid = os.getpgid(proc.pid)  # type: ignore[attr-defined]
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        os.killpg(pgid, sigkill)  # type: ignore[attr-defined]
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _stream_reader(stream, chunks: list[str], first_output_event: threading.Event) -> None:
    try:
        while True:
            # ``read(4096)`` may wait for a full buffer on Windows pipes even
            # after a flushed line is available. Reading a line makes startup
            # and long-running-process observations reflect real output as it
            # arrives instead of only after the child exits.
            readline = getattr(stream, "readline", None)
            data = readline() if callable(readline) else stream.read(1)
            if not data:
                break
            chunks.append(data)
            first_output_event.set()
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _stdin_writer(stream, text: str) -> None:
    try:
        stream.write(text)
    except (OSError, ValueError, BrokenPipeError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_bounded_subprocess(
    cmd: list[str],
    *,
    label: str,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
    cwd: str | None = None,
    startup_timeout: float | None = None,
    total_timeout: float | None = None,
    long_running_review_after: float | None = None,
    heartbeat_interval: float | None = None,
    cancel_event: threading.Event | None = None,
    root: str | None = None,
) -> BoundedRunResult:
    """Run *cmd* to completion while keeping its process observable.

    Never raises for "the child stalled" or "the child exited non-zero" —
    those are reported as a :class:`BoundedRunResult` with the appropriate
    ``phase``. It only raises for a genuinely unexpected local error (e.g.
    the OS refusing to spawn a thread), mirroring how ``subprocess.Popen``
    itself only raises for setup failures, not for the child's own exit
    status.
    """
    from .observability import emit_event

    startup_timeout = startup_timeout_s() if startup_timeout is None else startup_timeout
    total_timeout = total_timeout_s() if total_timeout is None else total_timeout
    long_running_review_after = (
        long_running_review_s() if long_running_review_after is None else long_running_review_after
    )
    heartbeat_interval = heartbeat_interval_s() if heartbeat_interval is None else heartbeat_interval

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=cwd,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs_for_new_process_group(),
        )
    except FileNotFoundError:
        return BoundedRunResult(
            phase=PHASE_FAILED,
            elapsed_s=0.0,
            returncode=None,
            stdout="",
            stderr=f"`{cmd[0]}` CLI not on PATH.",
            recovery=f"Install {label} first, then re-run.",
            label=label,
            cmd=cmd,
        )

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    first_output_event = threading.Event()

    threads = [
        threading.Thread(
            target=_stream_reader, args=(proc.stdout, stdout_chunks, first_output_event), daemon=True
        ),
        threading.Thread(
            target=_stream_reader, args=(proc.stderr, stderr_chunks, first_output_event), daemon=True
        ),
    ]
    if stdin_text is not None and proc.stdin is not None:
        threads.append(threading.Thread(target=_stdin_writer, args=(proc.stdin, stdin_text), daemon=True))
    for thread in threads:
        thread.start()

    phase = PHASE_COMPLETED
    last_heartbeat = start
    long_running_reported = False
    returncode: int | None = None
    while True:
        returncode = proc.poll()
        if returncode is not None:
            break
        now = time.monotonic()
        elapsed = now - start
        if cancel_event is not None and cancel_event.is_set():
            phase = PHASE_CANCELLED
            break
        if startup_timeout is not None and not first_output_event.is_set() and elapsed >= startup_timeout:
            phase = PHASE_STARTUP_TIMEOUT
            break
        if total_timeout is not None and elapsed >= total_timeout:
            phase = PHASE_TOTAL_TIMEOUT
            break
        if not long_running_reported and elapsed >= long_running_review_after:
            emit_event(
                "provider_long_running",
                {
                    "label": label,
                    "pid": proc.pid,
                    "elapsed_s": round(elapsed, 2),
                    "review_after_s": long_running_review_after,
                    "first_output_seen": first_output_event.is_set(),
                },
                level="warning",
                root=root,
            )
            long_running_reported = True
        if now - last_heartbeat >= heartbeat_interval:
            emit_event(
                "provider_heartbeat",
                {
                    "label": label,
                    "elapsed_s": round(elapsed, 2),
                    "first_output_seen": first_output_event.is_set(),
                },
                root=root,
            )
            last_heartbeat = now
        time.sleep(_POLL_INTERVAL_S)

    elapsed = time.monotonic() - start

    if phase != PHASE_COMPLETED:
        kill_process_tree(proc)
        for thread in threads:
            thread.join(timeout=5)
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        emit_event(
            f"provider_{phase}",
            {"label": label, "elapsed_s": round(elapsed, 2)},
            level="warning",
            root=root,
        )
        return BoundedRunResult(
            phase=phase,
            elapsed_s=elapsed,
            returncode=proc.poll(),
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            recovery=_RECOVERY_HINTS[phase],
            label=label,
            cmd=cmd,
        )

    for thread in threads:
        thread.join(timeout=5)

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    if returncode != 0:
        return BoundedRunResult(
            phase=PHASE_FAILED,
            elapsed_s=elapsed,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            recovery="Non-zero exit; inspect stderr for the CLI's reported cause.",
            label=label,
            cmd=cmd,
        )

    emit_event("provider_completed", {"label": label, "elapsed_s": round(elapsed, 2)}, root=root)
    return BoundedRunResult(
        phase=PHASE_COMPLETED,
        elapsed_s=elapsed,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        recovery="",
        label=label,
        cmd=cmd,
    )
