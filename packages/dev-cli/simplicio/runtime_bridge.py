"""Runtime bridge — Runtime is not part of this stack.

Callers still import these names. Discovery, native routing, and binary
invocation are hard-closed: never locate or spawn a ``simplicio`` binary.
``record_delegation`` remains so existing telemetry call sites keep working.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .observability import emit_event, record_savings_event

_RUNTIME_NOT_IN_STACK = (
    "simplicio-runtime is not part of this stack; do not invoke a simplicio binary. "
    "Use simplicio-dev-cli edit --plan <edit-plan.json> --apply."
)


def discover_simplicio() -> str | None:
    """Runtime is not part of this stack. Always ``None``."""
    return None


def simplicio_available() -> bool:
    """Runtime is not part of this stack. Always ``False``."""
    return False


def call_simplicio(
    args: list[str],
    *,
    input_text: str | None = None,
    capture_output: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Refuse Runtime binary invocation.

    Raises
    ------
    RuntimeError
        Always. Runtime is not part of this stack.
    """
    raise RuntimeError(_RUNTIME_NOT_IN_STACK)


def delegated_command(binary: str, args: list[str]) -> list[str]:
    """Build a Windows-safe argv for invoking an explicit local helper.

    Kept for Python-side callers that already resolved a helper path. This
    does not discover or launch Runtime.
    """
    binary_path = Path(binary)
    cmd = [binary, *args]
    if sys.platform != "win32":
        return cmd
    if binary_path.suffix.lower() in {".exe", ".bat", ".cmd", ".ps1"}:
        return cmd
    return [sys.executable, binary, *args]


def use_native_implementation(
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> bool:
    """Runtime is not part of this stack. Always ``False``."""
    return False


#: The three routes a delegable verb's invocation can take (issue #111):
#: ``"native"`` — unused; Runtime is not part of this stack;
#: ``"python-fallback"`` — Python implementation ran because Runtime is absent;
#: ``"python-forced"`` — the caller explicitly opted out of a native binary.
DELEGATION_ROUTES = ("native", "python-fallback", "python-forced")

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

    Called from every call site that previously chose between a native Rust
    binary and the Python fallback so ``simplicio-py doctor`` can report
    routing. Native is never selected from this module.
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
