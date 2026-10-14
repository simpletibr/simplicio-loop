"""Worktree and wave dispatch: Prism scheduler, isolated run contexts and the wave worktree dispatcher (#1606)."""
from __future__ import annotations

import asyncio
import json
import hashlib
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
from .evidence import build_evidence_receipt
from . import local_capacity, wave_worktree
from .runner_core import (
    _subprocess_env,
    _load_json,
    _write_json,
    _append_jsonl,
    _repo_fingerprint,
)
from .runner_lifecycle import _emit_event
from .runner_lane import _run_operator_item_process

def _resolve_dispatch_mode() -> str:
    """Resolve the per-task child-execution mode every dispatch path shares.

    ``process`` (the default) supervises each task in its own child process,
    same as the classic ``dispatch_operator_batch`` path; ``thread`` is the
    opt-out used by unit tests that stub the per-task worker with a local
    closure (unpicklable across a real process boundary).
    """
    dispatch_mode = os.environ.get("SIMPLICIO_LOOP_DISPATCH_MODE", "process").strip().lower()
    if dispatch_mode not in {"process", "thread"}:
        raise ValueError("SIMPLICIO_LOOP_DISPATCH_MODE must be process or thread")
    return dispatch_mode


def _load_prior_dispatch_records(
    journal_path: Path,
) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Return the last persisted attempt record per (repo, run_id, task_index).

    Shared by every dispatch path that persists to one run's
    ``operator-batch.jsonl`` (`_persist_attempt`'s file), so a resumed batch
    -- whichever path dispatches it -- recognizes the same durably-succeeded
    tasks and never re-dispatches them.
    """
    prior: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    if not journal_path.exists():
        return prior
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            key = (str(rec.get("repo")), str(rec.get("run_id")), int(rec.get("task_index")))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        prior[key] = rec
    return prior


def _operator_worker_limit(requested: Optional[int], item_count: int) -> int:
    """Resolve logical demand; the physical admission monitor governs live work."""
    if item_count <= 0:
        return 0
    if requested is None or requested <= 0:
        raw = os.environ.get("SIMPLICIO_LOOP_OPERATOR_WORKERS", "").strip()
        try:
            requested = int(raw) if raw else item_count
        except ValueError:
            raise ValueError("SIMPLICIO_LOOP_OPERATOR_WORKERS must be an integer") from None
        if requested <= 0:
            requested = item_count
    return max(1, min(int(requested), item_count))


def _build_native_prism_scheduler(
    items: Sequence[Mapping[str, Any]],
    worker_limit: int,
    *,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
) -> tuple[Any, str, dict[str, Any]]:
    """Build the native Prism admission authority for a local operator batch.

    Prism is intentionally an in-process contract here: it admits independent
    work up to the measured worker limit, preserves dependency/conflict edges,
    and leaves the existing worktree/operator bridge as the mutation boundary.
    This keeps the fast local path useful without requiring cloud workers or
    an Orca client, while physical admission remains separately governed.
    """
    from .prism_contracts import (
        TASK_STATES,
        PrismExecution,
        SlotSupervisor,
        TaskOwnership,
    )
    from .prism_budgets import AdaptiveBudgetGovernor, BudgetSample
    from .prism_scheduler import PrismPolicy, PrismScheduler, ResourceVector, ScheduledTask

    if not items or worker_limit < 1:
        raise ValueError("native Prism requires work and a positive worker limit")
    from .local_capacity import PhysicalAdmissionMonitor

    capacity_root = Path(str(items[0].get("repo") or ".")).resolve()
    # Queue/worktree adapters may hand the scheduler a path that is created only
    # after admission. Probe the nearest existing ancestor instead of treating
    # that normal pre-launch state as an unavailable disk signal.
    while not capacity_root.exists() and capacity_root != capacity_root.parent:
        capacity_root = capacity_root.parent
    monitor_kwargs = local_capacity.physical_monitor_kwargs(physical_monitor_kwargs)
    if monitor_kwargs:
        capacity_monitor = PhysicalAdmissionMonitor(
            str(capacity_root), worker_limit, **monitor_kwargs,
        )
    else:
        capacity_monitor = PhysicalAdmissionMonitor(
            str(capacity_root), worker_limit,
        )
    capacity_sample = capacity_monitor.refresh(force=True)
    # Keep one logical scheduler worker alive so its explicit unavailable sample
    # can produce a blocked admission decision instead of bypassing the receipt.
    worker_limit = max(1, min(int(worker_limit), max(1, capacity_sample.safe_workers)))
    run_id = str(items[0].get("run_id") or "local-batch")
    # Keep logical partitioning independent from physical workers.  A task may
    # provide an explicit partition identity; otherwise derive one from the
    # existing impact/dependency metadata so independent work does not collapse
    # into the historical single supervisor.
    def _partition_key(item: Mapping[str, Any]) -> str:
        spec = item.get("task_spec")
        spec = spec if isinstance(spec, Mapping) else {}
        explicit = (
            spec.get("slot_key") or spec.get("dependency_component")
            or spec.get("repository") or spec.get("repo")
        )
        if explicit:
            return str(explicit).strip()
        paths = spec.get("files_affected") or spec.get("candidate_targets") or ()
        if isinstance(paths, str):
            paths = (paths,)
        first = sorted(str(path).replace("\\", "/") for path in paths if str(path).strip())[:1]
        if first:
            return first[0].split("/", 1)[0]
        return "default"

    partitions: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        partitions.setdefault(_partition_key(item), []).append(item)
    # Logical slots are unbounded.  The measured worker/resource governor below
    # controls physical execution; it must not collapse independent partitions
    # into an artificial overflow slot.
    ordered_partitions = sorted(partitions.items(), key=lambda pair: pair[0])
    recovery_reserve = min(1, max(0, worker_limit - 1))
    validation_reserve = min(1, max(0, worker_limit - recovery_reserve - 1))
    policy = PrismPolicy(
        max_tasks_per_slot=10,
        global_worker_limit=max(1, int(worker_limit)),
        recovery_reserve=recovery_reserve,
        validation_reserve=validation_reserve,
    )
    policy_hash = hashlib.sha256(
        json.dumps({"policy": repr(policy), "run_id": run_id}, sort_keys=True).encode()
    ).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps({"items": [str(item.get("task_id") or "") for item in items]}, sort_keys=True).encode()
    ).hexdigest()
    root = PrismExecution(
        goal_id=run_id,
        owner_agent="simplicio-loop",
        policy_hash=policy_hash,
        config_hash=config_hash,
        source_generation=run_id,
        reducer_ref="simplicio_loop.runner.dispatch_operator_batch",
        budget=(("workers", max(1, int(worker_limit))),),
    )
    governor = AdaptiveBudgetGovernor(policy, relief_samples=2)

    def _budget_sample(sample: Any) -> BudgetSample:
        # Only worker capacity is measured by the local probe. Keep every other
        # governor dimension explicitly unavailable instead of inferring it from
        # an unrelated CPU, memory, or disk value.
        null_reasons = {
            name: "local_probe_not_supported"
            for name in (
                "cpu_millis", "rss_bytes", "io_units", "provider_requests",
                "tokens", "model_slots", "network_queue", "context_tokens",
                "evidence_bytes",
            )
        }
        if sample.safe_workers < 1 or sample.unavailable:
            null_reasons["workers"] = sample.null_reasons.get(
                "workers", "required_capacity_signal_unavailable"
            )
        return BudgetSample(
            workers=int(sample.safe_workers),
            observed_at_ns=int(sample.observed_at_ns),
            null_reasons=null_reasons,
        )

    observation = governor.observe(_budget_sample(capacity_sample))
    scheduler = PrismScheduler(policy, observation=observation)
    slots_by_partition: dict[str, SlotSupervisor] = {}
    for partition, group in ordered_partitions:
        slot = SlotSupervisor(
            parent_prism_id=root.prism_id,
            supervisor_agent=f"simplicio-loop:{partition}",
            capacity=max(10, len(group)),
        )
        scheduler.register_slot(slot)
        slots_by_partition[partition] = slot
    for item in items:
        task_spec = item.get("task_spec")
        task_spec = dict(task_spec) if isinstance(task_spec, Mapping) else {}
        raw_dependencies = task_spec.get("depends_on") or task_spec.get("dependencies") or ()
        if isinstance(raw_dependencies, Mapping):
            raw_dependencies = raw_dependencies.get("items") or ()
        kind = str(task_spec.get("kind") or "implementation")
        if kind not in {"implementation", "recovery", "validation", "review", "integration"}:
            kind = "implementation"
        task_id = str(item.get("task_id") or "")
        slot = slots_by_partition[_partition_key(item)]
        ownership = TaskOwnership(
            task_id=task_id,
            slot_id=slot.slot_id,
            attempt=1,
            owner_agent=str(item.get("worker_id") or "simplicio-local"),
            lease_id=str(item.get("lease_id") or task_id),
            fence=1,
            source_generation=run_id,
            capabilities=("operator", "local", "worktree"),
            allowed_transitions=tuple(sorted(TASK_STATES)),
        )
        scheduler.submit(ScheduledTask(
            task_id=task_id,
            slot_id=slot.slot_id,
            ownership=ownership,
            depends_on=tuple(str(value) for value in raw_dependencies if str(value).strip()),
            hard_conflicts=tuple(str(value) for value in (task_spec.get("hard_conflicts") or ())),
            exclusive_resources=tuple(str(value) for value in (task_spec.get("exclusive_resources") or ())),
            priority=int(task_spec.get("priority") or 0),
            kind=kind,
            resources=ResourceVector(workers=1),
        ))
    capacity_receipt = capacity_sample.to_dict()
    capacity_receipt["budget_governor"] = governor.status()
    capacity_receipt["monitor"] = capacity_monitor.status()
    capacity_receipt["policy"] = {
        "recovery_reserve": policy.recovery_reserve,
        "validation_reserve": policy.validation_reserve,
        "global_worker_limit": policy.global_worker_limit,
    }

    def refresh_capacity(*, force: bool = True) -> None:
        refreshed = capacity_monitor.refresh(force=force)
        scheduler.controller.update(governor.observe(_budget_sample(refreshed)))
        capacity_receipt.clear()
        capacity_receipt.update(refreshed.to_dict())
        capacity_receipt["budget_governor"] = governor.status()
        capacity_receipt["monitor"] = capacity_monitor.status()
        capacity_receipt["policy"] = {
            "recovery_reserve": policy.recovery_reserve,
            "validation_reserve": policy.validation_reserve,
            "global_worker_limit": policy.global_worker_limit,
        }

    # The dispatch bridge calls this before each refill and on the monitor clock.
    # Keeping the hook on the scheduler preserves the existing return contract.
    scheduler.native_capacity_refresh = refresh_capacity
    scheduler.native_capacity_monitor = capacity_monitor
    return scheduler, root.prism_id, capacity_receipt


def _worktree_task_spec(item: Mapping[str, Any]) -> Any:
    """Build the queue's impact contract without importing it at module load time.

    ``runner`` is also shipped as a standalone bundle, so importing the scripts package
    eagerly would make the existing operator API fail in installations that do not ship the
    optional isolation adapter.  The late import keeps that adapter genuinely optional while
    still passing the real ``TaskSpec`` to ``WorktreeQueue`` when it is available.
    """
    try:
        from scripts.worktree_queue import TaskSpec
    except ImportError:  # pragma: no cover - direct scripts/ execution fallback
        from worktree_queue import TaskSpec
    raw = item.get("task_spec")
    if isinstance(raw, TaskSpec):
        return raw
    payload = dict(raw or {}) if isinstance(raw, Mapping) else {}
    task_id = str(item.get("task_id") or "task-%s-%s" % (item.get("run_id"), item.get("task_index")))
    payload.setdefault("id", task_id)
    payload.setdefault("goal", str(item.get("goal") or ""))
    return TaskSpec.from_mapping(payload)


def _allocation_context(allocation: Any, item: Mapping[str, Any]) -> Dict[str, Any]:
    """Reduce an Allocation to JSON-safe, persisted operator context."""
    def value(name: str, default: Any = "") -> Any:
        if isinstance(allocation, Mapping):
            return allocation.get(name, default)
        return getattr(allocation, name, default)

    context = {
        "schema": "simplicio.operator-worktree-context/v1",
        "task_id": str(value("task_id", item.get("task_id") or "")),
        "run_id": str(value("run_id", item.get("run_id") or "")),
        "mode": str(value("mode", item.get("isolation", "worktree")) or item.get("isolation", "worktree")),
        "path": str(value("path", "") or ""),
        "branch": str(value("branch", "") or ""),
        "base_sha": str(value("base_sha", "") or ""),
        "head_sha": str(value("head_sha", "") or ""),
        "tree_sha": str(value("tree_sha", "") or ""),
        "lane": str(value("lane", "") or ""),
        "reattached": bool(value("reattached", False)),
        "lock_receipt": str(value("lock_receipt", "") or ""),
        "worktree_id": str(value("worktree_id", "") or ""),
        "terminal_handle": str(value("terminal_handle", "") or ""),
        "lease_owner": str(value("lease_owner", "") or ""),
        "source_repo": str(item.get("source_repo") or item.get("repo") or ""),
        "source_run_id": str(item.get("source_run_id") or item.get("run_id") or ""),
    }
    return context


def _persist_isolated_run_context(item: Dict[str, Any], context: Dict[str, Any]) -> None:
    """Persist queue context and clone run receipts into an isolated checkout.

    The copy is filesystem-only (no Git subprocess), making this path deterministic in unit
    tests and safe for callers that provide a fake queue.  If the source run is unavailable,
    the context receipt is still written; the operator then fails closed at its normal
    preflight boundary rather than manufacturing a success.
    """
    path = str(context.get("path") or "")
    source_repo = Path(str(context.get("source_repo") or item.get("repo") or "")).resolve()
    run_id = str(item.get("run_id") or context.get("source_run_id") or "")
    if not path:
        return
    target_root = Path(path).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    context_dir = target_root / ".simplicio-loop/orchestrator" / "dispatch-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / (str(context.get("task_id") or item.get("task_index")) + ".json")
    context["context_path"] = str(context_path)
    _write_json(context_path, context)

    source_state_path = source_repo / ".simplicio-loop" / "loop-runs" / run_id / "state.json"
    if source_state_path.exists():
        try:
            source_run = source_state_path.parent
            source_state = _load_json(source_state_path)
            _emit_event(source_run, source_state, "worktree_created",
                        receipt=str(context.get("lock_receipt") or context_path),
                        task_id=str(context.get("task_id") or item.get("task_id") or ""),
                        message="isolated worktree context persisted", worktree=context)
        except (OSError, ValueError, TypeError):
            # The worker's normal receipts remain authoritative if the coordinator is gone.
            pass

    source_run = source_repo / ".simplicio-loop" / "loop-runs" / run_id
    target_run = target_root / ".simplicio-loop" / "loop-runs" / run_id
    if source_run.is_dir() and target_root != source_repo and not target_run.exists():
        target_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_run, target_run)
    manifest_path = target_run / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = _load_json(manifest_path)
            manifest["repo"] = str(target_root)
            manifest["run_id"] = run_id
            _write_json(manifest_path, manifest)
        except (OSError, ValueError, TypeError):
            # The operator's ordinary preflight will emit a durable failure receipt.
            pass


def _prepare_worktree_contexts(normalized: List[Dict[str, Any]], worktree_queue: Any, *, defer_worktrees: bool = False) -> None:
    """Register optional worktrees and defer allocation until an admitted spawn."""
    if worktree_queue is None or not normalized:
        return
    specs = [_worktree_task_spec(item) for item in normalized]
    register = getattr(worktree_queue, "register_tasks", None)
    if callable(register):
        try:
            register(specs)
        except Exception as exc:
            for item in normalized:
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            return
    for item, spec in zip(normalized, specs):
        isolation = str(item.get("isolation") or "worktree").strip().lower()
        if isolation not in {"worktree", "shared"}:
            item["worktree_error"] = "ValueError: unsupported worktree isolation mode"
            continue
        if isolation == "shared" or defer_worktrees:
            # Both shared checkouts and isolated worktrees are allocated only after the
            # immediately preceding admission poll.  This prevents a later pressure sample
            # from leaving an unsent queue lease behind.
            item["worktree_deferred"] = True
            item["isolation_key"] = (
                "worktree:%s" % item.get("task_id")
                if isolation == "worktree" else "%s:%s" % (item.get("repo"), item.get("run_id"))
            )
            continue
        try:
            allocation = worktree_queue.allocate(spec)
        except Exception as exc:
            item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            continue
        context = _allocation_context(allocation, item)
        item["worktree_context"] = context
        item["source_repo"] = str(item.get("repo") or "")
        item["source_run_id"] = str(item.get("run_id") or "")
        # Worktree workers get their own run tree; shared mode intentionally retains the
        # original path and is serialized by the isolation key below.
        if context["mode"] == "worktree" and context["path"]:
            try:
                _persist_isolated_run_context(item, context)
            except Exception as exc:
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            item["repo"] = context["path"]
            item["isolation_key"] = context["path"]
        else:
            item["isolation_key"] = "%s:%s" % (item.get("repo"), item.get("run_id"))
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            try:
                recorder(context["task_id"], context)
            except Exception as exc:
                # Context persistence is a safety gate: do not run an unreceipted isolated
                # worker.  This preserves fail-closed behavior without changing the API.
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"


def _ensure_deferred_worktree_context(item: Dict[str, Any], worktree_queue: Any) -> None:
    """Acquire one deferred queue context immediately before its admitted spawn."""
    if not item.get("worktree_deferred") or item.get("worktree_context") or item.get("worktree_error"):
        return
    try:
        spec = _worktree_task_spec(item)
        isolation = str(item.get("isolation") or "worktree").strip().lower()
        if isolation == "shared":
            allocation = worktree_queue.allocate(spec, isolation="shared", shared_policy=True)
        else:
            allocation = worktree_queue.allocate(spec, isolation="worktree")
        context = _allocation_context(allocation, item)
        item["worktree_context"] = context
        item["source_repo"] = str(item.get("repo") or "")
        item["source_run_id"] = str(item.get("run_id") or "")
        if context["mode"] == "worktree" and context["path"]:
            _persist_isolated_run_context(item, context)
            item["repo"] = context["path"]
            item["isolation_key"] = context["path"]
        else:
            _persist_isolated_run_context(item, context)
            item["isolation_key"] = "%s:%s" % (item.get("repo"), item.get("run_id"))
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            recorder(context["task_id"], context)
    except Exception as exc:
        item["worktree_error"] = f"{type(exc).__name__}: {exc}"


def _release_shared_context(item: Mapping[str, Any], worktree_queue: Any, *, force: bool = False) -> None:
    context = item.get("worktree_context") or {}
    if not force and str(context.get("mode") or "") != "shared":
        return
    task_id = str(context.get("task_id") or item.get("task_id") or "")
    if force and task_id:
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            released = dict(context)
            released["active"] = False
            try:
                recorder(task_id, released)
            except Exception:
                pass
        cleanup = getattr(worktree_queue, "record_cleanup_receipt", None)
        worktree_id = str(context.get("worktree_id") or "")
        lease_owner = str(context.get("lease_owner") or "")
        if callable(cleanup) and worktree_id and lease_owner:
            try:
                cleanup(task_id, {
                    "worktree_id": worktree_id,
                    "terminal_handle": str(context.get("terminal_handle") or ""),
                    "lease_owner": lease_owner,
                    "cleanup_decision": "cleanup",
                    "reason": "cancelled_before_spawn",
                })
            except Exception:
                pass
    teardown = getattr(worktree_queue, "teardown", None)
    if callable(teardown) and task_id:
        try:
            teardown(task_id)
        except Exception:
            # Never mask the operator receipt with cleanup noise.
            pass


def _wave_capacity_admission(
    repo_path: Path,
    lane_count: int,
    requested_workers: Optional[int],
    *,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Resolve lane concurrency through the same physical admission governor
    the classic dispatch path uses (`local_capacity.PhysicalAdmissionMonitor`),
    instead of the raw ``min(cpu_count, len(lanes))`` guess `run_worktree_wave`
    falls back to on its own -- a lane is exactly as much of a live local
    worker (its own worktree + child process) as a classic dispatch item, so
    it must be governed by the same physical evidence, not a fixed request.
    """
    effective_workers = _operator_worker_limit(requested_workers, lane_count)
    if effective_workers <= 0:
        return 0, {
            "admitted": False, "reason_code": "NO_LANES", "reason": "no_lanes", "evidence": {},
        }
    capacity_root = Path(repo_path).resolve()
    while not capacity_root.exists() and capacity_root != capacity_root.parent:
        capacity_root = capacity_root.parent
    monitor_kwargs = local_capacity.physical_monitor_kwargs(physical_monitor_kwargs)
    monitor = local_capacity.PhysicalAdmissionMonitor(
        str(capacity_root), effective_workers, **monitor_kwargs,
    )
    sample = monitor.refresh(force=True)
    effective_workers = max(0, min(effective_workers, int(sample.safe_workers)))
    return effective_workers, monitor.admission_status()


def _seed_wave_lane_run_context(run_dir: Path, run_id: str, worktree_path: Path) -> None:
    """Copy this run's persisted receipts into a lane worktree and repoint its
    manifest at that worktree -- mirrors `_persist_isolated_run_context`'s
    existing single-task isolation trick, so each lane's tasks write real
    per-task operator receipts + evidence inside their own isolated checkout,
    through the exact same `execute_operator` boundary every other dispatch
    path uses.
    """
    target_run = worktree_path / ".simplicio-loop" / "loop-runs" / run_id
    if not target_run.exists():
        target_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, target_run)
    manifest_path = target_run / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = _load_json(manifest_path)
            manifest["repo"] = str(worktree_path)
            manifest["run_id"] = run_id
            _write_json(manifest_path, manifest)
        except (OSError, TypeError, ValueError):
            pass


def _wave_worktree_dispatch(
    *,
    repo_path: Path,
    run_id: str,
    run_dir: Path,
    items: Sequence[Mapping[str, Any]],
    retry_budget: int,
    max_workers: Optional[int],
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    stop_requested: Optional[Callable[[], bool]] = None,
) -> Optional[Dict[str, Any]]:
    """Lane-parallel wave dispatch.

    Groups ``items`` into disjoint-edit-plan-path lanes (`wave_worktree.
    group_disjoint_tasks`). With more than one lane, every lane runs
    concurrently in its own git worktree seeded from this run's current
    receipts (`run_worktree_wave`) -- a lane's own tasks apply ONE AT A TIME,
    in order, through the same per-task retry/dead-letter path
    (`_run_operator_item_process`), so chaining (#1295 ``repo_state_chain``)
    keeps working inside the lane exactly as it does on the shared-run serial
    path. Every lane's resulting patch is then integrated back into the main
    repo serially, in lane order (`integrate_lane_results`); a patch that no
    longer applies (the tree moved under it) re-runs that lane's tasks
    directly on the now-integrated main tree instead of failing the wave.
    Worktrees are removed afterward (`cleanup_worktrees`).

    Every safeguard the classic ``dispatch_operator_batch`` path has applies
    here too, at lane granularity instead of task granularity: lane
    concurrency is admitted by the same physical admission governor
    (`_wave_capacity_admission`, `local_capacity.PhysicalAdmissionMonitor`)
    rather than a raw CPU-count guess; each lane task's mutation runs in its
    own child process by default (`SIMPLICIO_LOOP_DISPATCH_MODE`, reusing
    `_run_operator_item_process` -- no new worker code); every terminal
    per-task record is persisted to this run's own ``operator-batch.jsonl``
    so a resumed batch recognizes durable success; ``stop_requested`` is
    polled before a lane starts and again between integration steps; and a
    caller-declared verifier command (``SIMPLICIO_TEST_CMD``) gates each
    lane's integration through the existing (previously unwired)
    ``verifier_for`` hook.

    Returns ``None`` -- the caller keeps its existing serial path unchanged --
    when there is only one lane (every task shares a file with another),
    this repo is not a git checkout, this run's own journal already shows
    durable progress on one of these items (a resume), or the governor
    reports zero safe workers. Pressure that refuses a fresh admission but
    still reports safe workers does not skip the wave: the lanes run at that
    width and the call returns only after every lane has closed.
    """
    ordered_items = list(items)
    if len(ordered_items) < 2 or not (repo_path / ".git").exists():
        return None
    paths_in_order = [
        [str(path) for path in ((item.get("task_spec") or {}).get("files_affected") or [])]
        for item in ordered_items
    ]
    if any(not paths for paths in paths_in_order):
        return None
    position_lanes = wave_worktree.group_disjoint_tasks(paths_in_order)
    if len(position_lanes) <= 1:
        return None
    lane_task_indices: List[List[int]] = [
        [int(ordered_items[position - 1]["task_index"]) for position in positions]
        for positions in position_lanes
    ]
    items_by_index = {int(item["task_index"]): dict(item) for item in ordered_items}

    journal_path = Path(run_dir).resolve() / "operator-batch.jsonl"
    prior = _load_prior_dispatch_records(journal_path)
    if any(
        prior.get(
            (str(item.get("repo")), str(item.get("run_id")), int(item["task_index"])), {}
        ).get("status") == "succeeded"
        for item in ordered_items
    ):
        # A crash mid-wave (or an already-resumed batch) left durable progress
        # in this exact journal file -- defer to the shared-run serial path,
        # which reads it too (same `journal_dir`) and skips only the
        # already-succeeded tasks instead of re-lane-grouping partial work.
        return None

    effective_workers, capacity_admission = _wave_capacity_admission(
        repo_path, len(lane_task_indices), max_workers,
        physical_monitor_kwargs=physical_monitor_kwargs,
    )
    if not capacity_admission.get("admitted"):
        if effective_workers < 1:
            # Zero safe workers: the classic path owns the typed blocked receipt.
            return None
        # Pressure refused a brand-new admission, but workers are still safe.
        # Keep the wave: lanes run, and this call returns only when they close.
        capacity_admission = dict(capacity_admission)
        capacity_admission["wave_mode"] = "admitted-under-pressure"
        capacity_admission["effective_workers"] = effective_workers

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path), capture_output=True,
        text=True, timeout=15, check=False, env=_subprocess_env(),
    )
    base_commit = (head.stdout or "").strip()
    if head.returncode != 0 or not base_commit:
        return None

    dispatch_mode = _resolve_dispatch_mode()
    process_pool: Optional[ProcessPoolExecutor] = None
    if dispatch_mode == "process":
        pool_kwargs: Dict[str, Any] = {"max_workers": max(1, effective_workers)}
        if os.name == "posix":
            try:
                import multiprocessing as _mp
                if "fork" in _mp.get_all_start_methods():
                    pool_kwargs["mp_context"] = _mp.get_context("fork")
            except (AttributeError, ValueError):
                pass
        process_pool = ProcessPoolExecutor(**pool_kwargs)
        # Force every worker to fork now, on the main thread, before
        # `asyncio.run` below starts its own default-executor threads.
        # `fork()` only duplicates the calling thread; forking later from one
        # of those asyncio worker threads while another thread holds an
        # unrelated interpreter lock (import lock, logging, GC) is a real,
        # intermittent deadlock hazard -- not hypothetical, reproduced empirically
        # while hardening this exact path. A trivial warm-up call sidesteps it
        # by making the fork happen here instead.
        process_pool.submit(int, 0).result()

    def _dispatch_one(lane_item: Mapping[str, Any]) -> List[Dict[str, Any]]:
        # Reuses the exact same child-process worker the classic dispatch
        # path submits to its own ProcessPoolExecutor -- no new worker code.
        if process_pool is not None:
            return process_pool.submit(_run_operator_item_process, dict(lane_item), retry_budget).result()
        return _run_operator_item_process(lane_item, retry_budget)

    test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip()
    lane_verifier_for = (lambda _lane_id, _cmd=test_cmd: _cmd) if test_cmd else None

    lane_records: Dict[Tuple[int, ...], List[Dict[str, Any]]] = {}

    def _run_lane_sync(worktree_path: Path, task_indices: Sequence[int]) -> Dict[str, Any]:
        _seed_wave_lane_run_context(run_dir, run_id, worktree_path)
        records: List[Dict[str, Any]] = []
        applied = True
        for task_index in task_indices:
            lane_item = dict(items_by_index[task_index])
            lane_item["repo"] = str(worktree_path)
            attempts = _dispatch_one(lane_item)
            record = attempts[-1]
            records.append(record)
            if record.get("status") != "succeeded":
                applied = False
                break
        lane_records[tuple(task_indices)] = records
        return {"applied": applied}

    async def apply_fn(worktree_path: Path, task_indices: Sequence[int]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run_lane_sync, worktree_path, list(task_indices))

    def reapply_fn(lane_id: int, task_indices: Sequence[int]) -> None:
        # Conflict repair: this lane's patch no longer applies onto the main repo
        # (an earlier lane's integration moved the tree under it) -- re-run its
        # tasks directly on the now-integrated main tree, serially, through the
        # same per-task operator path, exactly like the existing serial fallback.
        records: List[Dict[str, Any]] = []
        try:
            for task_index in task_indices:
                attempts = _dispatch_one(dict(items_by_index[task_index]))
                record = attempts[-1]
                records.append(record)
                if record.get("status") != "succeeded":
                    raise RuntimeError(
                        "reapply failed for task %d: %s"
                        % (task_index, record.get("error") or record.get("reason_code") or "unknown")
                    )
        finally:
            lane_records[tuple(task_indices)] = records

    try:
        # Worktrees live OUTSIDE the receipts run_dir -- seeding a lane's worktree
        # copies the whole run_dir tree into it (`_seed_wave_lane_run_context`),
        # which would recurse into itself if the worktree root were nested inside
        # run_dir.
        wave_scratch_dir = repo_path / ".simplicio-loop" / "orchestrator" / "wave" / run_id
        results = asyncio.run(wave_worktree.run_worktree_wave(
            repo_path, wave_scratch_dir, lane_task_indices, base_commit, apply_fn,
            max_workers=effective_workers, verifier_for=lane_verifier_for,
            stop_requested=stop_requested,
        ))
        integration = wave_worktree.integrate_lane_results(
            repo_path, results, reapply_fn, stop_requested=stop_requested,
        )
    finally:
        if process_pool is not None:
            process_pool.shutdown(wait=True)
    integrated_lane_ids = set(integration["integrated_lanes"])
    repaired_lane_ids = set(integration.get("repaired_lanes", []))
    stopped_lane_ids = set(integration.get("stopped_lanes", []))

    final_records: List[Dict[str, Any]] = []
    for lane_result in results:
        key = tuple(lane_result.task_indices)
        if lane_result.status == "stopped" or lane_result.lane_id in stopped_lane_ids:
            # Never started, or applied but not yet integrated when the stop
            # fired: none of this lane's work is on the main repo. Record it
            # as held/pending (resumable) -- never as a failure or a
            # dead-letter -- the exact vocabulary `dispatch_operator_batch`
            # already uses for a drained batch.
            for task_index in lane_result.task_indices:
                final_records.append({
                    "schema": "simplicio.operator-worker/v1", "task_index": task_index,
                    "run_id": run_id, "repo": str(repo_path),
                    "status": "pending", "execution_state": "pending",
                    "reason_code": "operator_stop_requested",
                    "drain_status": "held", "dead_letter": False,
                })
            continue
        records = lane_records.get(key) or []
        if lane_result.lane_id in integrated_lane_ids:
            # This lane's patch applied cleanly onto the main repo -- the real
            # per-task receipts it wrote live in the lane's isolated checkout;
            # copy them back so #1295's receipt gate and the oracle see them
            # exactly where every other dispatch path leaves them.
            lane_run = Path(lane_result.worktree) / ".simplicio-loop" / "loop-runs" / run_id
            for task_index in lane_result.task_indices:
                for name in (f"operator-receipt-{task_index}.json", f"task-{task_index}-result.json"):
                    src = lane_run / name
                    if src.is_file():
                        shutil.copy2(src, run_dir / name)
        elif lane_result.lane_id not in repaired_lane_ids:
            # Neither integrated nor repaired: this lane's own apply step or
            # its declared verifier (`SIMPLICIO_TEST_CMD`) failed, so nothing
            # of it ever reached the main repo. A per-task record here that
            # still reads "succeeded" only reflects that one isolated
            # worktree's own local result -- report it as blocked, never as a
            # false "succeeded", so the receipt never claims a delivery that
            # never happened. A record that already reports its own real
            # failure is kept as-is.
            corrected: List[Dict[str, Any]] = []
            for record in records:
                if isinstance(record, Mapping) and record.get("status") == "succeeded":
                    record = dict(record)
                    record["status"] = "blocked"
                    record["execution_state"] = "not_integrated"
                    record["reason_code"] = "wave_lane_not_integrated"
                    record["dead_letter"] = False
                corrected.append(record)
            records = corrected
        # A repaired lane's records come from `reapply_fn` running directly
        # on the already-integrated main repo -- they are the real, final
        # truth already and need no correction or receipt copy.
        final_records.extend(records)
        covered = {int(r.get("task_index")) for r in records if isinstance(r, Mapping) and r.get("task_index") is not None}
        for task_index in lane_result.task_indices:
            if task_index not in covered:
                # This lane failed before its worktree/apply step ever reached
                # this task -- record it once (dead-letter), never fabricate a
                # receipt or leave it silently unaccounted for.
                final_records.append({
                    "schema": "simplicio.operator-worker/v1", "task_index": task_index,
                    "run_id": run_id, "repo": str(repo_path), "status": "failed",
                    "execution_state": "blocked", "reason_code": "wave_lane_failed",
                    "dead_letter": True, "error": lane_result.log[-2000:],
                })

    wave_worktree.cleanup_worktrees(repo_path, results)

    # Persist every terminal (non-pending) per-task record to this run's own
    # operator-batch.jsonl -- the same durable journal `dispatch_operator_batch`
    # reads/writes -- so a crash-recovery resume, on whichever path handles it
    # next, recognizes a durably-succeeded task and never re-dispatches it.
    for record in final_records:
        if record.get("status") == "pending":
            continue
        # `record["repo"]` may still be the lane's ephemeral worktree path
        # (each lane task runs with its item's "repo" pointed at that
        # worktree) -- the journal's resume key must match the canonical
        # repo/run_id every caller (this function and the classic path) uses
        # to look an item up, never the worktree it happened to run in.
        journal_record = dict(record)
        journal_record["run_id"] = run_id
        journal_record["repo"] = str(repo_path)
        _append_jsonl(journal_path, journal_record)

    # Rebind repo_state_chain to the just-integrated tree so `verify`'s
    # staleness checks compare against what this run actually left, not a
    # stale `prepare`-time snapshot -- the same intent as the shared-run
    # serial path's own `state["repo_state_chain"] = after` write.
    try:
        state = _load_json(run_dir / "state.json")
        state["repo_state_chain"] = _repo_fingerprint(repo_path)
        _write_json(run_dir / "state.json", state)
    except (OSError, TypeError, ValueError):
        pass
    # The evidence receipt is one aggregate file per run (not per task) --
    # recompute it fresh against the just-integrated tree, same as every
    # successful serial dispatch already does at the end of each task.
    try:
        evidence = build_evidence_receipt(str(run_dir))
        _write_json(run_dir / "evidence-receipt.json", evidence)
    except (OSError, TypeError, ValueError):
        pass

    drained = bool(stopped_lane_ids) or any(r.status == "stopped" for r in results)
    return {
        "schema": "simplicio.operator-batch-receipt/v1",
        "workers": final_records,
        "max_workers": effective_workers or len(lane_task_indices),
        "max_workers_requested": max_workers,
        "capacity_admission": capacity_admission,
        "dispatch_mode": dispatch_mode,
        "serial_fallback_reason": "",
        "completed_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "succeeded"
        ),
        "failed_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "failed"
        ),
        "blocked_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "blocked"
        ),
        "dead_letter_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("dead_letter")
        ),
        "drain": {
            "status": "drained" if drained else "not_requested",
            "reason_code": "operator_stop_requested" if drained else "none",
            "pending_task_indices": sorted(
                int(r["task_index"]) for r in final_records if r.get("status") == "pending"
            ),
        },
        "wave": {
            "schema": wave_worktree.SCHEMA,
            "lanes": lane_task_indices,
            "base_commit": base_commit,
            "integration": integration,
        },
    }
