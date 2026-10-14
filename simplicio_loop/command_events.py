"""``command_started`` / ``command_finished`` producer for the dashboard-event/v1 stream (issue #1551).

``track`` wraps one real command run: it appends ``command_started`` before the command and the matching
``command_finished`` (exit code, duration from a monotonic clock) after it, also when the run raises or is
cancelled. ``around`` does the same for an awaitable that yields a check result dict (``returncode`` or
``reason_code``). The command text is scrubbed by ``runs.redact_command`` and only then cut to ``COMMAND_MAX``
characters, so a cut cannot split a secret into a shape the scrubber no longer knows. Every step of the telemetry is
fail-open: an error in the scrubber or the event writer never changes the run. Events go out through the quality
producer's seam (source ``worker``, scope ``task``, kill switch, run directory and iteration rules).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .dashboard.runs import redact_command
from .quality_events import _emit

COMMAND_MAX = 200
REASON_MAX = 100
# ``emit(kind, payload, severity)`` appends one event. The default is the worker seam; a runner passes its own run directory.
Emit = Callable[[str, dict[str, Any], str], None]


def scrub(command: Any) -> str:
    """The command text as it may be written to an event: secrets masked first, then cut to ``COMMAND_MAX``."""
    if isinstance(command, bytes):
        command = command.decode("utf-8", "replace")
    return redact_command("" if command is None else str(command))[:COMMAND_MAX]


class Span:
    """One tracked command: the body sets ``exit_code`` (and ``reason`` when it did not exit) before the block ends."""

    def __init__(self) -> None:
        self.command_id = uuid.uuid4().hex
        self.exit_code: Any = None
        self.reason: Any = None


def _worker_emit(task_id: Any, iteration: Any, env: Any) -> Emit:
    """The default writer: the worker's quality-events seam, task scope."""
    def emit(kind: str, payload: dict[str, Any], severity: str) -> None:
        _emit(task_id, [(kind, payload, severity)], iteration, env)
    return emit


def _write(emit: Emit, kind: str, payload: Any, severity: str) -> None:
    """Append one event; ``payload`` is a callable so that building it is fail-open too."""
    try:
        emit(kind, payload(), severity)
    except Exception:  # noqa: BLE001 - fail-open: telemetry must never break the run
        pass


def _finish(emit: Emit, span: Span, began: float, interrupted: bool) -> None:
    code = span.exit_code if isinstance(span.exit_code, int) and not isinstance(span.exit_code, bool) else None
    status = "interrupted" if interrupted else "error" if code is None else "pass" if code == 0 else "fail"

    def payload() -> dict[str, Any]:
        found: dict[str, Any] = {"command_id": span.command_id, "exit_code": None if interrupted else code,
                                 "duration_s": round(time.monotonic() - began, 3), "status": status}
        if span.reason:
            found["reason"] = str(span.reason)[:REASON_MAX]
        return found
    _write(emit, "command_finished", payload, "info" if status == "pass" else "warning")


@contextmanager
def track(task_id: Any, command: Any, *, iteration: Any = None, env: Mapping[str, Any] | None = None,
          emit: Emit | None = None) -> Iterator[Span]:
    """Append ``command_started`` now and the matching ``command_finished`` when the block ends, however it ends.

    ``emit`` replaces the default writer (the worker seam for ``task_id``, ``iteration`` and ``env``).
    """
    write = emit or _worker_emit(task_id, iteration, env)
    span = Span()
    _write(write, "command_started", lambda: {"command_id": span.command_id, "command": scrub(command)}, "info")
    began = time.monotonic()
    try:
        yield span
    except BaseException:
        _finish(write, span, began, True)
        raise
    _finish(write, span, began, False)


async def around(task_id: Any, command: Any, run: Awaitable[Any], *, iteration: Any = None,
                 env: Mapping[str, Any] | None = None) -> Any:
    """Await ``run`` between the two events and return its result; a result dict supplies ``returncode``/``reason_code``."""
    with track(task_id, command, iteration=iteration, env=env) as span:
        result = await run
        try:
            if isinstance(result, Mapping):
                span.exit_code = result.get("returncode")
                span.reason = result.get("reason_code")
        except Exception:  # noqa: BLE001 - fail-open: a result that cannot be read is still the caller's result
            pass
        return result
