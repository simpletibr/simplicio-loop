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
from .runner_core import (_subprocess_env, BatchPreflightError, _is_deterministic_operator_failure, BATCH_SCHEMA, NATIVE_PRISM_SCHEMA, _now, _load_json, _write_json, _append_jsonl, _task_goal, WAVE_INLINE_MAX_TASKS, _auto_worktree_dispatch, _task_dependency_references, _task_aliases, _assert_task_dependencies_ready, _item_dependencies, _completed_task_aliases, _omit_satisfied_dispatch_dependencies, _ordered_dispatch_items, read_status)
from .runner_mapper_env import (_mapper_journal_enabled)
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


# Moved to runner_dispatch_batch (#1818). Re-exported here so import paths and patch targets keep working.
from .runner_dispatch_batch import (  # noqa: E402,F401
    dispatch_operator_batch,
)
