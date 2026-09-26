#!/usr/bin/env python3
"""Crash-safe worktree allocation and composed merge queue primitives.

The coordinator must never ``git checkout`` while workers are running.  This
module keeps ownership in a small, persisted state document and allocates one
worktree/branch per item by default.  The state file is protected by a
cross-process lock, so a second process after a restart can reattach to the
same task/run instead of creating a duplicate checkout.

The queue deliberately stops short of declaring a branch delivered.  A
candidate is only *accepted* after an independently recorded composed
verification; delivery/PR/merge visibility remains the responsibility of the
delivery gate (#142).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


SCHEMA = "simplicio.worktree-merge-queue/v1"
_LOCAL_LOCK = threading.RLock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _norm(value: Any) -> str:
    """Normalize a conflict key without assuming the host filesystem case."""
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text.lower().strip("/")


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._/-]+", "-", str(value or "task"))
    text = text.replace("/", "-").strip("-.")
    return (text or "task")[:80]


@dataclass
class TaskSpec:
    """Frozen task impact used for isolation and deterministic conflict lanes."""

    id: str
    goal: str = ""
    files_affected: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    public_contracts: List[str] = field(default_factory=list)
    migrations: List[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TaskSpec":
        return cls(
            id=str(raw.get("id") or "").strip(),
            goal=str(raw.get("goal") or ""),
            files_affected=[str(x) for x in (raw.get("files_affected") or raw.get("plan_files") or [])],
            symbols=[str(x) for x in (raw.get("symbols") or [])],
            public_contracts=[str(x) for x in (raw.get("public_contracts") or raw.get("contracts") or [])],
            migrations=[str(x) for x in (raw.get("migrations") or [])],
        )

    def conflict_keys(self) -> List[str]:
        rows: List[str] = []
        for prefix, values in (
            ("path", self.files_affected),
            ("symbol", self.symbols),
            ("contract", self.public_contracts),
            ("migration", self.migrations),
        ):
            rows.extend("%s:%s" % (prefix, _norm(value)) for value in values if _norm(value))
        return sorted(set(rows))


@dataclass
class Allocation:
    task_id: str
    run_id: str
    mode: str
    path: str
    branch: str
    base_sha: str
    head_sha: str
    tree_sha: str
    lane: str
    reattached: bool = False
    lock_receipt: Optional[str] = None
    worktree_id: str = ""
    terminal_handle: str = ""
    lease_owner: str = ""


@dataclass
class CleanupReport:
    task_id: str
    removed: bool
    failures: List[str] = field(default_factory=list)
    path: str = ""
    branch: str = ""


class GitError(RuntimeError):
    pass


class WorktreeQueue:
    """Persistent allocator + serial conflict lanes + composed candidate queue."""

    def __init__(
        self,
        repo_root: Optional[str] = None,
        state_path: Optional[str] = None,
        run_id: Optional[str] = None,
        worktree_root: Optional[str] = None,
    ) -> None:
        self.repo_root = os.path.abspath(repo_root or os.getcwd())
        requested_run_id = run_id
        self.run_id = _slug(run_id or "run-%d" % int(time.time()))
        self.state_path = os.path.abspath(
            state_path or os.path.join(self.repo_root, ".simplicio-loop/orchestrator", "worktree-queue.json")
        )
        self.worktree_root = os.path.abspath(
            worktree_root or os.path.join(self.repo_root, ".simplicio-loop/orchestrator", "worktrees", self.run_id)
        )
        self.lock_path = self.state_path + ".lock"
        self._ensure_state()
        # A restarted coordinator that points at the same state file must
        # retain the frozen run identity (and therefore the same worktree
        # root/branch namespace) unless the caller explicitly requests a new
        # run id.
        if requested_run_id is None:
            try:
                with open(self.state_path, encoding="utf-8") as fh:
                    existing_run = json.load(fh).get("run_id")
                if existing_run:
                    self.run_id = _slug(existing_run)
                    self.worktree_root = os.path.abspath(
                        worktree_root or os.path.join(self.repo_root, ".simplicio-loop/orchestrator", "worktrees", self.run_id)
                    )
            except (OSError, ValueError, TypeError):
                pass

    # ---- persistence -------------------------------------------------
    def _ensure_state(self) -> None:
        parent = os.path.dirname(self.state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(self.state_path):
            self._write({
                "schema": SCHEMA,
                "run_id": self.run_id,
                "repo_root": self.repo_root,
                "base_sha": "",
                "created_at": _now(),
                "tasks": {},
                "lanes": {},
                "merge_queue": [],
                "receipts": [],
            })

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        """A lockfile that works in both Windows and POSIX subprocesses."""
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        with _LOCAL_LOCK:
            with open(self.lock_path, "a+b") as handle:
                locked = False
                try:
                    if os.name == "nt":
                        import msvcrt
                        handle.seek(0)
                        if not os.path.getsize(self.lock_path):
                            handle.write(b"0")
                            handle.flush()
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        locked = True
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                        locked = True
                    yield
                finally:
                    if locked:
                        if os.name == "nt":
                            import msvcrt
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.state_path, encoding="utf-8") as fh:
                state = json.load(fh)
            if state.get("schema") != SCHEMA:
                raise ValueError("unsupported worktree queue schema")
            return state
        except (OSError, ValueError, TypeError):
            return {
                "schema": SCHEMA, "run_id": self.run_id, "repo_root": self.repo_root,
                "base_sha": "", "created_at": _now(), "tasks": {}, "lanes": {},
                "merge_queue": [], "receipts": [],
            }

    def _write(self, state: Dict[str, Any]) -> None:
        parent = os.path.dirname(self.state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".worktree-queue-", suffix=".json", dir=parent or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            # Windows scanners and short-lived readers can transiently hold the
            # destination. Retry a bounded number of times; callers still receive
            # the OSError and must fail closed if the state cannot be persisted.
            last_error = None
            for attempt in range(4):
                try:
                    os.replace(temp, self.state_path)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    if attempt < 3:
                        time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def state(self) -> Dict[str, Any]:
        with self._lock():
            return self._read()

    # ---- git ---------------------------------------------------------
    def _git(self, args: Sequence[str], cwd: Optional[str] = None, check: bool = True) -> str:
        proc = subprocess.run(
            ["git"] + list(args), cwd=cwd or self.repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if check and proc.returncode:
            raise GitError("git %s failed (%d): %s" % (" ".join(args), proc.returncode, proc.stderr.strip()))
        return proc.stdout.strip()

    def _sha(self, ref: str = "HEAD", cwd: Optional[str] = None) -> str:
        return self._git(["rev-parse", ref], cwd=cwd)

    def _tree_sha(self, cwd: str) -> str:
        return self._git(["rev-parse", "HEAD^{tree}"], cwd=cwd)

    def _branch_path(self, task_id: str) -> str:
        return os.path.join(self.worktree_root, _slug(task_id))

    def _branch_name(self, task_id: str) -> str:
        return "simplicio/%s/%s" % (self.run_id, _slug(task_id))

    # ---- conflict lanes ---------------------------------------------
    @staticmethod
    def conflict_graph(tasks: Iterable[TaskSpec]) -> Dict[str, List[str]]:
        rows = list(tasks)
        graph = {task.id: set() for task in rows}
        keys = {task.id: set(task.conflict_keys()) for task in rows}
        for idx, left in enumerate(rows):
            for right in rows[idx + 1:]:
                if keys[left.id].intersection(keys[right.id]):
                    graph[left.id].add(right.id)
                    graph[right.id].add(left.id)
        return {task_id: sorted(neighbors) for task_id, neighbors in graph.items()}

    @classmethod
    def conflict_lanes(cls, tasks: Iterable[TaskSpec]) -> Dict[str, str]:
        rows = list(tasks)
        graph = cls.conflict_graph(rows)
        lanes: Dict[str, str] = {}
        for task in sorted(rows, key=lambda x: x.id):
            if task.id in lanes:
                continue
            stack = [task.id]
            component: List[str] = []
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.append(current)
                stack.extend(graph.get(current, []))
            lane = "lane-" + _sha256(sorted(component))[:12]
            for task_id in component:
                lanes[task_id] = lane
        return lanes

    def register_tasks(self, tasks: Iterable[TaskSpec], base_sha: Optional[str] = None) -> Dict[str, str]:
        rows = list(tasks)
        lanes = self.conflict_lanes(rows)
        with self._lock():
            state = self._read()
            base = base_sha or state.get("base_sha") or self._sha()
            if state.get("base_sha") and base_sha and state.get("base_sha") != base_sha:
                raise ValueError("frozen base SHA mismatch: %s != %s" % (base_sha, state.get("base_sha")))
            if not state.get("base_sha"):
                state["base_sha"] = base
            state.setdefault("lanes", {}).update(lanes)
            for task in rows:
                entry = state.setdefault("tasks", {}).setdefault(task.id, {
                    "task_id": task.id, "run_id": self.run_id, "status": "planned",
                    "mode": "worktree", "created_at": _now(),
                })
                entry["conflict_keys"] = task.conflict_keys()
                entry["lane"] = lanes[task.id]
                entry["goal"] = task.goal
            self._write(state)
        return lanes

    # ---- allocation --------------------------------------------------
    def allocate(
        self,
        task: TaskSpec,
        base_sha: Optional[str] = None,
        isolation: str = "worktree",
        shared_policy: bool = False,
    ) -> Allocation:
        if not task.id:
            raise ValueError("task id is required")
        if isolation not in ("worktree", "shared"):
            raise ValueError("isolation must be 'worktree' or 'shared'")
        if isolation == "shared" and not shared_policy:
            raise ValueError("shared checkout requires explicit shared_policy=True")
        with self._lock():
            state = self._read()
            base = base_sha or state.get("base_sha") or self._sha()
            if state.get("base_sha") and base_sha and state.get("base_sha") != base_sha:
                raise ValueError("frozen base SHA mismatch: %s != %s" % (base_sha, state.get("base_sha")))
            state["base_sha"] = state.get("base_sha") or base
            lanes = state.setdefault("lanes", {})
            lane = lanes.get(task.id) or self.conflict_lanes([task]).get(task.id)
            lanes[task.id] = lane
            existing = state.setdefault("tasks", {}).get(task.id)
            if (existing and existing.get("status") not in ("cleaned", "cleanup-failed")
                    and existing.get("path") and existing.get("branch")):
                path = existing["path"]
                if os.path.isdir(path):
                    existing.setdefault("worktree_id", "%s:%s" % (self.run_id, _slug(task.id)))
                    existing.setdefault("terminal_handle", "")
                    existing.setdefault("lease", {
                        "schema": "simplicio.worktree-lease/v1", "owner": self.run_id,
                        "status": "held", "acquired_at": _now(),
                    })
                    allocation = self._allocation_from_entry(existing, reattached=True)
                    state["tasks"][task.id]["last_seen_at"] = _now()
                    self._write(state)
                    return allocation
            if isolation == "shared":
                path = self.repo_root
                branch = self._branch_name(task.id)
                receipt = self._acquire_shared_receipt(task.id, state)
                head = self._sha("HEAD", cwd=path)
                entry = self._entry(task, path, branch, base, head, self._tree_sha(path), lane,
                                    mode="shared", lock_receipt=receipt)
            else:
                path = self._branch_path(task.id)
                branch = self._branch_name(task.id)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                # Never checkout in the coordinator.  git worktree add creates
                # the worker's own checkout and leaves the coordinator untouched.
                try:
                    self._git(["worktree", "add", "--quiet", "-b", branch, path, base])
                except GitError as first:
                    # Restart/idempotency: a pre-existing owned branch can be
                    # attached without changing its commit or the coordinator.
                    if "already exists" not in str(first).lower():
                        raise
                    if not os.path.isdir(path):
                        self._git(["worktree", "add", "--quiet", path, branch])
                    else:
                        raise
                head = self._sha("HEAD", cwd=path)
                entry = self._entry(task, path, branch, base, head, self._tree_sha(path), lane)
            state.setdefault("tasks", {})[task.id] = entry
            self._write(state)
            return self._allocation_from_entry(entry, reattached=False)

    def _entry(
        self, task: TaskSpec, path: str, branch: str, base: str, head: str, tree: str,
        lane: str, mode: str = "worktree", lock_receipt: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "task_id": task.id, "run_id": self.run_id, "mode": mode,
            "path": os.path.abspath(path), "branch": branch,
            "base_sha": base, "head_sha": head, "tree_sha": tree, "lane": lane,
            "status": "allocated", "owned": True, "created_at": _now(),
            "lock_receipt": lock_receipt,
            "conflict_keys": task.conflict_keys(),
            "worktree_id": "%s:%s" % (self.run_id, _slug(task.id)),
            "terminal_handle": "",
            "lease": {"schema": "simplicio.worktree-lease/v1", "owner": self.run_id,
                       "status": "held", "acquired_at": _now()},
        }

    def _allocation_from_entry(self, entry: Mapping[str, Any], reattached: bool) -> Allocation:
        return Allocation(
            task_id=str(entry.get("task_id")), run_id=str(entry.get("run_id") or self.run_id),
            mode=str(entry.get("mode") or "worktree"), path=str(entry.get("path") or ""),
            branch=str(entry.get("branch") or ""), base_sha=str(entry.get("base_sha") or ""),
            head_sha=str(entry.get("head_sha") or ""), tree_sha=str(entry.get("tree_sha") or ""),
            lane=str(entry.get("lane") or ""), reattached=reattached,
            lock_receipt=entry.get("lock_receipt"),
            worktree_id=str(entry.get("worktree_id") or ""),
            terminal_handle=str(entry.get("terminal_handle") or ""),
            lease_owner=str((entry.get("lease") or {}).get("owner") or ""),
        )

    def _acquire_shared_receipt(self, task_id: str, state: Dict[str, Any]) -> str:
        receipt_dir = os.path.join(os.path.dirname(self.state_path), "shared-locks", self.run_id)
        os.makedirs(receipt_dir, exist_ok=True)
        # One lock covers the shared checkout.  This intentionally serializes
        # even disjoint tasks in the explicit fallback mode; callers can only
        # release it through teardown after their commit/receipt is complete.
        path = os.path.join(receipt_dir, "shared-checkout.lock.json")
        if os.path.exists(path):
            try:
                old = json.load(open(path, encoding="utf-8"))
                supplied_sha = str(old.pop("receipt_sha", ""))
                if (supplied_sha and supplied_sha == _sha256(old)
                        and old.get("run_id") == self.run_id
                        and old.get("task_id") == task_id
                        and old.get("repo_root") == self.repo_root):
                    return path
            except (OSError, ValueError):
                pass
            raise RuntimeError("shared checkout lock is already owned: %s" % path)
        payload = {"schema": "simplicio.shared-checkout-lock/v1", "task_id": task_id,
                   "run_id": self.run_id, "repo_root": self.repo_root, "acquired_at": _now()}
        payload["receipt_sha"] = _sha256(payload)
        with open(path, "x", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        return path

    def snapshot(self, task_id: str) -> Allocation:
        with self._lock():
            state = self._read()
            entry = state.get("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            path = entry.get("path") or self.repo_root
            head = self._sha("HEAD", cwd=path)
            tree = self._tree_sha(path)
            entry["head_sha"], entry["tree_sha"], entry["last_seen_at"] = head, tree, _now()
            self._write(state)
            return self._allocation_from_entry(entry, reattached=False)

    def record_context(self, task_id: str, context: Mapping[str, Any]) -> Dict[str, Any]:
        """Persist the operator context that was handed to an allocated worker.

        The queue owns the durable allocation record, so operator receipts must not rely on
        an in-memory scheduler map.  Recording context is idempotent for the same task and
        replaces only the context envelope; allocation, lane, and merge metadata remain
        untouched.
        """
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        payload = dict(context or {})
        payload.setdefault("schema", "simplicio.operator-worktree-context/v1")
        payload.setdefault("task_id", task_id)
        with self._lock():
            state = self._read()
            entry = state.setdefault("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            entry["operator_context"] = payload
            entry["terminal_handle"] = str(payload.get("terminal_handle") or entry.get("terminal_handle") or "")
            lease = entry.setdefault("lease", {})
            lease.update({
                "schema": "simplicio.worktree-lease/v1",
                "owner": str(payload.get("lease_owner") or lease.get("owner") or self.run_id),
                "status": "active" if payload.get("active", True) else "released",
                "updated_at": _now(),
            })
            entry["context_recorded_at"] = _now()
            self._write(state)
        return payload

    def record_generation_binding(
        self, task_id: str, binding: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Persist the canonical Mapper/Fast pin handed to one worker.

        The queue does not build or promote generations.  It records the
        already-verified binding so a later merge candidate proves which
        immutable base and isolated overlay the worker used.
        """
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        payload = dict(binding or {})
        if payload.get("schema") != "simplicio.loop.generation-binding/v1":
            raise ValueError("unsupported generation binding schema")
        if str(payload.get("candidate_id") or "") != task_id:
            raise ValueError("generation binding candidate mismatch")
        if not str(payload.get("canonical_cache_key") or ""):
            raise ValueError("generation binding canonical cache key is required")
        if not str(payload.get("mapper_generation") or "") or not str(
            payload.get("fast_generation") or ""
        ):
            raise ValueError("generation binding generations are required")
        if not str(payload.get("receipt_hash") or ""):
            raise ValueError("generation binding receipt hash is required")
        with self._lock():
            state = self._read()
            entry = state.setdefault("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            previous = entry.get("generation_binding")
            if previous is not None and previous != payload:
                raise ValueError("generation binding is already pinned differently")
            entry["generation_binding"] = payload
            entry["generation_binding_hash"] = str(payload["receipt_hash"])
            entry["generation_recorded_at"] = _now()
            self._write(state)
        return dict(payload)

    # ---- composed merge queue ---------------------------------------
    def enqueue_merge(self, task_id: str, target_ref: str = "HEAD") -> Dict[str, Any]:
        with self._lock():
            state = self._read()
            entry = state.get("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            current_base = self._sha(target_ref)
            head = self._sha("HEAD", cwd=entry.get("path") or self.repo_root)
            candidate = {
                "task_id": task_id, "run_id": self.run_id, "branch": entry.get("branch"),
                "base_sha": entry.get("base_sha"), "head_sha": head, "target_ref": target_ref,
                "queued_at": _now(), "status": "queued",
            }
            binding = entry.get("generation_binding")
            if binding is not None:
                if str(binding.get("candidate_id") or "") != task_id:
                    raise ValueError("generation binding candidate mismatch")
                candidate["generation_binding"] = {
                    "schema": binding.get("schema"),
                    "mapper_generation": binding.get("mapper_generation"),
                    "fast_generation": binding.get("fast_generation"),
                    "canonical_cache_key": binding.get("canonical_cache_key"),
                    "overlay_path": binding.get("overlay_path"),
                    "receipt_hash": binding.get("receipt_hash"),
                }
            if current_base != entry.get("base_sha"):
                candidate["status"] = "repair-required"
                candidate["reason_code"] = "base-drift"
                candidate["repair_handoff"] = self._write_repair_handoff(candidate, current_base)
                entry["status"] = "repair-required"
            else:
                entry["status"] = "queued"
            state.setdefault("merge_queue", [])
            # Do not enqueue duplicate candidates after a restart.
            queue = state["merge_queue"]
            if not any(x.get("task_id") == task_id and x.get("head_sha") == head for x in queue):
                queue.append(candidate)
            self._write(state)
            return candidate

    def _write_repair_handoff(self, candidate: Mapping[str, Any], current_base: str) -> str:
        directory = os.path.join(os.path.dirname(self.state_path), "handoff", self.run_id)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.json" % _slug(str(candidate.get("task_id"))))
        payload = {
            "schema": "simplicio.merge-repair-handoff/v1", "created_at": _now(),
            "task_id": candidate.get("task_id"), "run_id": self.run_id,
            "branch": candidate.get("branch"), "head_sha": candidate.get("head_sha"),
            "frozen_base_sha": candidate.get("base_sha"), "current_base_sha": current_base,
            "reason_code": "base-drift",
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        return path

    def record_composed_verification(
        self, task_id: str, passed: bool, suite: str = "composed", details: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock():
            state = self._read()
            entry = state.get("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            queue = next((x for x in reversed(state.get("merge_queue", [])) if x.get("task_id") == task_id), None)
            if not queue:
                raise ValueError("task is not queued for merge: %s" % task_id)
            if queue.get("status") != "queued":
                raise ValueError("candidate is not merge-queued: %s" % queue.get("status"))
            previous = state.get("receipts", [])[-1].get("receipt_sha") if state.get("receipts") else ""
            receipt = {
                "schema": "simplicio.composed-verification/v1", "task_id": task_id,
                "run_id": self.run_id, "suite": suite, "passed": bool(passed),
                "branch": queue.get("branch"), "base_sha": queue.get("base_sha"),
                "head_sha": queue.get("head_sha"),
                "worktree_path": entry.get("path") or "",
                "lane": entry.get("lane") or "",
                "tree_sha": entry.get("tree_sha") or "",
                "details": dict(details or {}),
                "previous_receipt_sha": previous, "recorded_at": _now(),
            }
            receipt["receipt_sha"] = _sha256(receipt)
            directory = os.path.join(os.path.dirname(self.state_path), "receipts", self.run_id)
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "%s-%s.json" % (_slug(task_id), receipt["receipt_sha"][:12]))
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(receipt, fh, indent=2, sort_keys=True)
                fh.write("\n")
            receipt["path"] = path
            state.setdefault("receipts", []).append(receipt)
            queue["status"] = "accepted" if passed else "verification-failed"
            queue["receipt_sha"] = receipt["receipt_sha"]
            queue["receipt_path"] = path
            entry["status"] = queue["status"]
            self._write(state)
            return receipt

    def composed_candidates(self) -> List[Dict[str, Any]]:
        state = self.state()
        return [dict(x) for x in state.get("merge_queue", []) if x.get("status") == "accepted"]

    def run_composed_verification(
        self,
        task_id: str,
        commands: Sequence[Sequence[str]],
        suite: str = "composed",
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Run the supplied suite/flow/impact commands in the candidate tree.

        The command argv is recorded in the receipt, together with bounded
        stdout/stderr digests.  Callers can pass several independent checks;
        all must pass for the candidate to become ``accepted``.  Commands are
        argv arrays (never shell strings) so task data cannot inject a shell.
        """
        state = self.state()
        entry = state.get("tasks", {}).get(task_id)
        if not entry:
            raise KeyError("unknown task: %s" % task_id)
        outcomes: List[Dict[str, Any]] = []
        for command in commands:
            argv = [str(part) for part in command]
            if not argv:
                outcomes.append({"command": [], "returncode": 2, "stderr": "empty command"})
                continue
            try:
                proc = subprocess.run(
                    argv, cwd=entry.get("path") or self.repo_root,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=timeout, close_fds=True,
                )
                out, err = (proc.stdout or "")[-4000:], (proc.stderr or "")[-4000:]
                outcomes.append({"command": argv, "returncode": proc.returncode,
                                 "stdout": out, "stderr": err,
                                 "output_sha": _sha256({"stdout": out, "stderr": err})})
            except (OSError, subprocess.TimeoutExpired) as exc:
                outcomes.append({"command": argv, "returncode": 124, "stderr": str(exc)})
        passed = bool(outcomes) and all(row.get("returncode") == 0 for row in outcomes)
        return self.record_composed_verification(
            task_id, passed, suite=suite,
            details={"commands": outcomes, "all_checks_passed": passed},
        )

    # ---- cleanup -----------------------------------------------------
    def record_cleanup_receipt(self, task_id: str, receipt: Mapping[str, Any]) -> Dict[str, Any]:
        """Persist explicit terminal/commit/PR/no-change evidence for safe teardown."""
        required = ("worktree_id", "terminal_handle", "lease_owner", "cleanup_decision", "reason")
        payload = dict(receipt or {})
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError("cleanup receipt missing: %s" % ",".join(missing))
        if payload.get("cleanup_decision") != "cleanup":
            raise ValueError("cleanup receipt decision must be cleanup")
        payload.setdefault("schema", "simplicio.worktree-cleanup-receipt/v1")
        payload["task_id"] = str(task_id)
        payload["receipt_sha"] = _sha256(payload)
        with self._lock():
            state = self._read()
            entry = state.setdefault("tasks", {}).get(task_id)
            if not entry:
                raise KeyError("unknown task: %s" % task_id)
            if str(payload.get("worktree_id")) != str(entry.get("worktree_id") or ""):
                raise ValueError("cleanup receipt worktree_id mismatch")
            if str(payload.get("lease_owner")) != str((entry.get("lease") or {}).get("owner") or ""):
                raise ValueError("cleanup receipt lease_owner mismatch")
            if str(payload.get("terminal_handle")) != str(entry.get("terminal_handle") or ""):
                raise ValueError("cleanup receipt terminal_handle mismatch")
            entry["cleanup_receipt"] = payload
            entry["cleanup_receipt_sha"] = payload["receipt_sha"]
            self._write(state)
        return payload

    def teardown(self, task_id: str, delete_branch: bool = False) -> CleanupReport:
        with self._lock():
            state = self._read()
            entry = state.get("tasks", {}).get(task_id)
            if not entry:
                return CleanupReport(task_id=task_id, removed=False, failures=["unknown-task"])
            failures: List[str] = []
            path, branch = str(entry.get("path") or ""), str(entry.get("branch") or "")
            lease = entry.get("lease") or {}
            context = entry.get("operator_context") or {}
            if str(lease.get("status") or "").lower() == "active" or context.get("active") is True:
                failures.append("active-worktree")
            if path and os.path.isdir(path) and not failures:
                try:
                    if self._git(["status", "--porcelain"], cwd=path):
                        failures.append("uncommitted-changes")
                except (GitError, OSError) as exc:
                    failures.append("status-unavailable: %s" % exc)
            if context and not failures and not entry.get("cleanup_receipt"):
                failures.append("missing-cleanup-receipt")
            if failures:
                entry["status"] = "cleanup-blocked"
                entry["cleanup_at"] = _now()
                entry["cleanup_failures"] = failures
                self._write(state)
                return CleanupReport(task_id=task_id, removed=False, failures=failures, path=path, branch=branch)
            if entry.get("mode") == "shared":
                receipt = entry.get("lock_receipt") or ""
                if receipt and os.path.exists(receipt):
                    try:
                        expected = Path(os.path.dirname(self.state_path), "shared-locks", self.run_id,
                                        "shared-checkout.lock.json").resolve()
                        actual = Path(receipt).resolve()
                        if actual != expected:
                            failures.append("lock-receipt-path-not-owned")
                            payload = {}
                        else:
                            payload = json.loads(actual.read_text(encoding="utf-8"))
                        supplied = str(payload.pop("receipt_sha", ""))
                        if actual == expected and (not supplied or supplied != _sha256(payload)):
                            failures.append("lock-receipt-hash-mismatch")
                        elif actual == expected and (payload.get("run_id") != self.run_id or payload.get("task_id") != task_id
                                or payload.get("repo_root") != self.repo_root):
                            failures.append("lock-receipt-owner-mismatch")
                        elif actual == expected:
                            actual.unlink()
                    except (OSError, ValueError) as exc:
                        failures.append("lock-release: %s" % exc)
            elif path:
                # Guard against a malformed state file ever removing a path
                # outside this run's owned worktree root.
                root = os.path.abspath(self.worktree_root) + os.sep
                if not os.path.abspath(path).startswith(root):
                    failures.append("path-not-owned")
                elif os.path.isdir(path):
                    try:
                        self._git(["worktree", "remove", "--force", path])
                    except (GitError, OSError) as exc:
                        failures.append("worktree-remove: %s" % exc)
            if delete_branch and branch.startswith("simplicio/%s/" % self.run_id):
                try:
                    self._git(["branch", "-D", branch])
                except GitError as exc:
                    failures.append("branch-remove: %s" % exc)
            entry["status"] = "cleaned" if not failures else "cleanup-failed"
            entry["cleanup_at"] = _now()
            entry["cleanup_failures"] = failures
            try:
                self._write(state)
            except OSError as exc:
                failures.append("state-write: %s" % exc)
            return CleanupReport(task_id=task_id, removed=not failures, failures=failures, path=path, branch=branch)

    def cleanup_orphans(self, task_ids: Optional[Iterable[str]] = None) -> List[CleanupReport]:
        """Teardown only records owned by this run; unknown worktrees are untouched."""
        state = self.state()
        wanted = set(task_ids or state.get("tasks", {}).keys())
        reports: List[CleanupReport] = []
        for task_id, entry in sorted(state.get("tasks", {}).items()):
            if task_id not in wanted or not entry.get("owned") or entry.get("status") == "cleaned":
                continue
            reports.append(self.teardown(task_id))
        return reports


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("graph", "selftest"))
    parser.add_argument("--tasks", help="JSON array of task impact objects")
    args = parser.parse_args()
    if args.command == "selftest":
        return selftest()
    if not args.tasks:
        parser.error("graph requires --tasks")
    with open(args.tasks, encoding="utf-8") as fh:
        tasks = [TaskSpec.from_mapping(x) for x in json.load(fh)]
    print(json.dumps({"graph": WorktreeQueue.conflict_graph(tasks),
                      "lanes": WorktreeQueue.conflict_lanes(tasks)}, indent=2, sort_keys=True))
    return 0


def selftest() -> int:
    """Small deterministic smoke test, useful on Windows and POSIX."""
    with tempfile.TemporaryDirectory(prefix="simplicio-worktree-queue-") as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "simplicio-test"], cwd=repo, check=True)
        Path(repo, "README").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        q = WorktreeQueue(repo, os.path.join(tmp, "state.json"), "selftest")
        a = TaskSpec("A", files_affected=["src/a.py"])
        b = TaskSpec("B", files_affected=["src/b.py"])
        c = TaskSpec("C", files_affected=["src/a.py"], public_contracts=["api.v1"])
        assert WorktreeQueue.conflict_graph([a, b, c])["A"] == ["C"]
        assert WorktreeQueue.conflict_lanes([a, b, c])["A"] == WorktreeQueue.conflict_lanes([a, b, c])["C"]
        alloc = q.allocate(a)
        assert alloc.path != repo and alloc.branch.startswith("simplicio/selftest/")
        assert q.allocate(a).reattached
        q.enqueue_merge("A")
        receipt = q.record_composed_verification("A", True, details={"flow": "green"})
        assert receipt["receipt_sha"] and q.composed_candidates()[0]["status"] == "accepted"
        result = q.teardown("A")
        assert result.removed, result.failures
    print("selftest: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
