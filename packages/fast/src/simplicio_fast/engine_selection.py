"""Rust-first Fast engine selection contract (V3 issues #39/#42).

This module is deliberately side-effect free: probing and conformance are supplied
by the caller, so selecting Rust never imports or starts the Python engine in the
same fast path. The CLI/router can persist the returned receipt at its boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

ENGINE_SELECTION_SCHEMA = "simplicio.fast.engine-selection/v1"
SUPPORTED_MODES = frozenset({"auto", "rust", "python", "off"})


def resolve_mode(
    *,
    cli: str | None = None,
    workspace: str | None = None,
    user: str | None = None,
    default: str = "auto",
) -> tuple[str, str]:
    """Resolve mode by CLI, workspace, user, then default precedence."""
    for source, value in (
        ("cli", cli),
        ("workspace", workspace),
        ("user", user),
        ("default", default),
    ):
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized not in SUPPORTED_MODES:
            raise ValueError(f"invalid Fast engine mode from {source}: {value}")
        return normalized, source
    raise ValueError("no Fast engine mode configured")


class EngineSelectionError(RuntimeError):
    """An explicit engine request cannot be satisfied."""


@dataclass(frozen=True)
class EngineSelection:
    requested: str
    selected: str | None
    usable: bool
    reason: str
    rust_probe: Mapping[str, Any]
    python_available: bool
    conformance_passed: bool

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": ENGINE_SELECTION_SCHEMA,
            "requested_engine": self.requested,
            "selected_engine": self.selected,
            "usable": self.usable,
            "reason": self.reason,
            "rust_probe": dict(self.rust_probe),
            "python_available": self.python_available,
            "conformance_passed": self.conformance_passed,
        }
        return payload


def select_engine(
    mode: str = "auto",
    *,
    rust_probe: Mapping[str, Any] | None = None,
    python_available: bool = True,
    conformance_passed: bool = False,
) -> EngineSelection:
    """Choose one engine without dual-loading or silent fallback.

    rust_probe is a trusted, already-completed health/capability result. A
    healthy Rust selection requires both healthy and conformance evidence.
    auto falls back to Python with a reason; explicit rust raises instead.
    """
    requested = str(mode or "auto").strip().lower()
    if requested not in SUPPORTED_MODES:
        raise ValueError(f"unsupported Fast engine mode: {mode}")
    probe = dict(rust_probe or {})
    rust_healthy = bool(probe.get("healthy") and probe.get("capabilities_ok"))
    rust_ready = rust_healthy and bool(conformance_passed)
    if requested == "off":
        return EngineSelection(
            requested,
            None,
            False,
            "disabled_by_configuration",
            probe,
            python_available,
            conformance_passed,
        )
    if requested == "python":
        if not python_available:
            raise EngineSelectionError("python_engine_unavailable")
        return EngineSelection(
            requested,
            "python",
            True,
            "explicit_python",
            probe,
            python_available,
            conformance_passed,
        )
    if requested == "rust":
        if not rust_ready:
            reason = (
                "rust_conformance_missing" if rust_healthy else "rust_health_failed"
            )
            raise EngineSelectionError(reason)
        return EngineSelection(
            requested,
            "rust",
            True,
            "explicit_rust",
            probe,
            python_available,
            conformance_passed,
        )
    if rust_ready:
        return EngineSelection(
            requested,
            "rust",
            True,
            "rust_health_and_conformance_passed",
            probe,
            python_available,
            conformance_passed,
        )
    if python_available:
        reason = "rust_conformance_missing" if rust_healthy else "rust_unavailable"
        return EngineSelection(
            requested,
            "python",
            True,
            reason,
            probe,
            python_available,
            conformance_passed,
        )
    return EngineSelection(
        requested,
        None,
        False,
        "no_usable_engine",
        probe,
        python_available,
        conformance_passed,
    )


__all__ = [
    "ENGINE_SELECTION_SCHEMA",
    "EngineSelection",
    "EngineSelectionError",
    "resolve_mode",
    "select_engine",
]
