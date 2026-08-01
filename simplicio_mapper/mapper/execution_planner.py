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
from dataclasses import asdict, dataclass
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


def plan_execution(file_count: int, threshold: int) -> ExecutionPlan:
    """Resolve the mapper execution profile for the current run.

    ``auto`` selects the bounded async pipeline so every normal mapper run
    benefits from concurrent file I/O and parsing. Explicit ``sync`` remains
    available for diagnosis and the async kill switch always wins. Future
    profiles are accepted as configuration vocabulary but deterministically
    fall back to ``auto`` until real worker/Hub protocols are implemented in
    this package.
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
            profiles = calibration.get("profiles") if isinstance(calibration, dict) else None
            sync_p95 = profiles.get("sync", {}).get("p95_ms") if isinstance(profiles, dict) else None
            async_p95 = profiles.get("async", {}).get("p95_ms") if isinstance(profiles, dict) else None
            if (isinstance(sync_p95, (int, float)) and isinstance(async_p95, (int, float))
                    and sync_p95 >= 0 and async_p95 > 0 and sync_p95 <= async_p95 * 0.9):
                return ExecutionPlan(
                    requested_profile=requested.value, selected_profile=ExecutionProfile.SYNC.value,
                    reason=f"auto selected sync from compatible calibration p95 ({sync_p95:g}ms <= 90% of {async_p95:g}ms)",
                    file_count=safe_file_count, threshold=safe_threshold, async_disabled=False,
                    platform=platform.system() or platform.platform(), source="calibration",
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    selected = ExecutionProfile.ASYNC
    reason = (
        f"{reason_prefix}auto selected bounded async pipeline "
        "for concurrent file inventory"
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
    )
