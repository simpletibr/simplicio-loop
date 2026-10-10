"""Automatic `map gc`, at most once an hour per repository (#1671).

The Runtime leaks `baseline-build-*` trees and `baseline-*.json` files under ``<git-common-dir>/simplicio`` (simplicio-runtime#7609).
``map gc`` reclaims them but nothing ran it, so the `watch247` tick calls :func:`maybe_gc` for every base clone it keeps. The
default policy only (``--keep 3``, only what ``plan_gc`` marks safe). The time of the last run is stamped in
``<git-common-dir>/simplicio/map-gc-auto.json`` so every worktree and every process of the repository shares one hour.
Never raises: housekeeping must not break a tick.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .map_service_gc import DEFAULT_KEEP, apply_gc, plan_gc, refused_root
from .map_service_git import git_common_dir

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600.0
STAMP_NAME = "map-gc-auto.json"
LOCK_NAME = "map-gc-auto.lock"  # single-flight per repository: one collection at a time across threads and processes


def _default_gc(repo: str) -> Dict[str, Any]:
    plan = plan_gc(repo, keep=DEFAULT_KEEP)
    for error in plan.errors:  # a refused root or an aborted bases pass: say why it was not collected
        log.warning("map gc auto: %s", error)
    result = apply_gc(plan)
    return {"removed": len(result.removed), "removed_bytes": result.removed_bytes,
            "errors": len(result.errors) + len(plan.errors)}


def _last_run(stamp: Path) -> Optional[float]:
    try:
        return float(json.loads(stamp.read_text(encoding="utf-8"))["last_run_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def maybe_gc(repo: str, *, clock: Callable[[], float] = time.time, interval: float = INTERVAL_SECONDS,
             gc: Callable[[str], Any] = _default_gc) -> Optional[Any]:
    """Run ``map gc`` for ``repo`` unless it ran less than ``interval`` seconds ago. The result of ``gc``, or None when skipped."""
    lock = None
    try:
        store = git_common_dir(str(repo)) / "simplicio"
        if not store.is_dir() or refused_root(store, store) or refused_root(store / "map", store):
            return None  # nothing was ever mapped here, or the store points out of the repository: never delete through a link
        from simplicio_mapper.mapper.file_lock import acquire_lock_at

        lock = acquire_lock_at(str(store / LOCK_NAME), operation="map-gc-auto")
        if lock is None:
            return None  # another process or thread is collecting this repository right now
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
    finally:
        if lock is not None:
            try:
                from simplicio_mapper.mapper.file_lock import release_lock_at

                release_lock_at(lock)
            except Exception:  # noqa: BLE001
                pass


__all__ = ["INTERVAL_SECONDS", "LOCK_NAME", "STAMP_NAME", "maybe_gc"]
