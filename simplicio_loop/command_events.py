"""``command_started`` / ``command_finished`` producer for the dashboard-event/v1 stream (issue #1551).

``track`` wraps one real command run: it appends ``command_started`` before the command and the matching
``command_finished`` (exit code, duration from a monotonic clock) after it, also when the run raises or is
cancelled. ``around`` does the same for an awaitable that yields a check result dict (``returncode`` or
``reason_code``). The command text is scrubbed and only then cut to ``COMMAND_MAX`` characters, so a cut cannot
split a secret into a shape the scrubber no longer knows. Every write is fail-open: an error in the event writer
never changes the run. Events go out through the quality producer's seam (source ``worker``, scope ``task``,
kill switch, run directory and iteration rules).
"""
from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .dashboard.runs import redact_text
from .quality_events import _emit

COMMAND_MAX = 200
SCRUB_INPUT_MAX = 4096
REASON_MAX = 100

# redact_text knows key=value pairs; a command line also passes a secret as the next word (``--token abc``).
_SECRET_FLAG = re.compile(
    r"(?i)(--?(?:pass(?:word|wd)?|pwd|token|secret|api[-_]?key|access[-_]?key|auth(?:orization)?)\s+)"
    r"(?:\"[^\"]*\"|'[^']*'|\S+)")


def scrub(command: Any) -> str:
    """The command text as it may be written to an event: secrets masked first, then cut to ``COMMAND_MAX``."""
    if isinstance(command, bytes):
        command = command.decode("utf-8", "replace")
    text = "" if command is None else str(command)[:SCRUB_INPUT_MAX]
    return _SECRET_FLAG.sub(r"\1[REDACTED]", redact_text(text))[:COMMAND_MAX]


class Span:
    """One tracked command: the body sets ``exit_code`` (and ``reason`` when it did not exit) before the block ends."""

    def __init__(self) -> None:
        self.command_id = uuid.uuid4().hex
        self.exit_code: Any = None
        self.reason: Any = None


def _write(task_id: Any, kind: str, payload: dict[str, Any], severity: str, iteration: Any, env: Any) -> None:
    try:
        _emit(task_id, [(kind, payload, severity)], iteration, env)
    except Exception:  # noqa: BLE001 - fail-open: telemetry must never break the run
        pass


def _finish(task_id: Any, span: Span, began: float, interrupted: bool, iteration: Any, env: Any) -> None:
    code = span.exit_code if isinstance(span.exit_code, int) and not isinstance(span.exit_code, bool) else None
    status = "interrupted" if interrupted else "error" if code is None else "pass" if code == 0 else "fail"
    payload: dict[str, Any] = {"command_id": span.command_id, "exit_code": None if interrupted else code,
                               "duration_s": round(time.monotonic() - began, 3), "status": status}
    if span.reason:
        payload["reason"] = str(span.reason)[:REASON_MAX]
    _write(task_id, "command_finished", payload, "info" if status == "pass" else "warning", iteration, env)


@contextmanager
def track(task_id: Any, command: Any, *, iteration: Any = None, env: Mapping[str, Any] | None = None) -> Iterator[Span]:
    """Append ``command_started`` now and the matching ``command_finished`` when the block ends, however it ends."""
    span = Span()
    _write(task_id, "command_started", {"command_id": span.command_id, "command": scrub(command)}, "info", iteration, env)
    began = time.monotonic()
    try:
        yield span
    except BaseException:
        _finish(task_id, span, began, True, iteration, env)
        raise
    _finish(task_id, span, began, False, iteration, env)


async def around(task_id: Any, command: Any, run: Awaitable[Any], *, iteration: Any = None,
                 env: Mapping[str, Any] | None = None) -> Any:
    """Await ``run`` between the two events and return its result; a result dict supplies ``returncode``/``reason_code``."""
    with track(task_id, command, iteration=iteration, env=env) as span:
        result = await run
        if isinstance(result, Mapping):
            span.exit_code = result.get("returncode")
            span.reason = result.get("reason_code")
        return result
