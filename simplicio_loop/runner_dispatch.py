"""Batch dispatch of operator items: dispatch journal, ``dispatch_operator_batch`` and ``execute_operator_batch`` (#1606)."""
from __future__ import annotations

import os
import shutil
import tempfile
import subprocess
from collections import deque
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
from .technical_debt import record_notice as _record_technical_debt
from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from .planning_gate import (
    content_hash as _planning_content_hash,
    evaluate_mutation_authority,
    mutation_authority_required,
)
from . import local_capacity
from .run_journal import RunJournal
from .mapper_run_journal import MapperRunJournal
from .runner_core import (
    _subprocess_env,
    BatchPreflightError,
    _is_deterministic_operator_failure,
    BATCH_SCHEMA,
    NATIVE_PRISM_SCHEMA,
    _now,
    _load_json,
    _write_json,
    _append_jsonl,
    _task_goal,
    WAVE_INLINE_MAX_TASKS,
    _auto_worktree_dispatch,
    _task_dependency_references,
    _task_aliases,
    _assert_task_dependencies_ready,
    _item_dependencies,
    _completed_task_aliases,
    _omit_satisfied_dispatch_dependencies,
    _ordered_dispatch_items,
    _mapper_journal_enabled,
    read_status,
)
from .runner_plan import (
    _mapper_operations_database,
    _ensure_mapper_operations_store,
)
from .runner_preflight import (
    _require_json_receipt,
    _validate_run_receipts,
    _persist_batch_preflight_block,
)
from .runner_execute import _terminate_owned_process
from .runner_lane import (
    _operator_dispatch_item,
    _operator_dispatch_attempt,
    _run_operator_item_process,
)
from .runner_wave import (
    _resolve_dispatch_mode,
    _load_prior_dispatch_records,
    _operator_worker_limit,
    _build_native_prism_scheduler,
    _prepare_worktree_contexts,
    _ensure_deferred_worktree_context,
    _release_shared_context,
    _wave_worktree_dispatch,
)

def _dispatch_journal_backend(
    journal_path: Optional[Path], *, repo_root: Optional[Path] = None,
) -> Any:
    """Select the journal from the rollout route; legacy remains pre-cutover default."""
    if _mapper_journal_enabled():
        # Mapper operations are repository-scoped.  Using the coordinator's cwd here
        # misroutes a zero-config run when the task repository is a fixture, worktree,
        # or child checkout launched from another project.
        root = Path(repo_root).resolve() if repo_root is not None else None
        if root is None and journal_path is not None:
            journal = Path(journal_path).resolve()
            for parent in (journal.parent, *journal.parents):
                if parent.name == "loop-runs" and parent.parent.name == ".simplicio-loop":
                    root = parent.parent.parent
                    break
        root = root or Path.cwd()
        return MapperRunJournal(_mapper_operations_database(root), auto_create=False)
    if journal_path is None:
        raise RuntimeError("JOURNAL_PATH_REQUIRED")
    return RunJournal(journal_path)


def _append_dispatch_journal(
    journal_path: Optional[Path], run_id: str, kind: str,
    payload: Mapping[str, Any], idempotency_key: str,
    *, repo_root: Optional[Path] = None,
) -> None:
    """Persist one idempotent batch lifecycle event in the existing RunJournal."""
    if journal_path is None:
        return
    journal = _dispatch_journal_backend(journal_path, repo_root=repo_root)
    if not journal.events(run_id):
        journal.append(
            run_id, "run_started", {"scope": "operator_batch"},
            idempotency_key="run:started",
        )
    journal.append(
        run_id, kind, dict(payload), idempotency_key=idempotency_key,
    )


def _dispatch_journal_recovery(
    journal_path: Optional[Path], run_id: str, *, repo_root: Optional[Path] = None,
) -> List[int]:
    """Return task indexes with a durable start but no terminal event."""
    if journal_path is None or (
        not _mapper_journal_enabled() and not journal_path.exists()
    ):
        return []
    events = _dispatch_journal_backend(journal_path, repo_root=repo_root).events(run_id)
    active: Dict[int, bool] = {}
    for event in events:
        payload = event.get("payload") or {}
        try:
            task_index = int(payload.get("task_index"))
        except (TypeError, ValueError):
            continue
        if event.get("kind") == "dispatch_started":
            active[task_index] = True
        elif event.get("kind") == "dispatch_terminal":
            active.pop(task_index, None)
    return sorted(active)


def dispatch_operator_batch(
    items: Iterable[Mapping[str, Any]],
    *,
    max_workers: Optional[int] = None,
    retry_budget: int = 3,
    journal_dir: Optional[str] = None,
    worktree_queue: Any = None,
    stop_requested: Optional[Callable[[], bool]] = None,
    owned_cancel: Optional[Callable[[str], Any]] = None,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    provider_worker: str | None = None,
) -> Dict[str, Any]:
    """Continuously dispatch real operator workers and refill freed slots.

    ``items`` is the typed bridge between a scheduler (DAG/leases/worktrees) and the
    existing mapper → plan → ``execute_operator`` boundary.  It is intentionally agnostic
    about claiming: callers pass only ready, atomically claimed nodes.  Items with the same
    ``isolation_key`` are forced onto one lane so a shared run state cannot be corrupted;
    distinct worktree/run contexts overlap in the pool.  A JSONL journal records each attempt
    before the next slot is refilled, so a process restart can safely resubmit only work that
    has no successful receipt.
    """
    normalized = [_operator_dispatch_item(item) for item in items]
    if provider_worker is not None:
        selected_provider_worker = str(provider_worker).strip().lower()
        for item in normalized:
            item["provider_worker"] = selected_provider_worker
    keys = {(item["repo"], item["run_id"], item["task_index"]) for item in normalized}
    if len(keys) != len(normalized):
        raise ValueError("operator dispatch contains duplicate repo/run/task items")
    normalized = _ordered_dispatch_items(normalized)
    prism_enabled = len(normalized) > 3
    has_dependencies = any(_item_dependencies(item) for item in normalized)

    # Issue #288 cross-process recovery: load the journal *before* preflight so a resumed
    # batch can tell "already durably succeeded" items apart from ones still needing a fresh
    # dry-run preflight. A succeeded item's operator-receipt.json has already been
    # overwritten by `execute_operator` with a *post-execution* receipt (no `run_id` field,
    # a different shape than the pre-execution dry-run receipt `_validate_run_receipts`
    # expects) -- re-validating it as if it were still a pending dry-run would always fail
    # and permanently block every resumed batch that contains even one completed item.
    journal_path: Optional[Path] = None
    durable_journal_path: Optional[Path] = None
    repo_root_by_run = {
        str(item["run_id"]): Path(item["repo"]).resolve()
        for item in normalized
    }
    if _mapper_journal_enabled():
        # Every repo a task will run its mutation attempt in needs an initialized
        # Mapper operations store *before* any worker tries to claim a lease there --
        # otherwise the first `_claim_mapper_operation_attempt` call in each fresh
        # worktree/repo fails closed with STORE_NOT_INITIALIZED. `execute_operator_batch`
        # already does this for its single, already-materialized run repo; this
        # boundary fans out across possibly-multiple, possibly-not-yet-materialized
        # repos, so it must ensure the store itself. Note this is *not* the same set
        # as ``repo_root_by_run.values()`` -- several items can share one run_id
        # while fanning out into distinct per-item repos/worktrees, and a dict keyed
        # by run_id keeps only the last item's repo for that key.
        for repo_path in {Path(item["repo"]).resolve() for item in normalized}:
            _ensure_mapper_operations_store(repo_path)
    if journal_dir:
        journal_path = Path(journal_dir).resolve() / "operator-batch.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        # The retired legacy route is intentionally read-only.  Keep its
        # append-only JSONL attempt records, but do not instantiate the old
        # RunJournal facade (which must fail closed) or pretend it can provide
        # MapperStore recovery semantics.  The Mapper route gets the durable
        # operations journal as before.
        if _mapper_journal_enabled():
            durable_journal_path = journal_path.parent / "run-journal.sqlite"
    recovery_pending_by_run: Dict[str, set[int]] = {}
    if durable_journal_path is not None:
        for run_id in {item["run_id"] for item in normalized}:
            pending_indices = set(_dispatch_journal_recovery(
                durable_journal_path,
                run_id,
                repo_root=repo_root_by_run.get(str(run_id)),
            ))
            if pending_indices:
                recovery_pending_by_run[run_id] = pending_indices
    prior = _load_prior_dispatch_records(journal_path) if journal_path else {}

    # A persisted run is a privileged execution boundary.  Keep synthetic scheduler
    # contexts supported, but fail every run-backed dispatch globally before worktree
    # preparation, journal creation, or worker submission unless its receipt chain is
    # fresh and bound to this exact run -- except an item already durably journaled as
    # succeeded, which is never re-dispatched and so must never be re-validated as if it
    # still needed a fresh dry run.
    for item in normalized:
        key = (item["repo"], item["run_id"], item["task_index"])
        if prior.get(key, {}).get("status") == "succeeded":
            continue
        repo_path = Path(item["repo"]).resolve()
        run_dir = repo_path / ".simplicio-loop" / "loop-runs" / item["run_id"]
        if not run_dir.is_dir():
            continue
        try:
            contract = _require_json_receipt(run_dir / "task-contract.json", "task contract")
            _validate_run_receipts(
                repo_path,
                run_dir,
                contract,
                state=_load_json(run_dir / "state.json") if (run_dir / "state.json").is_file() else None,
                manifest=_load_json(run_dir / "manifest.json") if (run_dir / "manifest.json").is_file() else None,
                require_dry_run=True,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            state_path = run_dir / "state.json"
            if state_path.is_file():
                _persist_batch_preflight_block(
                    run_dir,
                    _load_json(state_path),
                    repo_path,
                    str(exc),
                    task_indices=[item["task_index"]],
                )
            raise
    requested_workers = max_workers
    effective_workers = _operator_worker_limit(max_workers, len(normalized))
    serial_fallback_reason = ""
    # A queued worktree is a lease-bearing mutation resource.  Reserve independent
    # worktree lanes for the capacity request, but retain the shared-run serial guard
    # when no queue can provide those lanes.  Allocation itself happens only after the
    # first physical admission decision below.
    candidate_isolation_keys = {
        ("worktree:%s" % item["task_id"]
         if worktree_queue is not None and str(item.get("isolation") or "worktree") == "worktree"
         else item["isolation_key"])
        for item in normalized
    }
    if effective_workers > 1 and len(candidate_isolation_keys) < len(normalized):
        effective_workers = 1
        serial_fallback_reason = "shared_run_state"
    if has_dependencies:
        # A dependent task must observe the predecessor's real checkout and
        # task-result receipt. Keep the governed lane serial for both direct
        # parallelism and Prism; the physical governor remains active.
        effective_workers = 1
        serial_fallback_reason = "dependency_order"
    retry_budget = max(0, int(retry_budget))
    from .local_capacity import PhysicalAdmissionMonitor
    monitor_kwargs = local_capacity.physical_monitor_kwargs(physical_monitor_kwargs)
    if prism_enabled:
        prism_scheduler, prism_id, capacity_sample = _build_native_prism_scheduler(
            normalized, effective_workers, physical_monitor_kwargs=monitor_kwargs,
        )
        physical_monitor = getattr(prism_scheduler, "native_capacity_monitor", None)
        direct_governor = None
        effective_workers = max(0, min(effective_workers, int(capacity_sample["safe_workers"])))
    else:
        # One to three tasks use the direct executor path. Keep the same
        # receipt/journal/lease machinery and the same physical governor,
        # without creating a second scheduler graph.
        from .prism_budgets import AdaptiveBudgetGovernor, BudgetSample
        from .prism_scheduler import PrismPolicy
        capacity_root = Path(str((normalized[0].get("repo") if normalized else None) or ".")).resolve()
        while not capacity_root.exists() and capacity_root != capacity_root.parent:
            capacity_root = capacity_root.parent
        if monitor_kwargs:
            physical_monitor = PhysicalAdmissionMonitor(
                str(capacity_root), effective_workers, **monitor_kwargs,
            )
        else:
            physical_monitor = PhysicalAdmissionMonitor(
                str(capacity_root), effective_workers,
            )
        direct_policy = PrismPolicy(
            global_worker_limit=max(1, effective_workers),
            recovery_reserve=0,
            validation_reserve=0,
        )
        direct_governor = AdaptiveBudgetGovernor(direct_policy, relief_samples=2)

        def _direct_budget_sample(sample: Any) -> BudgetSample:
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

        direct_sample = physical_monitor.refresh(force=True)
        effective_workers = max(0, min(effective_workers, int(direct_sample.safe_workers)))
        direct_governor.observe(_direct_budget_sample(direct_sample))
        prism_scheduler = None
        prism_id = ""
        capacity_sample = direct_sample.to_dict()
        capacity_sample["schema"] = "simplicio.direct-parallelism-capacity/v1"
        capacity_sample["source"] = "physical_admission_monitor"
        capacity_sample["budget_governor"] = direct_governor.status()
        capacity_sample["monitor"] = physical_monitor.status()
        capacity_sample["policy"] = {
            "recovery_reserve": direct_policy.recovery_reserve,
            "validation_reserve": direct_policy.validation_reserve,
            "global_worker_limit": direct_policy.global_worker_limit,
        }
    capacity_admission: dict[str, Any] = (
        physical_monitor.admission_status()
        if physical_monitor is not None
        else {
            "admitted": False,
            "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
            "reason": "monitor_unavailable",
            "evidence": {},
        }
    )
    # Admission precedes all queue allocation.  A blocked batch therefore leaves no
    # worktree or shared-checkout lease behind for a later retry to mistake as owned.
    if capacity_admission.get("admitted"):
        _prepare_worktree_contexts(normalized, worktree_queue, defer_worktrees=True)
        actual_isolation_keys = {item["isolation_key"] for item in normalized}
        if effective_workers > 1 and len(actual_isolation_keys) < len(normalized):
            effective_workers = 1
            serial_fallback_reason = "shared_run_state"

    pending = deque(
        item for item in normalized
        if prior.get((item["repo"], item["run_id"], item["task_index"]), {}).get("status") != "succeeded"
        and item["task_index"] not in recovery_pending_by_run.get(item["run_id"], set())
    )
    # ``skipped_completed`` is specifically the durably-succeeded items a resumed batch
    # does not redo -- not every item this pass excludes from `pending`. An item held
    # back instead as `recovery_pending` (a crashed dispatch with a durable start but no
    # terminal event) is counted separately in `recovery_blocked_count` below; folding it
    # into `skipped_completed` would misreport a not-yet-reconciled item as "already done".
    skipped = sum(
        1 for item in normalized
        if prior.get((item["repo"], item["run_id"], item["task_index"]), {}).get("status") == "succeeded"
    )
    pending_task_ids = {str(item.get("task_id") or "") for item in pending}
    prism_admitted: deque[str] = deque()
    # A resumed batch can have a completed item at the head of Prism's ready queue.
    # Retire those durable successes before admitting fresh work; otherwise a full
    # capacity sample leaves the pending item permanently invisible behind the skip.
    if prism_enabled and capacity_admission.get("admitted"):
        while True:
            admitted = prism_scheduler.next_batch()
            if not admitted:
                break
            for task in admitted:
                if task.task_id in pending_task_ids:
                    prism_admitted.append(task.task_id)
                    continue
                try:
                    recovery = any(
                        item.get("task_id") == task.task_id
                        and int(item.get("task_index", -1))
                        in recovery_pending_by_run.get(str(item.get("run_id") or ""), set())
                        for item in normalized
                    )
                    prism_scheduler.complete(
                        task.task_id, "blocked" if recovery else "accepted",
                        owner_agent=task.ownership.owner_agent,
                        fence=task.ownership.fence,
                    )
                except Exception:
                    # The scheduler remains authoritative; a later normal admission or
                    # terminal path will surface any unexpected state mismatch.
                    continue
    else:
        prism_admitted.extend(str(item.get("task_id") or "") for item in pending)
    for item in pending:
        _append_dispatch_journal(
            durable_journal_path, item["run_id"], "dispatch_queued",
            {
                "task_id": item["task_id"], "task_index": item["task_index"],
                "worker_id": item["worker_id"], "isolation_key": item["isolation_key"],
            },
            f"dispatch:{item['task_id']}:queued",
            repo_root=Path(item["repo"]).resolve(),
        )
    for run_id, task_indices in recovery_pending_by_run.items():
        for task_index in sorted(task_indices):
            _append_dispatch_journal(
                durable_journal_path, run_id, "dispatch_recovery_pending",
                {
                    "task_index": task_index,
                    "reason_code": "unknown_effect_reconciliation_required",
                },
                f"dispatch:{run_id}:{task_index}:recovery-pending",
                repo_root=repo_root_by_run.get(str(run_id)),
            )
    started = _now()
    records: Dict[Tuple[str, str, int], Dict[str, Any]] = dict(prior)
    for item in normalized:
        if item["task_index"] not in recovery_pending_by_run.get(item["run_id"], set()):
            continue
        records[(item["repo"], item["run_id"], item["task_index"])] = {
            "schema": "simplicio.operator-worker/v1",
            "worker_id": item["worker_id"], "repo": item["repo"],
            "source_repo": item.get("source_repo", item["repo"]),
            "run_id": item["run_id"], "task_index": item["task_index"],
            "task_id": item.get("task_id", ""),
            "worktree_context": item.get("worktree_context", {}),
            "status": "blocked", "phase": "recovery",
            "execution_state": "unknown_effect",
            "reason_code": "unknown_effect_reconciliation_required",
            "recovery_pending": True, "dead_letter": False,
            "attempt": 0, "attempt_count": 0,
            "started_at": _now(), "finished_at": _now(),
        }
    completed: List[Dict[str, Any]] = []
    refill_count = 0
    initial_admissions = 0
    stop_reason = ""
    capacity_stop_reason = ""

    def _drain_requested() -> bool:
        nonlocal stop_reason
        if stop_requested is None:
            return False
        try:
            requested = bool(stop_requested())
        except Exception as exc:
            stop_reason = f"stop_callback_failed:{type(exc).__name__}"
            return True
        if requested and not stop_reason:
            stop_reason = "operator_stop_requested"
        return requested

    def _persist_attempt(record: Dict[str, Any]) -> None:
        if journal_path:
            _append_jsonl(journal_path, record)
        records[(record["repo"], record["run_id"], record["task_index"])] = record

    def _run_item(item: Dict[str, Any], owned_process_registry: Any = None) -> List[Dict[str, Any]]:
        attempts: List[Dict[str, Any]] = []
        previous_fingerprint = ""
        _ensure_deferred_worktree_context(item, worktree_queue)
        try:
            for attempt_no in range(1, retry_budget + 2):
                dispatch_item = dict(item)
                dispatch_item["owned_process_registry"] = owned_process_registry
                record = _operator_dispatch_attempt(dispatch_item)
                record["dispatch_attempt"] = attempt_no
                if previous_fingerprint and record.get("failure_fingerprint") == previous_fingerprint:
                    record["retry_strategy"] = "same_fingerprint_bounded"
                elif attempt_no > 1:
                    record["retry_strategy"] = "alternate_strategy"
                else:
                    record["retry_strategy"] = "initial"
                attempts.append(record)
                if record["status"] == "succeeded":
                    break
                if _is_deterministic_operator_failure(record):
                    # #NOWASTE: same reasoning as `_run_operator_item_process` -- a
                    # deterministic failure is recorded once, never retried.
                    record["retry_skipped_reason"] = "deterministic_failure_no_retry"
                    break
                previous_fingerprint = str(record.get("failure_fingerprint") or "")
        finally:
            _release_shared_context(item, worktree_queue)
        attempts[-1]["dead_letter"] = attempts[-1]["status"] != "succeeded"
        # Keep compact per-lane history on the final record while the JSONL journal
        # retains the complete receipts.  This proves a retry belongs to one worker and
        # did not restart sibling lanes.
        attempts[-1]["attempt_count"] = len(attempts)
        attempts[-1]["retry_scope"] = "worker"
        attempts[-1]["attempt_history"] = [
            {
                "dispatch_attempt": int(record.get("dispatch_attempt") or index),
                "status": record.get("status", "UNVERIFIED"),
                "failure_fingerprint": record.get("failure_fingerprint", ""),
            }
            for index, record in enumerate(attempts, start=1)
        ]
        return attempts

    def _take_prism_admitted() -> Optional[Dict[str, Any]]:
        for item in pending:
            if item.get("task_id") not in prism_admitted:
                continue
            pending.remove(item)
            prism_admitted.remove(item.get("task_id"))
            return item
        return None

    def _refill_prism(*, refresh_capacity: bool = True) -> None:
        if not prism_enabled:
            return
        if refresh_capacity:
            refresh = getattr(prism_scheduler, "native_capacity_refresh", None)
            if refresh is not None:
                refresh()
        for task in prism_scheduler.next_batch():
            if task.task_id not in prism_admitted:
                prism_admitted.append(task.task_id)

    def _update_direct_capacity_receipt(sample: Any) -> None:
        capacity_sample.clear()
        capacity_sample.update(sample.to_dict())
        capacity_sample["schema"] = "simplicio.direct-parallelism-capacity/v1"
        capacity_sample["source"] = "physical_admission_monitor"
        capacity_sample["budget_governor"] = direct_governor.status()
        capacity_sample["monitor"] = physical_monitor.status()
        capacity_sample["policy"] = {
            "recovery_reserve": direct_policy.recovery_reserve,
            "validation_reserve": direct_policy.validation_reserve,
            "global_worker_limit": direct_policy.global_worker_limit,
        }

    def _refresh_physical_admission(*, force: bool = False) -> dict[str, Any]:
        nonlocal capacity_admission
        monitor = physical_monitor
        if monitor is None:
            capacity_admission = {
                "admitted": False,
                "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
                "reason": "monitor_unavailable",
                "evidence": {},
            }
            return capacity_admission
        if force or monitor.due():
            if prism_enabled:
                refresh = getattr(prism_scheduler, "native_capacity_refresh", None)
                if refresh is None:
                    monitor.refresh(force=True)
                else:
                    refresh(force=True)
            else:
                refreshed = monitor.refresh(force=force)
                direct_governor.observe(_direct_budget_sample(refreshed))
                _update_direct_capacity_receipt(refreshed)
        sample = monitor.sample
        if sample is None:
            capacity_admission = {
                "admitted": False,
                "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
                "reason": "no_sample",
                "action": "suspend_new",
                "evidence": {},
            }
        else:
            capacity_admission = monitor.admission_status()
        return capacity_admission

    def _set_capacity_stop(admission: Mapping[str, Any]) -> None:
        nonlocal capacity_stop_reason
        if admission.get("admitted"):
            # Physical pressure is resumable after the monitor's sustained-recovery
            # window.  Operator stop requests remain in ``stop_reason`` below.
            capacity_stop_reason = ""
            return
        code = str(admission.get("reason_code") or "PHYSICAL_ADMISSION_BLOCKED")
        reason = str(admission.get("reason") or "capacity_not_admitted")
        capacity_stop_reason = f"{code}:{reason}"

    dispatch_mode = _resolve_dispatch_mode()
    registry_manager = None
    owned_process_registry: Any = {}
    if dispatch_mode == "process":
        registry_manager = Path(tempfile.mkdtemp(prefix="simplicio-owned-processes-"))
        owned_process_registry = str(registry_manager)

    owned_shutdown: dict[str, Any] = {
        "status": "not_requested", "action": "", "cancelled_task_ids": [],
        "limitations": [], "errors": [],
    }

    def _request_owned_cancel(task_id: str) -> Any:
        """Terminate the registered child, then fall back to a queue cancellation hook."""
        outcome = _terminate_owned_process(owned_process_registry, task_id)
        if outcome is not None:
            return outcome
        if owned_cancel is not None:
            return owned_cancel(task_id)
        if worktree_queue is not None:
            for method_name in ("request_cancel", "cancel_task", "release_task", "cancel"):
                method = getattr(worktree_queue, method_name, None)
                if not callable(method):
                    continue
                try:
                    return method(task_id, reason="physical_pressure_terminate")
                except TypeError:
                    return method(task_id)
        return None

    def _shutdown_owned(admission: Mapping[str, Any], active: Mapping[Any, Mapping[str, Any]]) -> None:
        if str(admission.get("action") or "") != "terminate_owned":
            return
        if owned_shutdown.get("action") == "terminate_owned":
            return
        owned_shutdown.update({"status": "requested", "action": "terminate_owned"})
        for future, item in active.items():
            task_id = str(item.get("task_id") or "")
            if not task_id:
                continue
            # ``Future.cancel`` is safe for work not yet started.  A running process
            # is cancellable only through the existing owned queue/registry hook.
            if future.cancel():
                owned_shutdown["cancelled_task_ids"].append(task_id)
                continue
            try:
                outcome = _request_owned_cancel(task_id)
                cancelled = not isinstance(outcome, Mapping) or outcome.get("cancelled", True) is not False
                if outcome is None or not cancelled:
                    owned_shutdown["limitations"].append(
                        f"{task_id}:running_subprocess_requires_owned_supervisor_hook"
                    )
                elif task_id not in owned_shutdown["cancelled_task_ids"]:
                    owned_shutdown["cancelled_task_ids"].append(task_id)
            except Exception as exc:
                owned_shutdown["errors"].append(
                    f"{task_id}:{type(exc).__name__}: {exc}"
                )
        if not owned_shutdown["cancelled_task_ids"] and not owned_shutdown["errors"]:
            owned_shutdown["status"] = "limited"


    def _submit_process_item(pool: Any, item: Dict[str, Any]) -> Any:
        _ensure_deferred_worktree_context(item, worktree_queue)
        try:
            return pool.submit(_run_operator_item_process, item, retry_budget, owned_process_registry)
        except Exception:
            # Allocation happened before submission; a failed submission must release
            # the owned lease even when no worker ever receives the item.
            _release_shared_context(item, worktree_queue, force=True)
            raise

    # Queue clients remain coordinator-owned and are never sent to children.  The
    # child receives only the already-persisted, JSON-safe worktree context; the
    # coordinator releases the queue lease after the child returns.  This keeps
    # process supervision as the default even when isolated worktrees are enabled.
    executor_type = ProcessPoolExecutor if dispatch_mode == "process" else ThreadPoolExecutor
    executor_kwargs = {"max_workers": effective_workers}
    if dispatch_mode == "process" and os.name == "posix":
        try:
            import multiprocessing as _mp
            if "fork" in _mp.get_all_start_methods():
                executor_kwargs["mp_context"] = _mp.get_context("fork")
        except (AttributeError, ValueError):
            pass
    if dispatch_mode == "thread":
        executor_kwargs["thread_name_prefix"] = "simplicio-operator"
    _set_capacity_stop(_refresh_physical_admission())
    if pending and effective_workers and not stop_reason and not capacity_stop_reason:
        with executor_type(**executor_kwargs) as pool:
            active = {}
            while pending and len(active) < effective_workers and not _drain_requested() and not stop_reason and not capacity_stop_reason:
                admission = _refresh_physical_admission()
                if not admission.get("admitted"):
                    _set_capacity_stop(admission)
                    break
                item = _take_prism_admitted()
                if item is None:
                    break
                if dispatch_mode == "process":
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_started",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "mode": dispatch_mode},
                        f"dispatch:{item['task_id']}:started",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    active[_submit_process_item(pool, item)] = item
                    initial_admissions += 1
                else:
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_started",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "mode": dispatch_mode},
                        f"dispatch:{item['task_id']}:started",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    active[pool.submit(_run_item, item, owned_process_registry)] = item
                    initial_admissions += 1
            while active:
                timeout = (
                    max(0.001, physical_monitor.sample_interval_ns / 1_000_000_000)
                    if physical_monitor is not None else 5.0
                )
                done, not_done = wait(
                    tuple(active), timeout=timeout, return_when=FIRST_COMPLETED,
                )
                # A coordinator cancellation can leave a Future in CANCELLED until the
                # executor notifies its waiter; process it immediately so owned context
                # cleanup does not wait for a cancelled task forever.
                done.update(future for future in not_done if future.cancelled())
                if not done:
                    admission = _refresh_physical_admission()
                    if not admission.get("admitted"):
                        _set_capacity_stop(admission)
                    _shutdown_owned(admission, active)
                    if admission.get("admitted") and pending and prism_enabled and not stop_reason and not capacity_stop_reason:
                        _refill_prism(refresh_capacity=False)
                    continue
                for future in done:
                    item = active.pop(future)
                    try:
                        attempts = future.result()
                    except Exception as exc:  # defensive: _run_item already receipts exceptions
                        attempts = [{
                            "schema": "simplicio.operator-worker/v1",
                            "worker_id": item["worker_id"], "repo": item["repo"],
                            "source_repo": item.get("source_repo", item["repo"]),
                            "run_id": item["run_id"], "task_index": item["task_index"],
                            "task_id": item.get("task_id", ""),
                            "worktree_context": item.get("worktree_context", {}),
                            "status": "failed", "phase": "blocked", "execution_state": "error",
                            "error": f"{type(exc).__name__}: {exc}", "dead_letter": True,
                            "started_at": _now(), "finished_at": _now(),
                        }]
                    if dispatch_mode == "process":
                        _release_shared_context(item, worktree_queue, force=future.cancelled())
                    for record in attempts:
                        _persist_attempt(record)
                    final = attempts[-1]
                    completed.append(final)
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_terminal",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "status": final.get("status"),
                         "receipt": final.get("receipt", "")},
                        f"dispatch:{item['task_id']}:terminal:{final.get('status', 'unknown')}",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    try:
                        if prism_enabled:
                            prism_scheduler.complete(
                                str(item.get("task_id") or ""),
                                "accepted" if final.get("status") == "succeeded" else "failed",
                                owner_agent=str(item.get("worker_id") or "simplicio-local"),
                                fence=1,
                            )
                            _refill_prism()
                    except Exception as exc:
                        final.setdefault("prism_error", f"{type(exc).__name__}: {exc}")
                    admission = _refresh_physical_admission()
                    _set_capacity_stop(admission)
                    _shutdown_owned(admission, active)
                    # Refill as soon as this worker exits; there is no frozen wave barrier.
                    if pending and not _drain_requested() and not stop_reason and not capacity_stop_reason:
                        next_item = _take_prism_admitted()
                        if next_item is None:
                            continue
                        if dispatch_mode == "process":
                            _append_dispatch_journal(
                                durable_journal_path, next_item["run_id"], "dispatch_started",
                                {"task_id": next_item["task_id"], "task_index": next_item["task_index"],
                                 "worker_id": next_item["worker_id"], "mode": dispatch_mode},
                                f"dispatch:{next_item['task_id']}:started",
                                repo_root=Path(next_item["repo"]).resolve(),
                            )
                            active[_submit_process_item(pool, next_item)] = next_item
                        else:
                            _append_dispatch_journal(
                                durable_journal_path, next_item["run_id"], "dispatch_started",
                                {"task_id": next_item["task_id"], "task_index": next_item["task_index"],
                                 "worker_id": next_item["worker_id"], "mode": dispatch_mode},
                                f"dispatch:{next_item['task_id']}:started",
                                repo_root=Path(next_item["repo"]).resolve(),
                            )
                            active[pool.submit(_run_item, next_item, owned_process_registry)] = next_item
                        refill_count += 1

    if registry_manager is not None:
        shutil.rmtree(registry_manager, ignore_errors=True)

    final_records = []
    capacity_blocked = not bool(capacity_admission.get("admitted"))
    for item in normalized:
        key = (item["repo"], item["run_id"], item["task_index"])
        existing = records.get(key)
        if existing is None and capacity_blocked:
            # Every unsent task receives a durable blocked receipt with the exact
            # physical evidence that prevented admission.  This keeps queue state
            # auditable and gives a retry a concrete reason to reconcile.
            blocked = {
                "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
                "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
                "task_id": item.get("task_id", ""),
                "source_repo": item.get("source_repo", item["repo"]),
                "worktree_context": item.get("worktree_context", {}),
                "status": "blocked", "phase": "capacity", "execution_state": "paused",
                "reason_code": capacity_admission.get("reason_code", "PHYSICAL_ADMISSION_BLOCKED"),
                "reason": capacity_admission.get("reason", "capacity_not_admitted"),
                "error": capacity_admission.get("reason", "capacity_not_admitted"),
                "admission_evidence": capacity_admission.get("evidence", {}),
                "receipt_status": "BLOCKED", "attempt": 0, "attempt_count": 0,
                "dead_letter": False, "blocked": True,
                "started_at": _now(), "finished_at": _now(),
            }
            _persist_attempt(blocked)
            existing = blocked
        final_records.append(existing or {
            "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
            "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
            "task_id": item.get("task_id", ""),
            "source_repo": item.get("source_repo", item["repo"]),
            "worktree_context": item.get("worktree_context", {}),
            "status": "pending", "phase": "queued", "execution_state": "pending",
            "drain_status": "held" if (stop_reason or capacity_stop_reason) else "queued",
        })
    result = {
        "schema": BATCH_SCHEMA,
        "run_id": normalized[0]["run_id"] if normalized and len({i["run_id"] for i in normalized}) == 1 else "",
        "requested_tasks": [item["task_index"] for item in normalized],
        "skipped_completed": skipped,
        "recovery_blocked_count": sum(
            len(indices) for indices in recovery_pending_by_run.values()
        ),
        "max_workers_requested": requested_workers,
        "max_workers": effective_workers,
        "active_workers": 0,
        "worker_count": len(final_records),
        "queue_depth": 0,
        "capacity_admission": capacity_admission,
        "owned_shutdown": owned_shutdown,
        "refill_count": refill_count,
        "initial_admissions": initial_admissions,
        "serial_fallback_reason": serial_fallback_reason,
        "dispatch_mode": dispatch_mode,
        "drain": {
            "status": "drained" if (stop_reason or capacity_stop_reason) else "not_requested",
            "reason_code": stop_reason or capacity_stop_reason or "none",
            "pending_task_indices": [item["task_index"] for item in pending],
        },
        "durable_journal": str(durable_journal_path) if durable_journal_path else "",
        "recovery_pending_task_indices": sorted({
            task_index
            for run_id in {item["run_id"] for item in normalized}
            for task_index in _dispatch_journal_recovery(
                durable_journal_path, run_id, repo_root=repo_root_by_run.get(str(run_id)),
            )
        }),
        "leases": [],
        "blockers": [
            {
                "task_index": record["task_index"],
                "reason_code": record.get(
                    "reason_code",
                    "operator_failed",
                ),
                "error": record.get("error", ""),
                "failure_fingerprint": record.get("failure_fingerprint", ""),
            }
            for record in final_records
            if record.get("status") in {"failed", "blocked"}
        ],
        "attempts": {
            str(record["task_index"]): int(record.get("dispatch_attempt") or 0)
            for record in final_records
        },
        "started_at": started,
        "finished_at": _now(),
        "workers": final_records,
        "completed_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "succeeded"),
        "failed_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "failed"),
        "blocked_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "blocked"),
        "dead_letter_task_indices": sorted(r["task_index"] for r in final_records if r.get("dead_letter")),
        "receipt_contract": {
            "scope": "worker",
            "required": ["operator_receipt", "evidence_receipt"],
            "ready": all(
                r.get("receipt_status") == "VERIFIED"
                for r in final_records
            ),
            "missing_task_indices": sorted(
                r["task_index"] for r in final_records
                if r.get("receipt_status") != "VERIFIED"
            ),
        },
        "retry_contract": {
            "scope": "worker",
            "independent": True,
            "attempts_by_task": {
                str(r["task_index"]): int(r.get("attempt_count") or 0)
                for r in final_records
            },
        },
        "prism": {
            "schema": NATIVE_PRISM_SCHEMA,
            "mode": "native-local" if prism_enabled else "direct-parallelism",
            "prism_id": prism_id,
            "scheduler": (
                "simplicio_loop.prism_scheduler.PrismScheduler"
                if prism_enabled else "concurrent.futures.direct"
            ),
            "admission": "governed" if prism_enabled else "direct-executor",
            "max_workers": effective_workers,
            "capacity": capacity_sample,
            "snapshot": prism_scheduler.snapshot() if prism_enabled else None,
        },
        "journal": str(journal_path) if journal_path else "",
    }
    if journal_path:
        _write_json(journal_path.with_suffix(".json"), result)
    return result


def execute_operator_batch(
    repo: str,
    run_id: str,
    task_indices: Optional[Sequence[int]] = None,
    *,
    max_workers: Optional[int] = None,
    retry_budget: int = 3,
    isolated_contexts: Optional[Mapping[int, Mapping[str, Any]]] = None,
    worktree_queue: Any = None,
    auto_fan_out: Optional[bool] = None,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    provider_worker: str | None = None,
) -> Dict[str, Any]:
    """Dispatch all (or selected) tasks from one run through the real operator bridge.

    Independent tasks fan out into owned worktrees by default.  Set ``auto_fan_out=False`` or
    ``SIMPLICIO_LOOP_AUTO_FAN_OUT=0`` to opt out.  If impact metadata, Git, or the worktree
    adapter is unavailable, the shared-run serial guard remains the safe fallback.
    """
    status = read_status(repo, run_id)
    if (status["state"].get("maintenance") or {}).get("disposition") == "backlog_only":
        raise RuntimeError("maintenance deferred: operator batch is blocked until explicit resume")
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"].get("repo") or repo).resolve()
    _ensure_mapper_operations_store(
        repo_path,
        status["manifest"].get("storage_route"),
    )
    try:
        contract = _require_json_receipt(run_dir / "task-contract.json", "task contract")
        receipts = _validate_run_receipts(
            Path(status["manifest"].get("repo") or repo).resolve(),
            run_dir,
            contract,
            state=status["state"],
            manifest=status["manifest"],
            require_dry_run=True,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        _persist_batch_preflight_block(
            run_dir,
            status["state"],
            Path(status["manifest"].get("repo") or repo).resolve(),
            str(exc),
            task_indices=task_indices or (),
        )
        # #NOWASTE: this exact receipt chain will fail the exact same validation
        # the exact same way on any immediate re-invocation (nothing about the
        # repo/receipts changes between retries) -- a typed reason_code lets any
        # caller that retries a whole batch dispatch (e.g. an outer re-feed loop)
        # recognize "deterministic, do not retry on a cadence" instead of
        # treating this like a transient failure.
        raise BatchPreflightError(str(exc)) from exc
    plan = receipts["plan"]
    # #284: mutation-authority gate, mandatory by default -- same as execute_operator()
    # (single-task tick), extended to the batch boundary. "execute_operator() e batch
    # recusam execução sem mutation authority válida" now applies unconditionally
    # (opt out only via an explicit falsy SIMPLICIO_REQUIRE_MUTATION_AUTHORITY; see
    # planning_gate.mutation_authority_required()).
    if mutation_authority_required():
        batch_attempt = int((status["state"] or {}).get("attempts", 0)) + 1
        current_source_hash = ""
        current_snapshot_path = run_dir / "source-snapshot-current.json"
        if current_snapshot_path.exists():
            try:
                current_source_hash = str((_load_json(current_snapshot_path).get("source") or {}).get("snapshot_hash") or "")
            except Exception:
                current_source_hash = ""
        authority_verdict = evaluate_mutation_authority(
            run_dir, run_id=run_id, attempt=batch_attempt,
            task_contract_hash=str(contract.get("collection_hash") or _planning_content_hash(contract)),
            plan_hash=_planning_content_hash(plan),
            source_snapshot_hash=current_source_hash,
        )
        if not authority_verdict["ok"]:
            _persist_batch_preflight_block(
                run_dir,
                status["state"],
                Path(status["manifest"].get("repo") or repo).resolve(),
                f"mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}",
                task_indices=task_indices or (),
            )
            raise RuntimeError(
                "mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}"
            )
    else:
        batch_attempt = int((status["state"] or {}).get("attempts", 0)) + 1
    task_count = len(contract.get("tasks") or [])
    if task_indices is None:
        indices = list(range(1, task_count + 1))
    else:
        indices = [int(index) for index in task_indices]
    if any(index < 1 or index > task_count for index in indices):
        raise ValueError("task index out of range")
    contexts = dict(isolated_contexts or {})
    auto_reason = "explicit_contexts" if isolated_contexts else ""
    contract_tasks = list(contract.get("tasks") or [])
    contract_steps = list(plan.get("steps") or [])
    has_task_dependencies = any(
        _task_dependency_references(
            contract_tasks[index - 1] if 0 < index <= len(contract_tasks) else {},
            contract_steps[index - 1] if 0 < index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else {},
        )
        for index in indices
    )
    if not isolated_contexts and worktree_queue is None and (auto_fan_out is not False) and not has_task_dependencies:
        previous = os.environ.get("SIMPLICIO_LOOP_AUTO_FAN_OUT")
        if auto_fan_out is True:
            os.environ["SIMPLICIO_LOOP_AUTO_FAN_OUT"] = "1"
        try:
            worktree_queue, auto_contexts, auto_reason = _auto_worktree_dispatch(
                repo, run_id, contract, plan, indices,
            )
        finally:
            if auto_fan_out is True:
                if previous is None:
                    os.environ.pop("SIMPLICIO_LOOP_AUTO_FAN_OUT", None)
                else:
                    os.environ["SIMPLICIO_LOOP_AUTO_FAN_OUT"] = previous
        contexts.update(auto_contexts)
    elif has_task_dependencies:
        auto_reason = "dependency_order_requires_shared_run"
    items = []
    runtime_task_ids = {
        index: str((contexts.get(index) or {}).get("task_id") or f"{run_id}-task-{index}")
        for index in indices
    }
    dependency_aliases = {
        alias: runtime_task_ids[index]
        for index, task in enumerate(contract_tasks, start=1)
        if index in runtime_task_ids
        for alias in _task_aliases(task, index, run_id)
    }
    for index in indices:
        context = dict(contexts.get(index) or {})
        task = contract_tasks[index - 1]
        step = contract_steps[index - 1] if index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else {}
        task_id = runtime_task_ids[index]
        target_paths = [str(path) for path in (step.get("candidate_targets") or []) if str(path).strip()]
        task_spec = dict(context.get("task_spec") or {})
        task_spec.setdefault("id", task_id)
        task_spec.setdefault("goal", _task_goal(task))
        task_spec.setdefault("files_affected", target_paths)
        dependencies = []
        for dependency in _task_dependency_references(task, step):
            dependencies.append(dependency_aliases.get(dependency, dependency))
        dependencies.extend(_item_dependencies({"task_spec": task_spec}))
        task_spec["depends_on"] = list(dict.fromkeys(str(value) for value in dependencies if str(value).strip()))
        item = {
            "repo": context.get("repo", repo),
            "run_id": context.get("run_id", run_id),
            "task_index": index,
            "worker_id": context.get("worker_id", f"operator-{index}"),
            "isolation_key": context.get("isolation_key"),
            "task_id": task_id,
            "task_spec": task_spec,
            "isolation": context.get("isolation", "worktree"),
            "authority_attempt": batch_attempt,
        }
        if provider_worker is not None:
            item["provider_worker"] = provider_worker
        items.append(item)
    for index in indices:
        step = contract_steps[index - 1] if index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else None
        _assert_task_dependencies_ready(
            run_dir, contract_tasks, index, run_id, step=step, in_batch=set(indices),
        )
    items = _omit_satisfied_dispatch_dependencies(
        items,
        satisfied_aliases=_completed_task_aliases(run_dir, contract_tasks, run_id),
    )
    def _batch_stop_requested() -> bool:
        try:
            current = _load_json(Path(status["run_dir"]) / "state.json")
        except (OSError, TypeError, ValueError):
            return False
        return str(current.get("phase") or "") == "cancelled"

    result = None
    # Lane-parallel wave dispatch: only where the caller has not already asked for
    # something more specific (explicit isolated contexts, an existing worktree
    # queue, or shared-run-forcing task dependencies) -- those keep their own,
    # unchanged path below.
    if (
        not isolated_contexts and worktree_queue is None
        and not has_task_dependencies and len(items) > WAVE_INLINE_MAX_TASKS
    ):
        result = _wave_worktree_dispatch(
            repo_path=Path(status["manifest"].get("repo") or repo).resolve(),
            run_id=run_id, run_dir=run_dir, items=items,
            retry_budget=retry_budget, max_workers=max_workers,
            physical_monitor_kwargs=physical_monitor_kwargs,
            stop_requested=_batch_stop_requested,
        )
    if result is None:
        result = dispatch_operator_batch(
            items,
            max_workers=max_workers,
            retry_budget=retry_budget,
            journal_dir=str(Path(status["run_dir"])),
            worktree_queue=worktree_queue,
            stop_requested=_batch_stop_requested,
            physical_monitor_kwargs=physical_monitor_kwargs,
            provider_worker=provider_worker,
        )
    lifecycle_result: Dict[str, Any]
    try:
        repo_root = Path(status["manifest"].get("repo") or repo).resolve()
        source_commit = str(status["manifest"].get("source_commit") or "")
        if not source_commit:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True,
                text=True, timeout=15, check=False, env=_subprocess_env(),
            )
            source_commit = (head.stdout or "").strip() or "unavailable"
        mapper_generation = str(
            (status["state"].get("mapper") or {}).get("generation")
            or "mapper-unpinned"
        )
        lifecycle = CheckpointLifecycle(
            repo_root / ".simplicio-loop" / "loop-runs",
            task_id=run_id,
            attempt_id=f"batch-{int((status['state'] or {}).get('attempts', 0)) + 1}",
            source_commit=source_commit,
            mapper_generation=mapper_generation,
            base_path=repo_root,
        )
        workers = list(result.get("workers") or [])
        candidate_ids = []
        successful_ids = []
        for worker in sorted(workers, key=lambda row: str(row.get("task_id") or row.get("task_index"))):
            candidate_id = str(worker.get("task_id") or f"task-{worker.get('task_index')}")
            succeeded = worker.get("status") == "succeeded"
            lifecycle.checkpoint(
                candidate_id, "operator", "READY_TO_PROMOTE" if succeeded else "HELD",
                receipts=[value for value in (
                    str(worker.get("operator_receipt") or ""),
                    str(worker.get("evidence_receipt") or ""),
                ) if value],
                work_units=int(worker.get("attempt_count") or 1),
            )
            candidate_ids.append(candidate_id)
            if succeeded:
                successful_ids.append(candidate_id)
        if not any(worker.get("status") == "succeeded" for worker in workers):
            lifecycle_result = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                                "status": "HELD", "reason": "no_successful_candidate"}
        else:
            def _cancel_boundary(candidate_id: str) -> None:
                if worktree_queue is None:
                    return
                for method_name in ("cancel_task", "release_task", "cancel"):
                    method = getattr(worktree_queue, method_name, None)
                    if callable(method):
                        method(candidate_id)
                        return
            selected_winner = sorted(successful_ids)[0]
            lifecycle_result = lifecycle.converge_selected(
                winner_id=selected_winner,
                candidate_ids=candidate_ids,
                shard_id="operator",
                cancel_callback=_cancel_boundary,
            )
    except (LifecycleError, OSError, ValueError, subprocess.SubprocessError) as exc:
        lifecycle_result = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                            "status": "HELD", "reason": "lifecycle_integration_failed",
                            "error": str(exc)}
    result["checkpoint_lifecycle"] = lifecycle_result
    technical_debts: List[Dict[str, Any]] = []
    # Fan-out is an optimization. A safe serial lane is still useful work, so
    # capability loss is recorded as advisory debt instead of a global blocker.
    if auto_reason and auto_reason not in {"explicit_contexts", "single_task", "inline_small_batch"} and len(items) > 1:
        technical_debts.append(_record_technical_debt(
            status["run_dir"],
            run_id=run_id,
            reason_code=auto_reason if auto_reason in {
                "fanout_disabled", "not_git_checkout", "missing_plan_targets",
                "overlapping_task_impacts", "worktree_adapter_unavailable",
                "worktree_preflight_failed",
            } else "fanout_serial_fallback",
            stage="dispatch",
            source="simplicio_loop.runner._auto_worktree_dispatch",
            message="automatic fan-out was not available; continuing with the safe serial lane",
            next_action="install/configure the worktree adapter or split overlapping targets",
        ))
    if not contexts and len(items) > 1:
        # dispatch_operator_batch derives this from the shared isolation key; retain a clear
        # contract-level marker for callers inspecting the convenience API.
        result["serial_fallback_reason"] = result.get("serial_fallback_reason") or (
            "inline_small_batch" if auto_reason == "inline_small_batch" else "shared_run_state"
        )
        if not technical_debts and auto_reason != "inline_small_batch":
            technical_debts.append(_record_technical_debt(
                status["run_dir"],
                run_id=run_id,
                reason_code="fanout_serial_fallback",
                stage="dispatch",
                source="simplicio_loop.runner.dispatch_operator_batch",
                message="tasks share run state or could not be isolated; serial execution preserved safety",
                next_action="provide distinct worktree contexts for independent tasks",
            ))
    result["technical_debts"] = technical_debts
    result["fan_out"] = {
        "enabled": bool(worktree_queue is not None and len(contexts) > 1),
        "default": auto_fan_out is not False,
        "reason": auto_reason or ("isolated_contexts" if contexts else "serial_fallback"),
        "contexts": len(contexts),
    }
    return result
