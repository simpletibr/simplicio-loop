"""Adaptive execution-profile planning for the mapping pipeline.

Issue #279 asks that ``auto`` stop treating async as dogma and make the
chosen route explicit/rollbackable.  This module is intentionally narrow:
it governs the profiles this package can actually execute today (``sync``
and ``async``) while reserving the public enum values for future
``thread``/``process``/``hub`` integrations without pretending those runtimes
exist locally.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ExecutionProfile(str, Enum):
    """User-visible execution profiles for mapper pipeline dispatch."""

    AUTO = "auto"
    SYNC = "sync"
    ASYNC = "async"
    THREAD = "thread"
    PROCESS = "process"
    HUB = "hub"


EXECUTION_PROFILE_ENV = "SIMPLICIO_MAPPER_EXECUTION_PROFILE"
ASYNC_KILL_SWITCH_ENV = "SIMPLICIO_MAPPER_NO_ASYNC_PIPELINE"
AUTO_CALIBRATION_ENV = "SIMPLICIO_MAPPER_AUTO_CALIBRATION"

_SUPPORTED_LOCAL_PROFILES = {ExecutionProfile.SYNC, ExecutionProfile.ASYNC}
_FUTURE_PROFILES = {ExecutionProfile.THREAD, ExecutionProfile.PROCESS, ExecutionProfile.HUB}


@dataclass(frozen=True)
class ExecutionPlan:
    """Resolved route and the evidence used to pick it."""

    requested_profile: str
    selected_profile: str
    reason: str
    file_count: int
    threshold: int
    async_disabled: bool
    platform: str
    source: str
    candidates: dict[str, Any] = field(default_factory=dict)
    evidence: str | None = None
    predicted_p95_ms: float | None = None
    fallback_profile: str | None = None
    fallback_reason: str | None = None

    def to_receipt(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = "simplicio.execution-plan/v1"
        return payload


def _requested_profile_from_env() -> ExecutionProfile:
    raw = os.environ.get(EXECUTION_PROFILE_ENV, "auto").strip().lower()
    try:
        return ExecutionProfile(raw)
    except ValueError:
        return ExecutionProfile.AUTO


def _calibration_fingerprint() -> dict[str, str]:
    return {
        "platform": platform.system() or platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def _compatible_calibration_profiles(
    calibration: Any, file_count: int
) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not isinstance(calibration, dict):
        return {}, "calibration is not an object"
    expected = calibration.get("fingerprint")
    if isinstance(expected, dict):
        actual = _calibration_fingerprint()
        mismatches = [key for key, value in expected.items() if actual.get(key) != value]
        if mismatches:
            return {}, f"calibration fingerprint mismatch: {', '.join(sorted(mismatches))}"
    raw_profiles = calibration.get("profiles")
    if not isinstance(raw_profiles, dict):
        return {}, "calibration profiles are missing"
    profiles: dict[str, dict[str, Any]] = {}
    for name in ("sync", "async"):
        profile = raw_profiles.get(name)
        if not isinstance(profile, dict):
            continue
        p95 = profile.get("p95_ms")
        minimum, maximum = profile.get("file_count_min", 0), profile.get("file_count_max")
        if not isinstance(p95, (int, float)) or p95 <= 0:
            continue
        if not isinstance(minimum, int) or (maximum is not None and not isinstance(maximum, int)):
            continue
        if file_count < minimum or (maximum is not None and file_count > maximum):
            continue
        profiles[name] = profile
    return profiles, None if profiles else "no compatible calibrated profile"


def plan_execution(file_count: int, threshold: int) -> ExecutionPlan:
    """Resolve the mapper execution profile for the current run.

    ``auto`` selects the lowest-p95 compatible calibrated local profile. With
    no compatible calibration, it uses the conservative synchronous path:
    missing evidence must not promote a more complex executor. Explicit
    ``sync``/``async`` remain available for diagnosis and benchmarking, and
    the async kill switch always wins.
    """
    requested = _requested_profile_from_env()
    async_disabled = os.environ.get(ASYNC_KILL_SWITCH_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    safe_threshold = max(1, int(threshold))
    safe_file_count = max(0, int(file_count))
    source = "env" if os.environ.get(EXECUTION_PROFILE_ENV) else "auto"

    if async_disabled:
        return ExecutionPlan(
            requested_profile=requested.value,
            selected_profile=ExecutionProfile.SYNC.value,
            reason=f"{ASYNC_KILL_SWITCH_ENV} is set; forced safe synchronous rollback",
            file_count=safe_file_count,
            threshold=safe_threshold,
            async_disabled=True,
            platform=platform.system() or platform.platform(),
            source="kill-switch",
        )

    if requested in _SUPPORTED_LOCAL_PROFILES:
        return ExecutionPlan(
            requested_profile=requested.value,
            selected_profile=requested.value,
            reason=f"explicit {EXECUTION_PROFILE_ENV}={requested.value}",
            file_count=safe_file_count,
            threshold=safe_threshold,
            async_disabled=False,
            platform=platform.system() or platform.platform(),
            source=source,
        )

    if requested in _FUTURE_PROFILES:
        reason_prefix = (
            f"{EXECUTION_PROFILE_ENV}={requested.value} is reserved but not implemented locally; "
        )
        source = "fallback"
    else:
        reason_prefix = ""

    calibration_path = os.environ.get(AUTO_CALIBRATION_ENV, "").strip()
    if calibration_path:
        try:
            with open(calibration_path, encoding="utf-8") as handle:
                calibration = json.load(handle)
            profiles, calibration_reason = _compatible_calibration_profiles(calibration, safe_file_count)
            if profiles:
                ordered = sorted(profiles.items(), key=lambda item: float(item[1]["p95_ms"]))
                best_name, best = ordered[0]
                candidates = {name: float(profile["p95_ms"]) for name, profile in ordered}
                return ExecutionPlan(
                    requested_profile=requested.value, selected_profile=best_name,
                    reason=f"auto selected {best_name} from compatible calibration p95 ({float(best['p95_ms']):g}ms)",
                    file_count=safe_file_count, threshold=safe_threshold, async_disabled=False,
                    platform=platform.system() or platform.platform(), source="calibration",
                    candidates=candidates, evidence="compatible calibration",
                    predicted_p95_ms=float(best["p95_ms"]),
                )
            fallback_reason = calibration_reason or "calibration was not usable"
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            fallback_reason = "calibration could not be read or parsed"
    else:
        fallback_reason = None

    selected = ExecutionProfile.SYNC
    reason = (
        f"{reason_prefix}auto fell back to the conservative synchronous path "
        "because no compatible calibration evidence was available"
    )

    return ExecutionPlan(
        requested_profile=requested.value,
        selected_profile=selected.value,
        reason=reason,
        file_count=safe_file_count,
        threshold=safe_threshold,
        async_disabled=False,
        platform=platform.system() or platform.platform(),
        source=source,
        fallback_profile=selected.value,
        fallback_reason=locals().get("fallback_reason"),
    )
