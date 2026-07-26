"""task_operator.py — bounded execution of shelled-out provider subprocesses.

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
- classifies a stall as ``"startup_timeout"`` (no stdout/stderr byte yet) vs
  ``"total_timeout"`` (output has started, but the deadline passed anyway);
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
# Configuration (env-overridable; defaults preserve the pre-#210 behavior for
# the total deadline).
# --------------------------------------------------------------------------- #

DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_TOTAL_TIMEOUT_S = 600.0
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


def startup_timeout_s() -> float:
    return _env_float("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", DEFAULT_STARTUP_TIMEOUT_S)


def total_timeout_s() -> float:
    return _env_float("SIMPLICIO_PROVIDER_TOTAL_TIMEOUT_S", DEFAULT_TOTAL_TIMEOUT_S)


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


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill *proc* and every descendant it spawned.

    POSIX: the child was started in its own session (``start_new_session=
    True``), so its process group id equals its pid; ``os.killpg`` reaches
    every descendant in one call.

    Windows: the child was started with ``CREATE_NEW_PROCESS_GROUP``;
    ``taskkill /PID <pid> /T /F`` kills the whole tree. If ``taskkill`` is
    unavailable for any reason, fall back to killing only the direct child
    (still better than leaking the whole call).
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
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
            data = stream.read(4096)
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
    heartbeat_interval: float | None = None,
    cancel_event: threading.Event | None = None,
    root: str | None = None,
) -> BoundedRunResult:
    """Run *cmd* to completion or until it is bounded off.

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
        if not first_output_event.is_set() and elapsed >= startup_timeout:
            phase = PHASE_STARTUP_TIMEOUT
            break
        if elapsed >= total_timeout:
            phase = PHASE_TOTAL_TIMEOUT
            break
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
