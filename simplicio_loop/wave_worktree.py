"""Worktree-parallel wave dispatch with serial integration (issue: wave perf).

``simplicio-loop wave`` fans independent tasks out into their own git
worktrees, runs them concurrently (bounded by an ``asyncio.Semaphore``), then
integrates every worker's result back into the main repo **serially, in task
order** — the only step that is allowed to touch the shared tree. A worker
whose patch no longer applies cleanly (the integrated tree moved under it)
falls back to a serial re-run of that one task's edit-plan directly on the
now-integrated tree, instead of failing the whole wave.

Tasks whose edit-plan paths overlap are grouped into the same lane (and run
in that lane, in order) so two workers never race on one file; only
path-disjoint lanes get concurrency. This module is intentionally
self-contained: it does not touch the Mapper-lease/journal machinery in
``runner.py`` and is stdlib-only (``asyncio`` + ``subprocess`` + ``os``/``pathlib``).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

SCHEMA = "simplicio.wave-worktree/v1"
# A caller's own state seeded into a lane worktree (e.g. a host's run receipts
# copied in so its per-task operator dispatch can write real receipts there)
# must never be captured in the lane's integration patch.
EXCLUDED_DIFF_PATH = ".simplicio-loop"


# --------------------------------------------------------------------------
# 1. Disjoint-path lane grouping (pure, order-preserving, union-find).
# --------------------------------------------------------------------------

def group_disjoint_tasks(task_paths: Sequence[Sequence[str]]) -> List[List[int]]:
    """Group 1-based task indices into ordered lanes by edit-plan path overlap.

    Two tasks that touch any path in common land in the same lane, in the
    order they were given; a task with no path in common with any earlier
    task opens a new lane. Lanes are independent of each other and safe to
    run concurrently; tasks inside one lane must run in order (same file).
    """
    n = len(task_paths)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    owner: Dict[str, int] = {}
    for i, paths in enumerate(task_paths):
        for raw in paths:
            path = str(raw).strip()
            if not path:
                continue
            if path in owner:
                union(i, owner[path])
            else:
                owner[path] = i

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i + 1)
    return [groups[root] for root in sorted(groups, key=lambda root: groups[root][0])]


# --------------------------------------------------------------------------
# 2. Shared default-branch artifact cache (Mapper/Fast survey, built once).
# --------------------------------------------------------------------------

def default_branch_commit(repo: str | Path, *, timeout: int = 10) -> str:
    """Resolve the default branch's commit SHA.

    Tries ``origin/HEAD`` first (the canonical default branch pointer);
    falls back to the current ``HEAD`` when there is no configured remote
    (a freshly-initialized local fixture, for example).
    """
    repo = str(repo)
    try:
        ref = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=timeout, check=False,
        )
        branch_ref = (ref.stdout or "").strip()
        if ref.returncode == 0 and branch_ref:
            sha = subprocess.run(
                ["git", "rev-parse", branch_ref],
                cwd=repo, capture_output=True, text=True, timeout=timeout, check=False,
            )
            if sha.returncode == 0 and (sha.stdout or "").strip():
                return sha.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return head.stdout.strip() if head.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class ArtifactCache:
    """File-backed survey-artifact cache keyed by default-branch commit SHA.

    Every worker asks for the same key (the default branch's current SHA);
    the first caller builds it, every later caller (this run or a future
    one) reuses the same directory read-only. A stale/missing cache
    rebuilds exactly once, centrally, through ``builder`` — workers never
    invoke Mapper/Fast themselves.
    """

    MARKER = ".complete"

    def __init__(self, cache_root: str | Path) -> None:
        self.cache_root = Path(cache_root)

    def _key_dir(self, key: str) -> Path:
        return self.cache_root / key

    def is_cached(self, key: str) -> bool:
        return (self._key_dir(key) / self.MARKER).exists()

    def get_or_build(self, key: str, builder: Callable[[Path], None]) -> tuple[Path, bool]:
        """Return ``(artifact_dir, cache_hit)``, building at most once per ``key``.

        A best-effort lock file serializes concurrent builders for the same
        key within one process tree; a builder that loses the race still
        gets a correct artifact directory (it just builds redundantly once)
        rather than blocking indefinitely — this cache optimizes the common
        case (one build reused by many readers), it does not need to be a
        perfect distributed lock.
        """
        key = str(key).strip() or "unknown"
        key_dir = self._key_dir(key)
        marker = key_dir / self.MARKER
        if marker.exists():
            return key_dir, True
        self.cache_root.mkdir(parents=True, exist_ok=True)
        key_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.cache_root / f".{key}.lock"
        owns_lock = False
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            owns_lock = True
        except FileExistsError:
            owns_lock = False
        try:
            if marker.exists():
                return key_dir, True
            builder(key_dir)
            marker.write_text(str(time.time()), encoding="utf-8")
            return key_dir, False
        finally:
            if owns_lock:
                try:
                    lock_path.unlink()
                except OSError:
                    pass


# --------------------------------------------------------------------------
# 3. Worktree-parallel lane execution (asyncio) + serial integration.
# --------------------------------------------------------------------------

@dataclass
class LaneResult:
    lane_id: int
    task_indices: List[int]
    status: str  # "applied" | "failed" | "stopped"
    patch: str = ""
    log: str = ""
    worktree: str = ""
    branch: str = ""


ApplyFn = Callable[[Path, Sequence[int]], Awaitable[Mapping[str, Any]]]
ReapplyFn = Callable[[int, Sequence[int]], None]
# Contract for both callbacks: a lane's ``task_indices`` are applied ONE AT A
# TIME, in order, each compiling its edit-plan against whatever tree the
# previous task in that same lane just left (worktree state for ``apply_fn``,
# the just-integrated main-repo tree for ``reapply_fn`` on conflict). Never
# compile task N against a stale snapshot of task N-1's expected result --
# that mismatch is exactly what makes a real dev-cli integration go stale.


async def _run_git(argv: Sequence[str], cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, "", "timeout"
    return process.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


async def run_worktree_lane(
    repo: Path,
    wt_root: Path,
    lane_id: int,
    branch_prefix: str,
    base_commit: str,
    task_indices: Sequence[int],
    apply_fn: ApplyFn,
    verifier_cmd: Optional[str] = None,
    verifier_timeout: int = 300,
    worktree_add_lock: Optional[asyncio.Lock] = None,
) -> LaneResult:
    """Create one lane's worktree, apply its edit-plan, verify, capture a patch.

    ``worktree_add_lock`` (supplied by `run_worktree_wave`, bound to its own
    event loop) serializes only the `git worktree add` step -- `git worktree
    add` races against itself under real concurrency (git's own
    .git/worktrees/<name> bookkeeping is not fully concurrency-safe) -- never
    the actual task work in ``apply_fn``, so lanes still run concurrently.
    """
    repo = Path(repo)
    wt_path = wt_root / f"lane-{lane_id}"
    branch = f"{branch_prefix}-lane-{lane_id}"
    log_parts: List[str] = []

    if worktree_add_lock is not None:
        async with worktree_add_lock:
            rc, out, err = await _run_git(
                ["git", "worktree", "add", "-B", branch, str(wt_path), base_commit], repo,
            )
    else:
        rc, out, err = await _run_git(
            ["git", "worktree", "add", "-B", branch, str(wt_path), base_commit], repo,
        )
    log_parts.append(f"$ git worktree add\n{out}{err}")
    if rc != 0:
        return LaneResult(lane_id, list(task_indices), "failed", log="\n".join(log_parts), branch=branch)

    try:
        outcome = await apply_fn(wt_path, task_indices)
        log_parts.append(f"apply: {outcome!r}")
        applied = bool(outcome.get("applied"))
        if not applied:
            return LaneResult(
                lane_id, list(task_indices), "failed", log="\n".join(log_parts),
                worktree=str(wt_path), branch=branch,
            )

        if verifier_cmd:
            rc, out, err = await asyncio.wait_for(
                _run_verifier(verifier_cmd, wt_path), timeout=verifier_timeout,
            )
            log_parts.append(f"$ {verifier_cmd}\n{out}{err}")
            if rc != 0:
                return LaneResult(
                    lane_id, list(task_indices), "failed", log="\n".join(log_parts),
                    worktree=str(wt_path), branch=branch,
                )

        # A caller may seed the worktree with its own out-of-band state (e.g. the
        # host's run receipts) before/while applying a task -- that state must
        # never leak into the lane's patch or get git-applied onto the main repo.
        rc, out, err = await _run_git(
            ["git", "add", "-A", "--", ".", ":(exclude)" + EXCLUDED_DIFF_PATH], wt_path,
        )
        rc, out, err = await _run_git(
            ["git", "diff", "--binary", base_commit, "--", ".", ":(exclude)" + EXCLUDED_DIFF_PATH],
            wt_path,
        )
        patch = out
        log_parts.append("$ git diff --binary\n" + (err or ""))
        return LaneResult(
            lane_id, list(task_indices), "applied", patch=patch,
            log="\n".join(log_parts), worktree=str(wt_path), branch=branch,
        )
    except Exception as exc:  # noqa: BLE001 - lane failures must not crash the wave
        log_parts.append(f"lane_exception: {type(exc).__name__}: {exc}")
        return LaneResult(
            lane_id, list(task_indices), "failed", log="\n".join(log_parts),
            worktree=str(wt_path), branch=branch,
        )


async def _run_verifier(command: str, cwd: Path) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_shell(
        command, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


async def run_worktree_wave(
    repo: Path,
    run_dir: Path,
    lanes: Sequence[Sequence[int]],
    base_commit: str,
    apply_fn: ApplyFn,
    *,
    branch_prefix: str = "simplicio-wave",
    verifier_for: Optional[Callable[[int], Optional[str]]] = None,
    max_workers: Optional[int] = None,
    stop_requested: Optional[Callable[[], bool]] = None,
) -> List[LaneResult]:
    """Run every lane concurrently, bounded by ``min(cpu_count, len(lanes))``."""
    repo, run_dir = Path(repo), Path(run_dir)
    wt_root = run_dir / "wt"
    wt_root.mkdir(parents=True, exist_ok=True)
    limit = max_workers or min(os.cpu_count() or 1, max(1, len(lanes)))
    semaphore = asyncio.Semaphore(max(1, limit))
    # Created fresh per call (like `semaphore` above), bound only to this
    # call's own running loop -- an asyncio.Lock kept at module scope would
    # otherwise still reference a now-closed event loop on a later call.
    worktree_add_lock = asyncio.Lock()

    async def _bounded(lane_id: int, task_indices: Sequence[int]) -> LaneResult:
        async with semaphore:
            # Checked once the lane is actually about to start (post-admission,
            # not at fan-out time) so a stop requested while earlier lanes were
            # still running is honored for every lane not yet underway --
            # cleanly, before it ever touches git or the shared repo.
            if stop_requested is not None and stop_requested():
                return LaneResult(
                    lane_id, list(task_indices), "stopped", log="stop_requested_before_lane_start",
                )
            verifier_cmd = verifier_for(lane_id) if verifier_for else None
            return await run_worktree_lane(
                repo, wt_root, lane_id, branch_prefix, base_commit,
                task_indices, apply_fn, verifier_cmd=verifier_cmd,
                worktree_add_lock=worktree_add_lock,
            )

    results = await asyncio.gather(
        *[_bounded(lane_id, indices) for lane_id, indices in enumerate(lanes, start=1)]
    )
    return list(results)


def _git_apply(repo: Path, patch: str) -> tuple[bool, str]:
    if not patch.strip():
        return True, ""
    proc = subprocess.run(
        ["git", "apply", "--index", "-"], cwd=str(repo), input=patch,
        capture_output=True, text=True, timeout=60, check=False,
    )
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def integrate_lane_results(
    repo: Path,
    results: Sequence[LaneResult],
    reapply_fn: ReapplyFn,
    *,
    stop_requested: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Serially apply every lane's patch onto the main repo, in lane order.

    A patch that no longer applies (the tree moved under it) is not fatal:
    the lane's edit-plan is re-run directly on the already-integrated tree
    via ``reapply_fn`` (a serial repair, matching the file's own
    "compile binds to the new tree" contract), and the wave continues.

    ``stop_requested``, when given, is polled between lanes -- the only
    integration step that is safe to interrupt without leaving the shared
    tree half-applied, since each lane's patch is applied atomically by
    ``git apply``. A lane already applied before the stop fires is kept
    integrated; every lane not yet reached is left un-integrated and
    reported separately so a retry/resume never re-applies it silently.
    """
    repo = Path(repo)
    integrated: List[int] = []
    repaired: List[int] = []
    failed: List[int] = []
    stopped: List[int] = []
    logs: Dict[int, str] = {}
    for result in results:
        if stop_requested is not None and stop_requested():
            stopped.append(result.lane_id)
            logs[result.lane_id] = "stopped_before_integration"
            continue
        if result.status != "applied":
            failed.append(result.lane_id)
            logs[result.lane_id] = result.log
            continue
        ok, log = _git_apply(repo, result.patch)
        if ok:
            integrated.append(result.lane_id)
            logs[result.lane_id] = log
            continue
        try:
            reapply_fn(result.lane_id, result.task_indices)
            repaired.append(result.lane_id)
            logs[result.lane_id] = f"conflict_repaired: {log}"
        except Exception as exc:  # noqa: BLE001
            failed.append(result.lane_id)
            logs[result.lane_id] = f"conflict_repair_failed: {type(exc).__name__}: {exc}: {log}"
    return {
        "schema": SCHEMA,
        "integrated_lanes": integrated,
        "repaired_lanes": repaired,
        "failed_lanes": failed,
        "stopped_lanes": stopped,
        "logs": logs,
    }


def cleanup_worktrees(repo: Path, results: Sequence[LaneResult]) -> None:
    """Remove every lane's worktree and branch; best-effort, never raises."""
    repo = Path(repo)
    for result in results:
        if result.worktree:
            subprocess.run(
                ["git", "worktree", "remove", "--force", result.worktree],
                cwd=str(repo), capture_output=True, text=True, timeout=30, check=False,
            )
        if result.branch:
            subprocess.run(
                ["git", "branch", "-D", result.branch],
                cwd=str(repo), capture_output=True, text=True, timeout=30, check=False,
            )
