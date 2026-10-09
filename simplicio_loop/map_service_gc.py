"""Safe garbage collection for the repository-central map stores (#1574).

Three stores live under ``<git-common-dir>/simplicio`` and are shared by every linked worktree:

* ``map/``       baselines written by the Simplicio Runtime (``baseline-<tree>.json``), their
                 ``baseline-<tree>.lock`` files and the ``baseline-build-*`` scratch trees it
                 materializes while building one;
* ``canonical/`` the Mapper's content-addressed default-branch bases (``<digest>/``);
* ``scratch/``   temporary checkouts the Mapper builder uses while it builds a base.

A one-shot Runtime process that is killed, or that exits while its detached baseline thread is still
building, never runs the destructors that would remove its scratch tree and lock. Measured on a
synthetic repository with the real binary: ``simplicio context`` leaves one ``baseline-build-*``
(a full tree copy) per call once the previous lock is stale. On the maintainer's repository that
was 102 directories of 63-69 MB (6.8 GB). Nothing reclaimed them.

Safety rules, all enforced again right before a removal:

* a scratch tree is only removed when nothing was written under it for ``max_age`` seconds (1 h),
  it holds no live ``build.lock`` and no process has its working directory or an open file in it;
* a lock file is only removed when it is older than ``max_age`` (the Runtime itself reclaims a lock
  after five minutes);
* a Runtime baseline is kept when it is among the newest ``keep``, is the base a live worktree still
  forks from, has a fresh build lock, or was written moments ago;
* canonical bases are handled by :mod:`simplicio_mapper.mapper.canonical_gc` with the same ``keep``
  and the digests that live worktrees reference.

``startup_gc`` is the cheap, never-raising variant run before every index: scratch trees and orphan
locks only, never a base.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .map_service_git import (
    GitDiscoveryError,
    GitIdentityError,
    default_branch_ref,
    git_common_dir,
    list_worktrees,
    merge_base_tree,
    resolve_default_base,
)

SCHEMA = "simplicio.map-gc/v1"
SCRATCH_PREFIX = "baseline-build-"
STALE_AFTER_SECONDS = 3600.0
RECENT_BASELINE_SECONDS = 60.0
DEFAULT_KEEP = 3
LOCK_NAME = "build.lock"
OVERLAY_RELATIVE = (".simplicio-loop", "overlay.json")

_BASELINE_FILE = re.compile(r"^baseline-(?P<key>[0-9a-f]{40,64})\.(?P<ext>json|lock)$")


@dataclass
class GcItem:
    kind: str  # scratch | lock | baseline | canonical-base | canonical-tmp
    path: str
    bytes: int
    action: str  # remove | keep
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "path": self.path, "bytes": self.bytes,
            "action": self.action, "reason": self.reason,
        }


@dataclass
class GcPlan:
    repo: str
    common_dir: str
    keep: int
    max_age: float
    items: List[GcItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    now: float = 0.0
    canonical: Optional[Dict[str, Any]] = None

    @property
    def would_free_bytes(self) -> int:
        return sum(item.bytes for item in self.items if item.action == "remove")


@dataclass
class GcResult:
    removed: List[str] = field(default_factory=list)
    removed_bytes: int = 0
    errors: List[str] = field(default_factory=list)


# --- filesystem helpers -------------------------------------------------------------------------


def tree_size(path: Path) -> int:
    """Bytes under ``path`` (files only, symlinks not followed); a plain file is its own size."""
    try:
        if not path.is_dir() or path.is_symlink():
            return path.lstat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def newest_mtime(path: Path) -> float:
    """Latest modification time of ``path`` or anything inside it."""
    try:
        newest = path.lstat().st_mtime
    except OSError:
        return 0.0
    if not path.is_dir() or path.is_symlink():
        return newest
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


def _lock_is_live(directory: Path) -> bool:
    lock = directory / LOCK_NAME
    if not lock.exists():
        return False
    try:
        from simplicio_mapper.mapper.file_lock import inspect_lock_at

        return bool(inspect_lock_at(str(lock))["active"])
    except Exception:  # noqa: BLE001 - an unreadable lock is treated as held: never guess-delete
        return True


def process_inside(directory: Path) -> Optional[int]:
    """Pid of a process whose cwd or open file lives under ``directory`` (Linux ``/proc``)."""
    proc = Path("/proc")
    if not sys.platform.startswith("linux") or not proc.is_dir():
        return None
    prefix = os.path.realpath(str(directory)) + os.sep
    own = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        try:
            targets = [os.readlink(entry / "cwd")]
            targets.extend(os.readlink(fd) for fd in (entry / "fd").iterdir())
        except OSError:
            continue
        if any((target + os.sep).startswith(prefix) for target in targets):
            return int(entry.name)
    return None


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


# --- stores -------------------------------------------------------------------------------------


def _cache_root(common: Path) -> Path:
    try:
        from simplicio_mapper.mapper.canonical_storage import resolve_canonical_cache_root

        return Path(resolve_canonical_cache_root(str(common)))
    except ImportError:  # pragma: no cover - the mapper ships in the same wheel
        return common / "simplicio"


def _stores(common: Path) -> Dict[str, Path]:
    base = common / "simplicio"
    cache = _cache_root(common)
    return {"map": base / "map", "scratch": cache / "scratch", "canonical": cache / "canonical"}


def _scratch_candidates(stores: Dict[str, Path]) -> Iterable[Path]:
    map_dir, scratch_dir = stores["map"], stores["scratch"]
    if map_dir.is_dir():
        for entry in sorted(map_dir.iterdir()):
            if entry.name.startswith(SCRATCH_PREFIX) and entry.is_dir() and not entry.is_symlink():
                yield entry
    if scratch_dir.is_dir():
        for entry in sorted(scratch_dir.iterdir()):
            if entry.is_dir() and not entry.is_symlink():
                yield entry


def _classify_scratch(path: Path, now: float, max_age: float) -> GcItem:
    size = tree_size(path)
    age = now - newest_mtime(path)
    if age < max_age:
        return GcItem("scratch", str(path), size, "keep", "recent")
    if _lock_is_live(path):
        return GcItem("scratch", str(path), size, "keep", "lock_held")
    if process_inside(path) is not None:
        return GcItem("scratch", str(path), size, "keep", "process_inside")
    return GcItem("scratch", str(path), size, "remove", "stale_unlocked")


def _classify_lock(path: Path, now: float, max_age: float) -> GcItem:
    try:
        age = now - path.lstat().st_mtime
    except OSError:
        return GcItem("lock", str(path), 0, "keep", "vanished")
    if age < max_age:
        return GcItem("lock", str(path), 0, "keep", "recent")
    return GcItem("lock", str(path), 0, "remove", "stale_lock")


def referenced_keys(repo: str) -> Dict[str, Set[str]]:
    """What live worktrees still reference: Runtime baseline keys and canonical digests."""
    runtime: Set[str] = set()
    digests: Set[str] = set()
    found = default_branch_ref(repo)
    ref = found[1] if found else None
    try:
        worktrees = list_worktrees(repo)
    except GitDiscoveryError:
        worktrees = []
    for worktree in worktrees:
        root = Path(worktree.path)
        if not root.is_dir():
            continue
        if ref:
            tree = merge_base_tree(str(root), ref)
            if tree:
                runtime.add(tree)
        overlay = root.joinpath(*OVERLAY_RELATIVE)
        if overlay.is_file():
            try:
                digest = json.loads(overlay.read_text(encoding="utf-8")).get("base_digest")
            except (OSError, ValueError):
                digest = None
            if isinstance(digest, str) and digest:
                digests.add(digest)
    base = resolve_default_base(repo)
    if base is not None:
        runtime.add(base.tree)
    return {"runtime": runtime, "digests": digests}


def _classify_baselines(
    map_dir: Path, referenced: Set[str], keep: int, now: float, max_age: float
) -> List[GcItem]:
    files = []
    fresh_locks: Set[str] = set()
    for entry in map_dir.iterdir():
        match = _BASELINE_FILE.match(entry.name)
        if not match or not entry.is_file():
            continue
        if match.group("ext") == "lock":
            try:
                if now - entry.lstat().st_mtime < max_age:
                    fresh_locks.add(match.group("key"))
            except OSError:
                pass
            continue
        try:
            files.append((entry.lstat().st_mtime, match.group("key"), entry))
        except OSError:
            continue
    files.sort(reverse=True)
    items = []
    for index, (mtime, key, entry) in enumerate(files):
        size = tree_size(entry)
        if index < keep:
            reason = "newest_%d" % keep
        elif key in referenced:
            reason = "referenced_by_worktree"
        elif key in fresh_locks:
            reason = "build_lock_fresh"
        elif now - mtime < RECENT_BASELINE_SECONDS:
            reason = "written_moments_ago"
        else:
            items.append(GcItem("baseline", str(entry), size, "remove", "outside_newest_and_unreferenced"))
            continue
        items.append(GcItem("baseline", str(entry), size, "keep", reason))
    return items


def _canonical_plan(repo: str, keep: int, digests: Set[str], plan: GcPlan) -> None:
    try:
        from simplicio_mapper.mapper.canonical_gc import scan_canonical_gc
    except ImportError as exc:  # pragma: no cover - the mapper ships in the same wheel
        plan.errors.append("canonical gc unavailable: %s" % exc)
        return
    try:
        report = scan_canonical_gc(
            repo, apply=False, keep_last=keep, referenced_digests=frozenset(digests), now=plan.now,
        )
    except Exception as exc:  # noqa: BLE001
        plan.errors.append("canonical gc failed: %s" % exc)
        return
    cache_root = _cache_root(Path(plan.common_dir))
    plan.errors.extend(report.errors)
    for candidate, action in [(c, "remove") for c in report.candidates] + [
        (c, "keep") for c in report.preserved
    ]:
        path = cache_root / candidate.relative_path
        kind = "canonical-tmp" if candidate.kind != "manifest_dir" else "canonical-base"
        plan.items.append(GcItem(kind, str(path), tree_size(path), action, candidate.reason))
    plan.canonical = {"keep": keep, "digests": sorted(digests)}


# --- public API ---------------------------------------------------------------------------------


def plan_gc(
    repo: str,
    *,
    keep: int = DEFAULT_KEEP,
    max_age: float = STALE_AFTER_SECONDS,
    now: Optional[float] = None,
    include_bases: bool = True,
) -> GcPlan:
    """Describe what a GC would do. Reads only; nothing is removed."""
    current = time.time() if now is None else float(now)
    common = git_common_dir(repo)
    plan = GcPlan(repo=str(repo), common_dir=str(common), keep=max(0, int(keep)), max_age=max_age, now=current)
    stores = _stores(common)
    for scratch in _scratch_candidates(stores):
        plan.items.append(_classify_scratch(scratch, current, max_age))
    if stores["map"].is_dir():
        for entry in sorted(stores["map"].iterdir()):
            match = _BASELINE_FILE.match(entry.name)
            if match and match.group("ext") == "lock" and entry.is_file():
                plan.items.append(_classify_lock(entry, current, max_age))
    if include_bases:
        references = referenced_keys(repo)
        if stores["map"].is_dir():
            plan.items.extend(
                _classify_baselines(stores["map"], references["runtime"], plan.keep, current, max_age)
            )
        if stores["canonical"].is_dir():
            _canonical_plan(repo, plan.keep, references["digests"], plan)
    return plan


def _still_safe(item: GcItem, plan: GcPlan) -> bool:
    """Re-check an item immediately before removing it: the world may have moved on."""
    path = Path(item.path)
    if not path.exists():
        return False
    now = time.time()
    if item.kind == "scratch":
        fresh = _classify_scratch(path, now, plan.max_age)
        return fresh.action == "remove"
    if item.kind == "lock":
        return _classify_lock(path, now, plan.max_age).action == "remove"
    return True


def apply_gc(plan: GcPlan) -> GcResult:
    """Remove every ``remove`` item of ``plan`` that is still safe. Never raises."""
    result = GcResult()
    for item in plan.items:
        if item.action != "remove" or item.kind.startswith("canonical"):
            continue
        try:
            if not _still_safe(item, plan):
                continue
            _remove_tree(Path(item.path))
            result.removed.append(item.path)
            result.removed_bytes += item.bytes
        except OSError as exc:
            result.errors.append("%s: %s" % (item.path, exc))
    canonical = [item for item in plan.items if item.kind.startswith("canonical") and item.action == "remove"]
    if canonical:
        try:
            from simplicio_mapper.mapper.canonical_gc import scan_canonical_gc

            report = scan_canonical_gc(
                plan.repo, apply=True, keep_last=plan.keep, now=plan.now,
                referenced_digests=frozenset((plan.canonical or {}).get("digests", [])),
            )
            cache_root = _cache_root(Path(plan.common_dir))
            sizes = {item.path: item.bytes for item in canonical}
            for gone in list(report.removed) + list(report.recovered):
                path = str(cache_root / gone.relative_path)
                result.removed.append(path)
                result.removed_bytes += sizes.get(path, 0)
            result.errors.extend(report.errors)
        except Exception as exc:  # noqa: BLE001
            result.errors.append("canonical gc failed: %s" % exc)
    return result


def startup_gc(repo: str, *, max_age: float = STALE_AFTER_SECONDS) -> List[str]:
    """Best-effort reclaim of stale scratch trees and orphan locks. Never raises, never drops a base."""
    try:
        plan = plan_gc(repo, max_age=max_age, include_bases=False)
        return apply_gc(plan).removed
    except (GitDiscoveryError, GitIdentityError, OSError, ValueError):
        return []
    except Exception:  # noqa: BLE001 - a housekeeping failure must never break an index
        return []


__all__ = [
    "DEFAULT_KEEP", "GcItem", "GcPlan", "GcResult", "SCHEMA", "STALE_AFTER_SECONDS",
    "apply_gc", "newest_mtime", "plan_gc", "process_inside", "referenced_keys", "startup_gc",
    "tree_size",
]
