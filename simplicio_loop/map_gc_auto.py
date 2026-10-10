"""Automatic `map gc`, at most once an hour per repository (#1671).

The Runtime leaks `baseline-build-*` trees and `baseline-*.json` files under ``<git-common-dir>/simplicio`` (simplicio-runtime#7609).
``map gc`` reclaims them but nothing ran it, so the `watch247` tick calls :func:`maybe_gc` for every base clone it keeps. The
default policy only (``--keep 3``, only what ``plan_gc`` marks safe). The time of the last run is stamped in
``<git-common-dir>/simplicio/map-gc-auto.json`` so every worktree and every process of the repository shares one hour.
Never raises: housekeeping must not break a tick.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .map_service_gc import DEFAULT_KEEP, apply_gc, plan_gc
from .map_service_git import git_common_dir

INTERVAL_SECONDS = 3600.0
STAMP_NAME = "map-gc-auto.json"


def _default_gc(repo: str) -> Dict[str, Any]:
    result = apply_gc(plan_gc(repo, keep=DEFAULT_KEEP))
    return {"removed": len(result.removed), "removed_bytes": result.removed_bytes, "errors": len(result.errors)}


def _last_run(stamp: Path) -> Optional[float]:
    try:
        return float(json.loads(stamp.read_text(encoding="utf-8"))["last_run_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def maybe_gc(repo: str, *, clock: Callable[[], float] = time.time, interval: float = INTERVAL_SECONDS,
             gc: Callable[[str], Any] = _default_gc) -> Optional[Any]:
    """Run ``map gc`` for ``repo`` unless it ran less than ``interval`` seconds ago. The result of ``gc``, or None when skipped."""
    try:
        store = git_common_dir(str(repo)) / "simplicio"
        if not store.is_dir():
            return None  # nothing was ever mapped here: nothing to reclaim
        now = clock()
        stamp = store / STAMP_NAME
        last = _last_run(stamp)
        if last is not None and 0 <= now - last < interval:
            return None
        tmp = stamp.with_name(f"{STAMP_NAME}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"last_run_at": now}), encoding="utf-8")
        os.replace(tmp, stamp)  # stamped before the run: a failing gc is not retried every tick
        return gc(str(repo))
    except Exception:  # noqa: BLE001 - never break the caller
        return None


__all__ = ["INTERVAL_SECONDS", "STAMP_NAME", "maybe_gc"]
