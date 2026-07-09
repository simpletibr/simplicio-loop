"""Runtime bridge — discover and delegate to the Rust simplicio binary.

Provides a unified interface for detecting the native Rust ``simplicio``
binary on the PATH and routing CLI commands to it via ``subprocess``, with
graceful Python fallback when the binary is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .observability import emit_event, record_savings_event


def discover_simplicio() -> str | None:
    """Locate the ``simplicio`` Rust binary on the PATH.

    Returns the absolute path to the binary, or ``None`` if it is not found.
    Also respects the ``SIMPLICIO_BIN`` environment variable override.
    """
    explicit = os.environ.get("SIMPLICIO_BIN")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    found = shutil.which("simplicio")
    return found


def simplicio_available() -> bool:
    """Return ``True`` if the Rust ``simplicio`` binary is available."""
    return discover_simplicio() is not None


def call_simplicio(
    args: list[str],
    *,
    input_text: str | None = None,
    capture_output: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Call the Rust ``simplicio`` binary with *args*.

    Parameters
    ----------
    args:
        Command-line arguments to pass to the ``simplicio`` binary.
    input_text:
        Optional string to feed to the process's stdin.
    capture_output:
        If ``True`` (default), capture stdout and stderr.
    timeout:
        Timeout in seconds (no timeout if ``None``).

    Returns
    -------
    ``subprocess.CompletedProcess`` with ``stdout`` and ``stderr`` populated
    when *capture_output* is ``True``.

    Raises
    ------
    RuntimeError
        If the ``simplicio`` binary cannot be found.
    subprocess.TimeoutExpired
        If the call exceeds *timeout*.
    """
    binary = discover_simplicio()
    if binary is None:
        raise RuntimeError(
            "simplicio (Rust binary) not found on PATH. Install the simplicio-runtime or set SIMPLICIO_BIN."
        )
    cmd = [binary, *args]
    completed = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=capture_output,
        timeout=timeout,
    )
    return completed


def use_native_implementation(
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> bool:
    """Decide whether to use the Rust binary or Python fallback.

    ``prefer_native`` is the default behaviour — use Rust when available.
    ``prefer_python`` forces Python fallback regardless of availability.
    If both are ``False`` the function falls back to the default heuristic
    (prefer native when available).

    Returns ``True`` to indicate the Rust binary should be used.
    """
    if prefer_python:
        return False
    if not simplicio_available():
        return False
    return prefer_native


#: The three routes a delegable verb's invocation can take (issue #111):
#: ``"native"`` — the Rust ``simplicio`` binary handled the call;
#: ``"python-fallback"`` — the binary was unavailable or the delegation
#: attempt failed, so the pure-Python implementation ran instead;
#: ``"python-forced"`` — the caller explicitly opted out of the Rust binary
#: (e.g. ``--python``/``--no-runtime``), so Python ran even if the binary was
#: available.
DELEGATION_ROUTES = ("native", "python-fallback", "python-forced")

# Reasons that mean "this is the expected/routine case", not a real failure —
# a `python-fallback` for one of these stays at `level="info"`; anything else
# (a genuine subprocess/parse error) is surfaced as a `level="warning"` event
# so it's visible without hand-grepping `.simplicio/events.jsonl`.
_ROUTINE_FALLBACK_REASONS = frozenset({"binary-not-found", "user-forced-python"})


def record_delegation(
    verb: str,
    route: str,
    *,
    root: str = ".",
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record telemetry for one delegable-verb invocation (issue #111).

    Called from every call site that chooses between the native Rust
    binary and the Python fallback (``gate``/``nest`` in ``cli.py``,
    ``commands/edit.py``, ``commands/file_read.py``,
    ``commands/test_run.py``) so ``simplicio-py doctor`` can report what
    fraction of each verb's invocations actually reached the native binary,
    without every call site hand-rolling its own event/ledger bookkeeping.

    Writes two things, both through the existing observability primitives:

    - an ``emit_event("native_delegation", ...)`` record (schema
      ``simplicio.dev-cli-event/v1``) with ``payload = {"verb", "route",
      "reason"}`` — this is what `simplicio.observability.
      native_delegation_summary` aggregates for `doctor`.
    - a `record_savings_event` ledger entry, ``source=f"native-delegation:
      {verb}"``. Both `gate`/`nest`/`edit`/`file`/`test-run` are already
      zero-LLM-token deterministic operations in *both* the native and the
      Python-fallback implementation, so there is no real token delta to
      report either way — ``baseline_tokens == actual_tokens == 0`` is the
      honest number (``proof_kind="estimated"``, method declared in
      ``note``). This entry exists so a native-vs-python routing regression
      shows up in the same ledger the rest of the token-savings tooling
      already reads, without fabricating a savings claim that isn't real.
    """
    if route not in DELEGATION_ROUTES:
        raise ValueError(f"route must be one of {DELEGATION_ROUTES!r}, got {route!r}")

    payload: dict[str, Any] = {"verb": verb, "route": route}
    if reason:
        payload["reason"] = reason

    level = "info"
    if route == "python-fallback" and reason and reason not in _ROUTINE_FALLBACK_REASONS:
        level = "warning"

    event = emit_event("native_delegation", payload, level=level, root=root)

    record_savings_event(
        root,
        source=f"native-delegation:{verb}",
        baseline_tokens=0,
        actual_tokens=0,
        note=(
            f"native-vs-python routing telemetry for '{verb}' ({route}); "
            "no LLM token spend either way, so no savings are claimed"
        ),
        proof_kind="estimated",
        extra={"verb": verb, "route": route, "reason": reason, **(extra or {})},
    )
    return event
