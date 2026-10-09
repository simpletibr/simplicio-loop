from __future__ import annotations

import asyncio
import json
import hashlib
import os
import random
import re
import shutil
import signal
import tempfile
import subprocess
import time
import string
import sys
from threading import Thread
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Set, Tuple, TypedDict

from .delivery import (build_delivery_receipt, normalize_delivery_target,
                       reconcile_delivery_observation, write_delivery_receipt)
from .evidence import build_evidence_receipt, redact_sensitive_text
from .source_state import github_delivery_payload, infer_github_delivery_state
from . import github_lifecycle as _github_lifecycle
from . import dashboard_events as _dashboard_events
from .client_integrations import integration_enabled
from .orca_lifecycle import sync_orca_status
from .source_adapter import GitHubSourceAdapter
from .task_contract import compile_many, validate_contract
from .event_metadata import SCHEMA as EVENT_METADATA_SCHEMA, infer_scope
from .technical_debt import record_notice as _record_technical_debt
from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from .operator_bootstrap import (
    OperatorBootstrapError,
    ensure_operators as _ensure_required_operators,
)
from .plan_contract import PLAN_SCHEMA, validate_plan
from .ecc_guidance import (
    ecc_required,
    ensure_ecc_ready,
    extract_guidance_reference,
    inspect_ecc,
)
from .remote_queue import QueueUnavailable
from .receipt_verifier import (EVIDENCE_RECEIPT_SCHEMA as _EVIDENCE_RECEIPT_CONTENT_SCHEMA,
                               OPERATOR_RECEIPT_SCHEMA as _OPERATOR_RECEIPT_CONTENT_SCHEMA,
                               ReceiptStatus, verify_receipt)
from .planning_gate import content_hash as _planning_content_hash
from .planning_gate import evaluate_mutation_authority, mutation_authority_required
from .planning_gate import auto_planning_receipt_enabled
from .planning_gate import build_planning_receipt as _build_planning_receipt
from .planning_gate import publish_planning_receipt as _publish_planning_receipt
from .merge_executor import MergeExecutor, MergeExecutorError
from . import local_capacity
from . import plan_paths
from . import wave_worktree
from .loop_execution_receipt import (
    LoopExecutionReceiptError,
    publish_loop_execution_receipt,
)
from .provider_worker import (
    OPENROUTER_MODEL,
    OpenRouterWorker,
    ProviderWorkerError,
    forwarded_environment,
    proposal_to_mechanical_plan,
)
from .hookwall_gate import (
    HookwallBlocked,
    gate_completion,
    validate_envelope,
    validate_pre_decision,

)
from .hookwall_persistence import HookwallEffectLedger
from .authority_boundary import prepare_authorization_handoff
from .run_journal import RunJournal
from .mapper_run_journal import MapperRunJournal
from .mapper_hookwall import MapperHookwallEffectLedger
from .store_adapter import (
    StorageRoute,
    StorageRouter,
    StoreAdapterError,
    verify_route_receipt,
)
from .stack_lock import (
    StackLock,
    discover_installed_components,
    load_stack_lock,
    write_stack_lock,
)

from .execution_route import _stable_hash as _execution_route_hash
from .execution_route import capability_fingerprint, normalize_capability_manifest, route_receipt_is_current
from .execution_route import decide_route, verify_route_hash
from .openrouter_operator import (
    enabled as _openrouter_operator_enabled,
    external_preflight_admissible as _external_preflight_admissible,
)
try:
    from scripts.agent_identity import ensure_identity
except ImportError:  # pragma: no cover - installed package without scripts namespace
    ensure_identity = None
from .runner_core import (  # noqa: F401
    _subprocess_env,
    OPERATOR_RECEIPT_SCHEMA,
    MAX_PROVIDER_CURRENT_TARGET_CHARS,
    HOST_EDIT_PLAN_SCHEMAS,
    PLAN_REQUIRED,
    DETERMINISTIC_OPERATOR_REASON_CODES,
    BatchPreflightError,
    _classify_devcli_receipt_failure,
    _classify_operator_exception_reason_code,
    _is_deterministic_operator_failure,
    _receipt_max_age_seconds,
    PHASES,
    MAPPER_MIN_VERSION,
    MAPPER_REQUIRED_VERBS,
    DEVCLI_REQUIRED_TOKENS,
    DEVCLI_MIN_VERSION,
    DEVCLI_REQUIRED_CAPABILITIES,
    BATCH_SCHEMA,
    BATCH_PREFLIGHT_SCHEMA,
    NATIVE_PRISM_SCHEMA,
    _now,
    _rand_token,
    _load_json,
    _default_completion_state,
    _completion_state,
    _write_json,
    _verify_run_stack_lock,
    STORAGE_ROUTE_RECEIPT,
    _storage_route_requested,
    _verify_storage_route,
    _append_jsonl,
    _run_cmd,
    _run_repo_path,
    _git_current_branch,
    _dispatch_identity_fields,
    _operator_env,
    _operator_timeout,
    _mapper_timeout_seconds,
    _mapper_supports_command,
    _mapper_inspection_is_fresh,
    _mapper_inspection_reports_stale,
    _degraded_mapper_fallback_enabled,
    _degraded_mapper_payload,
    _devcli_env,
    _devcli_command_path,
    _devcli_cmd,
    _execution_profile,
    _hookwall_digest,
    _is_loop_generated_path,
    _repo_fingerprint,
    _repo_state_equivalent,
    _parse_version_tuple,
    _preflight_override,
    _resolved_identity,
    _criteria_text,
    _constraints_text,
    _task_goal,
    _task_spec_payload,
    _task_spec_hash,
    _derive_context_handle,
    _context_handoff_args,
    _auto_merge_enabled,
    _dispatch_merge_pr,
    WAVE_INLINE_MAX_TASKS,
    _auto_worktree_dispatch,
    _is_tool_cache_path,
    _dependency_references,
    _task_dependency_references,
    _task_aliases,
    _assert_task_dependencies_ready,
    _item_dependencies,
    _completed_task_aliases,
    _omit_satisfied_dispatch_dependencies,
    _ordered_dispatch_items,
    _mapper_journal_enabled,
    read_status,
)  # noqa: F401
from .runner_lifecycle import (  # noqa: F401
    _write_scratchpad,
    _write_watcher_challenge,
    _persist_external_completion_response,
    _ensure_verified_loop_journal,
    _transition,
    _maybe_auto_build_planning_receipt,
    _emit_event,
    _task_ac_ids,
    _run_with_operator_recovery,
)  # noqa: F401
from .runner_plan import (  # noqa: F401
    _mapper_operations_database,
    _ensure_mapper_operations_store,
    _claim_mapper_operation_attempt,
    _validate_minimal_host_plan_paths,
    _compile_minimal_host_plan,
    _resolve_host_edit_plan,
    _finish_operator_blocked,
    _provider_worker_plan,
    _hookwall_ledger,
    _extract_repo_file_hints,
    _build_plan_with_hints,
    _fallback_targets,
    _candidate_targets,
    _build_anchor,
    _operator_receipt_hash,
)  # noqa: F401
from .runner_preflight import (  # noqa: F401
    reset_capability_probe_cache,
    _preflight_mapper,
    DevCliCapabilitiesUnavailableError,
    _preflight_operator,
    _validate_mapper_receipt,
    _mapper_generation,
    _receipt_run_id,
    _require_matching_run_id,
    _require_json_receipt,
    _validate_run_receipts,
    _persist_batch_preflight_block,
    _run_mapper,
    _build_plan,
)  # noqa: F401
from .runner_execute import (  # noqa: F401
    _EffectRequest,
    _terminate_owned_process,
    _execute_operator_effect_unchecked,
    _execute_operator_effect,
    _changed_paths,
    _plan_relevant_changed_paths,
    _restore_operator_checkpoint,
    _operator_run_diff_coverage,
    conclude_run,
    _execute_operator_unleased,
    execute_operator,
)  # noqa: F401
from .runner_lane import (  # noqa: F401
    _operator_dispatch_item,
    _verify_worker_receipt_pair,
    _fanout_execution_route,
    _operator_dispatch_attempt,
    _run_operator_item_process,
)  # noqa: F401
from .runner_wave import (  # noqa: F401
    _resolve_dispatch_mode,
    _load_prior_dispatch_records,
    _operator_worker_limit,
    _build_native_prism_scheduler,
    _prepare_worktree_contexts,
    _ensure_deferred_worktree_context,
    _release_shared_context,
    _wave_worktree_dispatch,
)  # noqa: F401
from .runner_dispatch import (  # noqa: F401
    _dispatch_journal_backend,
    dispatch_operator_batch,
    execute_operator_batch,
)  # noqa: F401

RUNNER_SCHEMA = "simplicio.run-manifest/v1"
STATE_SCHEMA = "simplicio.run-state/v1"


MAINTENANCE_RECEIPT_SCHEMA = "simplicio.maintenance-receipt/v1"

MaintenanceMode = Literal["active", "maintenance_deferred"]
MaintenanceDisposition = Literal["operator", "backlog_only"]


class OperatorDispatchItem(TypedDict, total=False):
    """Typed input contract for :func:`dispatch_operator_batch`."""

    repo: str
    run_id: str
    task_index: int
    worker_id: str
    isolation_key: str
    task_id: str
    task_spec: Mapping[str, Any]
    isolation: str
    operator_context: Mapping[str, Any]
    context_pack: Mapping[str, Any]
    provider_worker: str


class MaintenanceState(TypedDict):
    mode: MaintenanceMode
    disposition: MaintenanceDisposition
    receipt: str
    correction_summary: str
    deferral_reason: str
    evidence_status: str


class MaintenanceDeferredReceipt(TypedDict):
    schema: str
    mode: Literal["maintenance_deferred"]
    disposition: Literal["backlog_only"]
    correction_summary: str
    deferral_reason: str
    resume_instructions: List[str]
    evidence_status: str
    recorded_at: str
    completion_ready: bool
    completion_verdict: str
    completion_reason_code: str


def _run_id() -> str:
    return time.strftime("run-%Y%m%d-%H%M%S-", time.gmtime()) + _rand_token(8)


def _default_maintenance_state() -> MaintenanceState:
    return {
        "mode": "active",
        "disposition": "operator",
        "receipt": "",
        "correction_summary": "",
        "deferral_reason": "",
        "evidence_status": "UNVERIFIED",
    }


def _active_maintenance_state(current: Mapping[str, Any] | None = None) -> MaintenanceState:
    payload = dict(current or {})
    return {
        "mode": "active",
        "disposition": "operator",
        "receipt": str(payload.get("receipt") or ""),
        "correction_summary": str(payload.get("correction_summary") or ""),
        "deferral_reason": str(payload.get("deferral_reason") or ""),
        "evidence_status": str(payload.get("evidence_status") or "UNVERIFIED"),
    }


def _freeze_stack_lock(run_root: Path, run_id: str) -> StackLock:
    """Freeze installed component identity before Mapper scan or mutation authority."""
    route = _execution_profile()
    lock = StackLock.create(
        discover_installed_components(),
        route,
        run_id=run_id,
    )
    write_stack_lock(lock, run_root / "stack-lock.json")
    return lock


def _freeze_storage_route(run_root: Path, run_id: str) -> dict[str, Any]:
    """Select and persist the store route before any mapper-backed operation."""
    router = StorageRouter(requested=_storage_route_requested(), run_id=run_id)
    router.freeze("run_bootstrap")
    receipt = router.receipt()
    _write_json(run_root / STORAGE_ROUTE_RECEIPT, receipt)
    return receipt


def _write_maintenance_deferred_receipt(
    run_dir: Path,
    *,
    correction_summary: str,
    deferral_reason: str,
    resume_instructions: Sequence[str] | str,
    evidence_status: str,
) -> MaintenanceDeferredReceipt:
    completion = _completion_state(run_dir)
    instructions = [str(item).strip() for item in resume_instructions] if not isinstance(resume_instructions, str) else [resume_instructions.strip()]
    payload: MaintenanceDeferredReceipt = {
        "schema": MAINTENANCE_RECEIPT_SCHEMA,
        "mode": "maintenance_deferred",
        "disposition": "backlog_only",
        "correction_summary": correction_summary.strip(),
        "deferral_reason": deferral_reason.strip(),
        "resume_instructions": [item for item in instructions if item],
        "evidence_status": str(evidence_status or "UNVERIFIED"),
        "recorded_at": _now(),
        "completion_ready": False,
        "completion_verdict": str(completion.get("verdict") or "DELIVERY_PENDING"),
        "completion_reason_code": str(completion.get("reason_code") or "oracle_incomplete"),
    }
    _write_json(run_dir / "maintenance-receipt.json", payload)
    return payload


def _contract_path(run_dir: Path) -> Path:
    return run_dir / "task-contract.json"


def _coverage(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_scenarios = 0
    total_rules = 0
    for task in tasks:
        total_scenarios += len(task.get("scenarios") or [])
        total_rules += len(task.get("rules") or [])
    return {
        "scenarios": {"verified": 0, "total": total_scenarios},
        "rules": {"verified": 0, "total": total_rules},
    }


def _prepare_operator_receipt(repo_path: Path, run_root: Path, task: Dict[str, Any],
                              target: str) -> Dict[str, Any]:
    try:
        target_path = (repo_path / target).resolve() if not Path(target).is_absolute() else Path(target).resolve()
        target_path.relative_to(repo_path.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"operator target outside authorized repo: {target!r}") from exc
    _preflight_operator(repo_path, run_root)
    task_spec_path = run_root / "task-spec.json"
    task_spec = _task_spec_payload(task)
    preflight_task_spec_placeholder = not task_spec.get("verification_commands")
    if preflight_task_spec_placeholder:
        task_spec["verification_commands"] = [{"command": "true", "verifier": "preflight-placeholder"}]
    task_spec_hash = _task_spec_hash(task_spec)
    _write_json(task_spec_path, task_spec)
    preflight_identity = f"{run_root.name}:preflight"
    _context_args, context_handoff = _context_handoff_args(
        repo_path,
        run_root,
        attempt_id=preflight_identity,
        lease_id=preflight_identity,
        fencing_token="1",
    )
    context_handoff["purpose"] = "read_only_preflight"
    fake = os.environ.get("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", "").strip()
    if fake:
        payload = json.loads(fake)
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": payload.get("execution_state", "dry_run"),
            "target": target,
            "goal": _task_goal(task),
            "argv": payload.get("argv", []),
            "returncode": payload.get("returncode", 0),
            "stdout": payload.get("stdout", {}),
            "stderr": payload.get("stderr", ""),
            "timed_out": False,
            "measured_at": _now(),
            "source": "env_override",
            "context_handoff": context_handoff,
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
        ecc_reference = extract_guidance_reference(receipt)
        if ecc_reference is not None:
            receipt["ecc_guidance_ref"] = ecc_reference
        _write_json(run_root / "operator-receipt.json", receipt)
        return receipt

    # The host writes the edit plan; there is none yet at prepare time. The
    # dry run proves the operator accepts a plan (the surface tick/wave use)
    # without the forbidden prose `task` path, which Dev CLI answers with
    # plan_required.
    argv = _devcli_cmd(repo_path, "edit", "--help")
    try:
        op_env = _devcli_env(repo_path, _operator_env())
        # Dev CLI is deterministic-only.  Any configured OpenRouter credential
        # belongs exclusively to the Loop coordinator and must not cross the
        # subprocess boundary during read-only preflight.
        op_env.pop("OPENROUTER_API_KEY", None)
        if not op_env.get("SIMPLICIO_RUNTIME_URL", "").strip():
            op_env.setdefault("SIMPLICIO_RUNTIME_OFFLINE", "1")
        preflight_test_command = op_env.get("SIMPLICIO_TEST_CMD", "").strip()
        if not preflight_test_command:
            preflight_test_command = "true"
            op_env["SIMPLICIO_TEST_CMD"] = preflight_test_command
        context_handoff["preflight_verification"] = {
            "command": preflight_test_command,
            "placeholder": preflight_test_command == "true",
            "scope": "dry_run_only",
            "task_spec_placeholder": preflight_task_spec_placeholder,
        }
        result = subprocess.run(
            argv,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=_operator_timeout("dry_run"),
            env=op_env,
        )
        stdout = (result.stdout or "").strip()
        parsed = {}
        if stdout:
            try:
                parsed = json.loads(stdout)
            except ValueError:
                parsed = {"raw": stdout}
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": "dry_run" if result.returncode == 0 else "blocked",
            "target": target,
            "goal": _task_goal(task),
            "argv": argv,
            "returncode": result.returncode,
            "stdout": parsed,
            "stderr": (result.stderr or "").strip(),
            "timed_out": False,
            "measured_at": _now(),
            "source": "live_cli",
            "context_handoff": context_handoff,
            "provider_config": {
                "model": op_env.get("SIMPLICIO_MODEL", ""),
                "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
            },
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
    except subprocess.TimeoutExpired as exc:
        op_env = _operator_env()
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "target": target,
            "goal": _task_goal(task),
            "argv": argv,
            "returncode": None,
            "stdout": {},
            "stderr": f"timed out after {exc.timeout}s",
            "timed_out": True,
            "measured_at": _now(),
            "source": "live_cli",
            "context_handoff": context_handoff,
            "provider_config": {
                "model": op_env.get("SIMPLICIO_MODEL", ""),
                "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
            },
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
    ecc_reference = extract_guidance_reference(receipt)
    if ecc_reference is not None:
        receipt["ecc_guidance_ref"] = ecc_reference
    _write_json(run_root / "operator-receipt.json", receipt)
    return receipt


def arm_run(repo: str, task_path: str, delivery: str, max_iterations: int) -> Dict[str, Any]:
    repo_path = Path(repo).resolve()
    delivery = normalize_delivery_target(delivery)
    raw = Path(task_path).read_text(encoding="utf-8")
    compiled = compile_many(raw, source_path=str(Path(task_path).resolve()))
    tasks = compiled.get("tasks") or []
    validation_errors: List[str] = []
    validation_warnings: List[str] = []
    for idx, task in enumerate(tasks, start=1):
        verdict = validate_contract(task)
        validation_errors.extend([f"task[{idx}] {e}" for e in verdict["errors"]])
        validation_warnings.extend([f"task[{idx}] {w}" for w in verdict["warnings"]])
    if validation_errors:
        raise ValueError("invalid task contract: " + "; ".join(validation_errors))

    run_id = _run_id()
    # Keep loop run state under .simplicio-loop/ (which simplicio-mapper ignores for
    # freshness) instead of .simplicio-loop/orchestrator/ (which the mapper sees as repo churn and
    # marks artifacts_not_fresh, blocking the loop before any implementation work).
    run_root = repo_path / ".simplicio-loop" / "loop-runs" / run_id
    loop_dir = run_root / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    # Keep the append-only loop attempt-memory artifact present even when the
    # run uses the MapperStore-backed lifecycle journal. A later verified run
    # appends its measured gate result without replacing prior records.
    (loop_dir / "journal.jsonl").touch(exist_ok=True)

    promise = f"run-{run_id}-verified"
    manifest = {
        "schema": RUNNER_SCHEMA,
        "run_id": run_id,
        "repo": str(repo_path),
        "task_path": str(Path(task_path).resolve()),
        "delivery_target": delivery,
        "max_iterations": max_iterations,
        "completion_promise": promise,
        "created_at": _now(),
        "task_count": compiled["task_count"],
        "collection_hash": compiled["collection_hash"],
    }
    _write_json(run_root / "manifest.json", manifest)
    _write_json(run_root / "task-contract.json", compiled)
    _write_json(loop_dir / "anchor.json", _build_anchor(tasks, compiled["collection_hash"]))
    goal = "\n\n".join([_task_goal(task) for task in tasks if _task_goal(task)]).strip() or raw.strip()
    _write_scratchpad(loop_dir, goal, max_iterations, promise)
    first_goal_fp = (tasks[0].get("source") or {}).get("hash", "") if tasks else ""
    _write_watcher_challenge(loop_dir, first_goal_fp)
    state = {
        "schema": STATE_SCHEMA,
        "run_id": run_id,
        "phase": "intake",
        "delivery_target": delivery,
        "created_at": _now(),
        "updated_at": _now(),
        "task_count": compiled["task_count"],
        "coverage": _coverage(tasks),
        "validation": {"errors": validation_errors, "warnings": validation_warnings},
        "current_action": "task_contract_compiled",
        "next_action": "mapper_scan_required",
        "delivery": {"target": delivery, "current_state": "planned", "ready": False, "receipt": ""},
        "completion": _default_completion_state(),
        "maintenance": _default_maintenance_state(),
        "stack_lock": {
            "ready": False,
            "path": str(run_root / "stack-lock.json"),
            "route": "",
            "lock_hash": "",
            "status": "UNVERIFIED",
        },
        "storage_route": {
            "ready": False,
            "path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "requested": _storage_route_requested(),
            "selected": "",
            "generation": "",
            "receipt_hash": "",
            "status": "UNVERIFIED",
        },
        "mapper": {"ready": False, "receipt": "", "targets": []},
        "operator": {"ready": False, "receipt": "", "target": "", "execution_state": "proposed"},
        "evidence": {"ready": False, "receipt": "", "status": "UNVERIFIED"},
        "blockers": [],
        "attempts": 0,
        "history": [],
        "events": [],
        "task_ids": [str(task.get("id") or "") for task in tasks if task.get("id")],
        "ac_ids": [ac_id for task in tasks for ac_id in _task_ac_ids(task)],
    }
    _write_json(run_root / "state.json", state)
    armed = {
        "ts": _now(),
        "from": None,
        "to": "intake",
        "reason": "run armed from raw task",
        "receipt": str(run_root / "task-contract.json"),
    }
    _append_jsonl(run_root / "transitions.jsonl", armed)
    _dashboard_events.emit_transition(run_root, armed, run_id=run_id)
    _emit_event(run_root, state, "contract_frozen", receipt=str(run_root / "task-contract.json"),
                message="task contract compiled and frozen")
    _emit_event(run_root, state, "watcher_challenge", receipt=str(loop_dir / "watcher_challenge.json"),
                message="watcher challenge created")
    try:
        stack_lock = _freeze_stack_lock(run_root, run_id)
        manifest.update({
            "stack_lock_path": str(run_root / "stack-lock.json"),
            "stack_lock_hash": stack_lock.lock_hash,
            "execution_profile": stack_lock.route,
        })
        _write_json(run_root / "manifest.json", manifest)
        state = _load_json(run_root / "state.json")
        state["stack_lock"] = {
            "ready": True,
            "path": str(run_root / "stack-lock.json"),
            "route": stack_lock.route,
            "lock_hash": stack_lock.lock_hash,
            "status": "MEASURED",
        }
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "stack_lock_frozen",
                    receipt=str(run_root / "stack-lock.json"),
                    message="installed stack lock frozen before Mapper scan")
        storage_route = _freeze_storage_route(run_root, run_id)
        _ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
        manifest.update({
            "storage_route_path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "storage_route_hash": storage_route.get("receipt_hash", ""),
            "storage_route": storage_route.get("selected"),
            "storage_route_generation": storage_route.get("generation", ""),
        })
        _write_json(run_root / "manifest.json", manifest)
        state = _load_json(run_root / "state.json")
        state["storage_route"] = {
            "ready": True,
            "path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "requested": storage_route.get("requested", ""),
            "selected": storage_route.get("selected", ""),
            "generation": storage_route.get("generation", ""),
            "receipt_hash": storage_route.get("receipt_hash", ""),
            "status": "MEASURED",
        }
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "storage_route_frozen",
                    receipt=str(run_root / STORAGE_ROUTE_RECEIPT),
                    message="store route selected and frozen before Mapper scan",
                    route=storage_route.get("selected"),
                    generation=storage_route.get("generation"),
                    receipt_hash=storage_route.get("receipt_hash"))
        _transition(run_root, state, "mapping", "stack and storage routes frozen; mapper required",
                    receipt=str(run_root / "stack-lock.json"))
        primary_goal = _task_goal(tasks[0]) if tasks else raw.strip()
        mapper_payload = _run_with_operator_recovery(
            "simplicio-mapper",
            run_root,
            lambda: _run_mapper(
                repo_path,
                run_root,
                task_path=str(Path(task_path).resolve()),
                goal=primary_goal,
                task_fingerprint=compiled["collection_hash"],
                target_hint=next(iter(_extract_repo_file_hints(raw, repo_path)), ""),
            ),
        )
        mapper_payload["run_id"] = run_id
        mapper_payload["task_contract_hash"] = compiled["collection_hash"]
        _write_json(run_root / "mapper-context.json", mapper_payload)
        state = _load_json(run_root / "state.json")
        mapper_degraded = bool(mapper_payload.get("degraded_local"))
        state["mapper"] = {
            "ready": True,
            "receipt": str(run_root / "mapper-context.json"),
            "targets": _candidate_targets(mapper_payload, repo_path),
            "degraded": mapper_degraded,
            "status": "UNVERIFIED" if mapper_degraded else "MEASURED",
            "ecc_admission": dict(mapper_payload.get("ecc_admission") or {}),
        }
        state["current_action"] = "mapper_context_degraded" if mapper_degraded else "mapper_context_persisted"
        state["next_action"] = "plan_ready_for_decision"
        _write_json(run_root / "state.json", state)
        if mapper_degraded:
            _emit_event(run_root, state, "mapper_degraded", receipt=str(run_root / "mapper-context.json"),
                        blocker="mapper_deep_pass_unavailable",
                        message="continuing with explicit-target local context; evidence is UNVERIFIED")
            _transition(run_root, state, "planning", "local context fallback persisted; mapper evidence is UNVERIFIED",
                        receipt=str(run_root / "mapper-context.json"))
        else:
            _emit_event(run_root, state, "mapper_fresh", receipt=str(run_root / "mapper-context.json"),
                        message="mapper scan, inspect, and handoff are fresh")
            _transition(run_root, state, "planning", "mapper scan/inspect/handoff persisted",
                        receipt=str(run_root / "mapper-context.json"))
        plan = _build_plan_with_hints(tasks, mapper_payload, repo_path, raw,
                                      contract_hash=compiled["collection_hash"])
        plan["run_id"] = run_id
        plan["mapper_context_hash"] = hashlib.sha256(
            (run_root / "mapper-context.json").read_bytes()
        ).hexdigest()
        plan_validation = validate_plan(
            plan, tasks, repo_path,
            contract_hash=compiled["collection_hash"],
            current_state=_repo_fingerprint(repo_path),
        )
        plan["validation"] = plan_validation
        if not plan_validation["valid"]:
            if any("targets_missing" in error for error in plan_validation["errors"]):
                raise RuntimeError("mapper-derived plan has no authorized operator target")
            raise RuntimeError("mapper-derived plan failed validation: " + ", ".join(plan_validation["errors"]))
        _write_json(run_root / "plan.json", plan)
        state = _load_json(run_root / "state.json")
        state["current_action"] = "plan_materialized"
        _maybe_auto_build_planning_receipt(run_root, state, run_id, compiled, plan, plan_validation, repo_path)
        candidates = ((plan.get("steps") or [{}])[0].get("candidate_targets") or [])
        if not candidates:
            raise RuntimeError("mapper-derived plan has no authorized operator target")
        receipt = _run_with_operator_recovery(
            "simplicio-dev-cli",
            run_root,
            lambda: _prepare_operator_receipt(
                repo_path, run_root, tasks[0], candidates[0]
            ),
        )
        plan_hash = hashlib.sha256((run_root / "plan.json").read_bytes()).hexdigest()
        receipt["run_id"] = run_id
        receipt["task_contract_hash"] = compiled["collection_hash"]
        receipt["plan_hash"] = plan_hash
        receipt["mapper_pack_hash"] = plan.get("mapper_pack_hash", "")
        receipt["mapper_context_hash"] = plan.get("mapper_context_hash", "")
        receipt["authorized_targets"] = [candidates[0]]
        receipt["target_within_repo"] = True
        _write_json(run_root / "operator-receipt.json", receipt)
        preflight_ok = receipt.get("execution_state") == "dry_run" and receipt.get("returncode") == 0
        external_preflight = _external_preflight_admissible(receipt)
        if external_preflight:
            # Dev CLI's deterministic-only policy is an expected, explicit block
            # during read-only preflight.  The configured external coordinator
            # supplies the mechanical plan at the mutation boundary; preserve the
            # raw non-zero result and record why this preflight is admissible.
            receipt["external_coordinator"] = {
                "provider": "openrouter",
                "route": "openrouter-to-mechanical-edit",
                "preflight_status": "admitted_with_explicit_dev_cli_llm_block",
                "raw_reason_code": "llm_execution_disabled",
            }
            receipt["preflight_admitted"] = True
        if not preflight_ok and not external_preflight:
            stdout_payload = receipt.get("stdout") if isinstance(receipt.get("stdout"), Mapping) else {}
            blocked = stdout_payload.get("blocked_preconditions") if isinstance(stdout_payload, Mapping) else []
            reason = ""
            if isinstance(blocked, list) and blocked:
                first = blocked[0] if isinstance(blocked[0], Mapping) else {}
                reason = str(first.get("code") or first.get("message") or "")
            if not reason and isinstance(stdout_payload.get("execution_profile"), Mapping):
                reason = str(stdout_payload["execution_profile"].get("reason_code") or "")
            raise RuntimeError(
                "operator preflight blocked the run: "
                + (reason or str(receipt.get("stderr") or receipt.get("execution_state") or "unknown failure"))
            )
        state["operator"] = {
            "ready": True,
            "receipt": str(run_root / "operator-receipt.json"),
            "target": candidates[0],
            "execution_state": receipt.get("execution_state", "proposed"),
            "ecc_guidance_ref": receipt.get("ecc_guidance_ref"),
        }
        evidence = build_evidence_receipt(str(run_root))
        _write_json(run_root / "evidence-receipt.json", evidence)
        state["evidence"] = {
            "ready": False,
            "receipt": str(run_root / "evidence-receipt.json"),
            "status": evidence.get("status", "UNVERIFIED"),
        }
        delivery_receipt = build_delivery_receipt(str(run_root), delivery, current_state="implemented")
        write_delivery_receipt(str(run_root), delivery_receipt)
        state["delivery"] = {
            "target": delivery,
            "current_state": delivery_receipt["current_state"],
            "ready": delivery_receipt["ready"],
            "receipt": str(run_root / "delivery-receipt.json"),
            "source_checked_at": delivery_receipt["source_checked_at"],
        }
        state["current_action"] = "operator_dry_run_recorded"
        state["next_action"] = "await_operator_decision"
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "plan_ready", receipt=str(run_root / "plan.json"),
                    message="validated plan materialized")
        if state.get("operator", {}).get("receipt"):
            _emit_event(run_root, state, "operator_receipt",
                        receipt=str(run_root / "operator-receipt.json"),
                        message="operator dry-run receipt persisted")
        _transition(run_root, state, "awaiting_decision", "plan derived from task contract + mapper",
                    receipt=str(run_root / "plan.json"))
    except Exception as exc:
        state = _load_json(run_root / "state.json")
        message = str(exc)
        if "no authorized operator target" in message or "operator preflight blocked" in message:
            state["blockers"] = [{
                "kind": "run_preflight",
                "reason_code": "no_authorized_target" if "target" in message else "operator_dry_run_failed",
                "message": message,
                "run_id": run_id,
            }]
        else:
            state["blockers"] = [message]
        state["current_action"] = "mapping_failed"
        state["next_action"] = "repair_mapper_or_repo"
        evidence_path = run_root / "evidence-receipt.json"
        if not evidence_path.exists():
            mapper_path = run_root / "mapper-context.json"
            operator_path = run_root / "operator-receipt.json"
            plan_path = run_root / "plan.json"
            if not plan_path.exists() and not mapper_path.exists():
                _write_json(mapper_path, {
                    "run_id": run_id,
                    "task_contract_hash": compiled["collection_hash"],
                    "status": "blocked",
                    "error": message,
                })
            if not plan_path.exists() and not operator_path.exists():
                _write_json(operator_path, {
                    "schema": OPERATOR_RECEIPT_SCHEMA,
                    "run_id": run_id,
                    "task_contract_hash": compiled["collection_hash"],
                    "execution_state": "blocked",
                    "status": "blocked",
                    "returncode": None,
                    "changed_paths": [],
                    "error": message,
                })
            if mapper_path.exists() and operator_path.exists():
                evidence = build_evidence_receipt(str(run_root))
                _write_json(evidence_path, evidence)
                state["evidence"] = {
                    "ready": False,
                    "receipt": str(evidence_path),
                    "status": evidence.get("status", "UNVERIFIED"),
                }
        _write_json(run_root / "state.json", state)
        _transition(run_root, state, "blocked", "mapper integration failed",
                    receipt=str(run_root / "mapper-context.json"), extra={"error": str(exc)})
    return {"manifest": manifest, "state": _load_json(run_root / "state.json"), "run_dir": str(run_root)}


def _watcher_script() -> Path:
    """The watcher shipped with this package; SIMPLICIO_LOOP_REPO points it at the target."""
    return Path(__file__).resolve().parent / "_bundle" / "scripts" / "watcher_verify.py"


def _ensure_current_quality_matrix(repo_path: Path, run_dir: Path) -> None:
    """Keep ``quality-matrix.json`` from going stale across a run's own separate ticks.

    `verify_run` (via `_finalize_public_flow`) runs after *every* `tick`/`wave
    --task-indices`, not only once at the very end -- so the first call to
    reach this run can build `quality-matrix.json` while other tasks are
    still pending (correctly reporting them missing at that moment). The
    independent watcher (`scripts/watcher_verify.py`, invoked right after
    this) re-derives its verdict from that SAME on-disk receipt via
    `quality_matrix.independent_reverify_quality_matrix`'s self-reported half
    -- so a cache that is never refreshed keeps reporting those tasks
    missing forever, even after a later task's own separate process applied
    them. Rebuild it whenever the applied/missing task set it once measured
    no longer matches what's actually on disk now; a matrix that already
    reports every task applied is left alone (no need to re-run the lane
    commands on every verify call).
    """
    from .lane_verifiers import build_quality_matrix, missing_or_unapplied_tasks

    quality_matrix_path = run_dir / "quality-matrix.json"
    contract = _load_json(run_dir / "task-contract.json")
    task_texts = [str(t.get("original_text") or "") for t in contract.get("tasks") or []]
    rebuild = not quality_matrix_path.exists()
    if not rebuild:
        try:
            cached_matrix = _load_json(quality_matrix_path)
        except (OSError, TypeError, ValueError):
            cached_matrix = {}
        cached_missing = (
            (cached_matrix.get("requirements") or {}).get("implementation") or {}
        ).get("missing_task_indices")
        if cached_missing:
            rebuild = missing_or_unapplied_tasks(run_dir, len(task_texts)) != cached_missing
    if rebuild:
        build_quality_matrix(repo_path, run_dir, task_texts)


def verify_run(repo: str, run_id: str, *, flow: str = "run") -> Dict[str, Any]:
    """Run the independent watcher and advance a run without a manual tick."""
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    state = status["state"]
    if state.get("phase") in {"done", "cancelled"}:
        return status
    watcher = _watcher_script()
    if not watcher.exists():
        state["blockers"] = ["watcher_verify.py is unavailable"]
        state["current_action"] = "watcher_unavailable"
        state["next_action"] = "inspect_and_recover"
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "independent watcher is unavailable", receipt=str(run_dir / "state.json"))
        return read_status(repo, run_id)
    # Parallel lanes each write evidence after their own task; re-measure on the
    # final tree so the watcher compares against the diff it will actually see.
    # This must run BEFORE `_ensure_current_quality_matrix` below: rebuilding
    # the quality matrix runs the task's own lane commands (pytest, coverage,
    # ...), which write byproducts (e.g. `.coverage`) to the tree -- doing
    # that first would make the evidence receipt's diff-coverage check see
    # those byproducts as an "uncovered diff outside operator receipt".
    _write_json(run_dir / "evidence-receipt.json", build_evidence_receipt(str(run_dir)))
    # A run-scoped contract (task-contract.json) always exists by the time a
    # run can be verified; only a synthetic/legacy caller without one skips
    # this (there is then no task list to measure "missing" against anyway).
    # Must run BEFORE the watcher below: the watcher independently re-derives
    # its verdict from this SAME on-disk quality-matrix.json, so a stale one
    # (a dependent task applied through its own separate `tick` process since
    # this receipt was last built) would fail the watcher before this
    # function's own later, redundant freshness check ever runs.
    if (run_dir / "task-contract.json").is_file():
        _ensure_current_quality_matrix(repo_path, run_dir)
    _transition(run_dir, state, "watching", "automatic conduct reached independent verification", receipt=str(run_dir / "operator-receipt.json"))
    env = _subprocess_env()
    env["SIMPLICIO_RUN_DIR"] = str(run_dir)
    env["SIMPLICIO_LOOP_REPO"] = str(repo_path)
    env["SIMPLICIO_LOOP_DIR"] = str(run_dir / "loop")
    result = subprocess.run([sys.executable, str(watcher), "verify"], cwd=str(repo_path), capture_output=True, text=True, timeout=180, env=env)
    output = redact_sensitive_text((result.stdout or "") + (result.stderr or "")).strip()
    _write_json(run_dir / "watcher-receipt.json", {"schema": "simplicio.watcher-invocation/v1", "returncode": result.returncode, "output": output, "receipt": str(run_dir / "loop" / "watcher_state.json"), "checked_at": _now()})
    watcher_path = run_dir / "loop" / "watcher_state.json"
    watcher_state = _load_json(watcher_path) if watcher_path.exists() else {}
    if result.returncode != 0 or watcher_state.get("status") != "MEASURED" or not watcher_state.get("match"):
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [watcher_state.get("reported") or output or "watcher verification failed"]
        state["current_action"] = "watcher_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {"ready": False, "receipt": str(watcher_path), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "independent watcher rejected the run", receipt=str(watcher_path))
        return read_status(repo, run_id)
    state = read_status(repo, run_id)["state"]
    state["evidence"] = {"ready": True, "receipt": str(watcher_path), "status": "MEASURED"}
    state["current_action"] = "watcher_verified"
    state["next_action"] = "delivery_reconciliation"
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "delivering", "independent watcher measured all acceptance criteria", receipt=str(watcher_path))
    evidence_payload = {}
    try:
        evidence_receipt = _load_json(run_dir / "evidence-receipt.json")
        evidence_payload = {
            "evidence_receipt": str(run_dir / "evidence-receipt.json"),
            "criteria_verified": int(
                (evidence_receipt.get("summary") or {}).get("criteria_verified") or 0
            ),
        }
    except (OSError, TypeError, ValueError):
        evidence_payload = {}
    delivered = reconcile_delivery(
        repo, run_id, "verified", source_kind="local", source_payload=evidence_payload
    )
    if not delivered["state"].get("delivery", {}).get("ready"):
        return delivered
    state = delivered["state"]
    state["current_action"] = "run_verified"
    state["next_action"] = "none"
    state["completion"] = {"ready": True, "receipt": str(watcher_path), "verdict": "VERIFIED", "reason_code": "watcher_and_delivery_verified", "tag": "MEASURED"}
    _write_json(run_dir / "state.json", state)
    # wi612 (#612): Quality Matrix + Completion Oracle obrigatorios antes do done (elimina bypass).
    from . import oracle as _oracle
    if not (run_dir / "quality-matrix.json").exists():
        from .lane_verifiers import build_quality_matrix
        contract = _load_json(run_dir / "task-contract.json")
        build_quality_matrix(repo_path, run_dir,
                             [str(t.get("original_text") or "") for t in contract.get("tasks") or []])
    _qm_ok, _qm_gate, _qm_verdict = _oracle._quality_matrix_gate(run_dir)
    if not _qm_ok:
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [_qm_verdict.get("reason", "quality matrix incomplete")]
        state["current_action"] = "quality_matrix_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "quality_matrix_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "quality-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "quality matrix gate rejected the run", receipt=str(run_dir / "quality-matrix.json"))
        return read_status(repo, run_id)
    _persist_external_completion_response(run_dir)
    _oracle_matrix = _oracle.evaluate_matrix(str(run_dir / "loop"), str(run_dir))
    _write_json(run_dir / "oracle-matrix.json", _oracle_matrix)
    if not _oracle_matrix.get("parity") or not all(a["ready"] for a in _oracle_matrix.get("adapters", [])):
        state = read_status(repo, run_id)["state"]
        state["blockers"] = ["completion oracle incomplete: " + str(_oracle_matrix.get("signature"))]
        state["current_action"] = "oracle_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "oracle_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "oracle-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "completion oracle rejected the run", receipt=str(run_dir / "oracle-matrix.json"))
        return read_status(repo, run_id)
    try:
        _ensure_verified_loop_journal(run_dir)
        publication_args = {
            "repo": repo_path,
            "run_dir": run_dir,
            "manifest": status["manifest"],
        }
        if flow != "run":
            publication_args["flow"] = flow
        loop_execution = publish_loop_execution_receipt(**publication_args)
        if loop_execution.get("status") != "VERIFIED":
            raise LoopExecutionReceiptError(
                "loop-execution receipt did not reach VERIFIED status"
            )
    except LoopExecutionReceiptError as exc:
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [f"loop-execution receipt publication failed: {exc}"]
        state["current_action"] = "loop_execution_receipt_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {
            "ready": False,
            "receipt": str(repo_path / ".simplicio-loop" / "loop-execution.json"),
            "status": "UNVERIFIED",
        }
        _write_json(run_dir / "state.json", state)
        _transition(
            run_dir,
            state,
            "blocked",
            "loop-execution receipt could not be published",
            receipt=str(run_dir / "state.json"),
        )
        return read_status(repo, run_id)
    state = read_status(repo, run_id)["state"]
    state["loop_execution"] = loop_execution
    state["blockers"] = []
    state["degraded"] = False
    _transition(run_dir, state, "done", "automatic task-to-verify conduct completed", receipt=str(watcher_path))
    return read_status(repo, run_id)


def _conduct_run(repo: str, task_path: str, delivery: str = "verified", max_iterations: int = 12, *, retry_budget: int = 3, quality_provider: Optional[str] = None, quality_policy: str = "strict-default", provider_worker: str | None = None) -> Dict[str, Any]:
    """Arm, execute, and independently verify one run as one durable operation.

    Issue #279: this boundary must never leave a run partially armed.  Either the full
    mapper -> plan -> operator preflight -> batch chain succeeds, or the run is left (and
    reported) explicitly ``blocked`` with a diagnostic receipt.  ``execute_operator_batch``
    already fails closed and persists a batch-preflight-block diagnostic before raising when
    the receipt chain is missing or stale, but that exception must not escape uncaught here --
    an uncaught exception is itself a partially-armed, undiagnosed state from the CLI's
    perspective.
    """
    armed = arm_run(repo, task_path, delivery, max_iterations)
    run_id = armed["manifest"]["run_id"]
    if armed["state"].get("phase") == "blocked":
        return armed
    try:
        # The public ``run`` path is intentionally zero-config: let the operator
        # derive its worker demand from the task set and let the physical admission
        # monitor choose the safe concurrency.  Callers that need a deterministic
        # serial lane can still use the explicit ``batch --serial`` surface.
        batch = execute_operator_batch(
            repo,
            run_id,
            max_workers=None,
            retry_budget=retry_budget,
            auto_fan_out=None,
            provider_worker=provider_worker,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        status = read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        state = status["state"]
        if state.get("phase") != "blocked":
            # Defensive fallback: execute_operator_batch's own preflight boundary is
            # expected to have already persisted a blocked diagnostic before raising, but
            # guarantee the run never surfaces as anything other than explicitly blocked.
            _transition(run_dir, state, "blocked",
                        "batch dispatch failed before dispatch", extra={"error": str(exc)})
            status = read_status(repo, run_id)
        return status
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    workers = list(batch.get("workers") or [])
    non_success_workers = [
        worker for worker in workers
        if str(worker.get("status") or "") != "succeeded"
    ]
    failed_indices = list(batch.get("failed_task_indices") or [])
    blocked_indices = list(batch.get("blocked_task_indices") or [])
    dead_letter_indices = list(batch.get("dead_letter_task_indices") or [])
    if (
        failed_indices
        or blocked_indices
        or dead_letter_indices
        or non_success_workers
        or status["state"].get("phase") == "blocked"
    ):
        # A worker can be ``blocked``/``paused`` without appearing in
        # ``failed_task_indices`` (for example when the physical governor
        # terminates admission).  Do not run the independent watcher against
        # that pre-mutation state: surface the real operator reason first.
        state = status["state"]
        if state.get("phase") not in {"blocked", "done", "cancelled"}:
            first_failure = non_success_workers[0] if non_success_workers else {}
            reason = (
                first_failure.get("reason")
                or first_failure.get("error")
                or first_failure.get("reason_code")
                or "operator batch did not produce successful worker receipts"
            )
            state["blockers"] = [str(reason)]
            state["current_action"] = "operator_batch_blocked"
            state["next_action"] = "inspect_and_recover"
            _write_json(run_dir / "state.json", state)
            _transition(
                run_dir,
                state,
                "blocked",
                "operator batch returned a non-success worker",
                receipt=str(run_dir / "operator-batch.json"),
                extra={
                    "failed_task_indices": failed_indices,
                    "blocked_task_indices": blocked_indices,
                    "dead_letter_task_indices": dead_letter_indices,
                },
            )
        return read_status(repo, run_id)
    # An explicitly selected quality provider runs after execution and before
    # the watcher/delivery/Completion Oracle. Once selected, it remains
    # fail-closed: there is no fallback for an unavailable or failing provider.
    if quality_provider:
        from .quality_provider import conduct_quality
        run_dir = Path(status["run_dir"])
        head = status.get("manifest", {}).get("head", "") or ""
        diff_hash = status.get("manifest", {}).get("diff_hash", "") or ""
        q = conduct_quality(
            repo, run_id,
            quality_provider=quality_provider, quality_policy=quality_policy,
            attempt=status["state"].get("attempt", 1), head=head, diff_hash=diff_hash,
        )
        if q.get("status") == "BLOCKED":
            state = read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("reason", "quality provider blocked the run")]
            state["current_action"] = "quality_blocked"
            state["next_action"] = "inspect_and_recover"
            state["evidence"] = {
                "ready": False,
                "receipt": str(run_dir / "quality-matrix.json"),
                "status": "UNVERIFIED",
            }
            _write_json(run_dir / "state.json", state)
            _transition(run_dir, state, "blocked",
                        "quality provider blocked the run (fail-closed)",
                        receipt=str(run_dir / "quality-matrix.json"))
            return read_status(repo, run_id)
        # A FAIL provider returns to recovery/implementation per the issue spec
        # (not a direct provider fix); surface it and stop short of verify.
        if q.get("status") == "FAIL":
            state = read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("detail", "quality provider reported FAIL")]
            state["current_action"] = "quality_failed"
            state["next_action"] = "inspect_and_recover"
            _write_json(run_dir / "state.json", state)
            _transition(run_dir, state, "blocked",
                        "quality provider reported FAIL -> recovery",
                        receipt=str(run_dir / "quality-matrix.json"))
            return read_status(repo, run_id)
    return verify_run(repo, run_id)


def conduct_run(repo: str, task_path: str, delivery: str = "verified", max_iterations: int = 12, *, retry_budget: int = 3, quality_provider: Optional[str] = None, quality_policy: str = "strict-default", provider_worker: str | None = None) -> Dict[str, Any]:
    """Conduct a run and attach its public Completion-Oracle-derived outcome."""
    status = _conduct_run(repo, task_path, delivery, max_iterations, retry_budget=retry_budget,
                          quality_provider=quality_provider, quality_policy=quality_policy,
                          provider_worker=provider_worker)
    from .run_outcome import persist_run_outcome
    status["outcome"] = persist_run_outcome(status)
    return status


def defer_maintenance_backlog_only(
    repo: str,
    run_id: str,
    *,
    correction_summary: str,
    deferral_reason: str,
    resume_instructions: Sequence[str] | str,
    evidence_status: str = "UNVERIFIED",
) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    if status["state"].get("phase") in {"done", "cancelled"}:
        raise ValueError(f"run already terminal: {status['state'].get('phase')}")
    run_dir = Path(status["run_dir"])
    state = status["state"]
    receipt = _write_maintenance_deferred_receipt(
        run_dir,
        correction_summary=correction_summary,
        deferral_reason=deferral_reason,
        resume_instructions=resume_instructions,
        evidence_status=evidence_status,
    )
    state["maintenance"] = {
        "mode": receipt["mode"],
        "disposition": receipt["disposition"],
        "receipt": str(run_dir / "maintenance-receipt.json"),
        "correction_summary": receipt["correction_summary"],
        "deferral_reason": receipt["deferral_reason"],
        "evidence_status": receipt["evidence_status"],
    }
    completion = _completion_state(run_dir, state.get("completion"))
    completion["ready"] = False
    completion["tag"] = "UNVERIFIED"
    completion["verdict"] = "DELIVERY_PENDING"
    completion["reason_code"] = "maintenance_deferred"
    if (run_dir / "completion-receipt.json").exists():
        persisted = _load_json(run_dir / "completion-receipt.json")
        persisted.update({"ready": False, "verdict": completion["verdict"],
                          "reason_code": completion["reason_code"], "tag": "UNVERIFIED"})
        _write_json(run_dir / "completion-receipt.json", persisted)
    state["completion"] = completion
    state["operator"] = {
        **(state.get("operator") or {}),
        "ready": False,
        "execution_state": "backlog_only",
    }
    state["current_action"] = "maintenance_deferred_to_backlog"
    state["next_action"] = "resume_from_maintenance_receipt"
    state["evidence"] = {
        **(state.get("evidence") or {}),
        "ready": False,
        "status": receipt["evidence_status"],
    }
    _write_json(run_dir / "state.json", state)
    _transition(
        run_dir,
        state,
        "partial",
        "maintenance correction deferred to backlog-only mode",
        receipt=str(run_dir / "maintenance-receipt.json"),
        extra={"mode": receipt["mode"], "disposition": receipt["disposition"]},
    )
    return read_status(repo, run_id)


def _cancel_mapper_background(repo_path: Path, run_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an outstanding deep Mapper job before a run becomes terminal."""
    mapper_state = state.get("mapper") if isinstance(state.get("mapper"), Mapping) else {}
    route = mapper_state.get("execution_route") if isinstance(mapper_state, Mapping) else None
    if not isinstance(route, Mapping):
        context_path = run_dir / "mapper-context.json"
        try:
            context = _load_json(context_path) if context_path.is_file() else {}
        except (OSError, TypeError, ValueError):
            context = {}
        candidate = context.get("execution_route") if isinstance(context, Mapping) else None
        route = candidate if isinstance(candidate, Mapping) else {}
    background = route.get("background") if isinstance(route, Mapping) else None
    if not isinstance(background, Mapping) or background.get("status") != "queued":
        return {"status": "not_active", "reason_code": "mapper_background_not_active"}

    result = _run_cmd(
        ["simplicio-mapper", "background", "cancel", ".", "--json"], repo_path,
    )
    try:
        stdout = json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        stdout = {"raw": result.stdout.strip()}
    receipt = {
        "schema": "simplicio.loop.mapper-background-cancellation/v1",
        "status": "cancelled" if result.returncode == 0 else "blocked",
        "reason_code": "mapper_background_cancelled" if result.returncode == 0 else "mapper_background_cancel_failed",
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": (result.stderr or "").strip(),
        "job_id": background.get("work_id"),
        "pid": background.get("pid"),
        "requested_at": _now(),
    }
    receipt_path = run_dir / "mapper-background-cancel.json"
    _write_json(receipt_path, receipt)
    state.setdefault("mapper", {})["background_cancellation"] = {
        **receipt, "receipt": str(receipt_path),
    }
    state["mapper"]["execution_route"] = {
        **dict(route),
        "background": {**dict(background), "status": receipt["status"],
                        "cancel_receipt": str(receipt_path)},
    }
    return receipt


def change_phase(repo: str, run_id: str, to_phase: str, reason: str) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    state = status["state"]
    if state.get("phase") in {"done", "cancelled"}:
        raise ValueError(f"run already terminal: {state.get('phase')}")
    if to_phase == "awaiting_decision":
        maintenance = state.get("maintenance") or {}
        if maintenance.get("mode") == "maintenance_deferred" or maintenance.get("disposition") == "backlog_only":
            state["maintenance"] = _active_maintenance_state(maintenance)
            state["operator"] = {
                **(state.get("operator") or {}),
                "ready": False,
                "execution_state": "invalidated",
            }
            state["evidence"] = {
                **(state.get("evidence") or {}),
                "ready": False,
                "status": "INVALIDATED",
            }
        state["next_action"] = "mapper_scan_required"
    elif to_phase == "cancelled":
        _cancel_mapper_background(Path(repo).resolve(), run_dir, state)
        state["next_action"] = "none"
    _transition(run_dir, state, to_phase, reason, receipt=str(run_dir / "state.json"))
    return read_status(repo, run_id)


def reconcile_delivery(repo: str, run_id: str, current_state: str, source_kind: str = "local",
                       source_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    manifest = status["manifest"]
    state = status["state"]
    previous_receipt = None
    previous_path = run_dir / "delivery-receipt.json"
    if previous_path.exists():
        try:
            previous_receipt = _load_json(previous_path)
        except (OSError, ValueError, TypeError):
            previous_receipt = None
    execution_route = None
    route_path = run_dir / "execution-route.json"
    if route_path.is_file():
        try:
            candidate = _load_json(route_path)
            if verify_route_hash(candidate):
                execution_route = candidate
        except (OSError, ValueError, TypeError):
            execution_route = None
    delivery_payload = dict(source_payload or {})
    if execution_route:
        delivery_payload.setdefault("execution_route", execution_route)
    receipt = build_delivery_receipt(str(run_dir), manifest.get("delivery_target") or "verified",
                                     current_state=current_state, source_kind=source_kind,
                                     source_payload=delivery_payload)
    if execution_route:
        receipt["execution_route"] = execution_route
        receipt["route_receipt_sha"] = execution_route.get("receipt_sha", "")
    receipt["reconciliation"] = reconcile_delivery_observation(previous_receipt, receipt)
    write_delivery_receipt(str(run_dir), receipt)
    state["delivery"] = {
        "target": receipt["target"],
        "current_state": receipt["current_state"],
        "ready": receipt["ready"],
        "receipt": str(run_dir / "delivery-receipt.json"),
        "source_checked_at": receipt["source_checked_at"],
        "source_kind": source_kind,
        "execution_route": execution_route,
        "route_receipt_sha": receipt.get("route_receipt_sha", ""),
    }
    reconciliation = receipt.get("reconciliation") or {}
    if reconciliation.get("status") == "reopened":
        state["current_action"] = "delivery_reopened"
        state["next_action"] = "requery_source"
        next_phase = "partial"
        state.setdefault("blockers", [])
        failed_gate = next((gate for gate in receipt.get("gates", [])
                            if gate.get("status") == "fail"), {})
        state["blockers"] = [
            "delivery reopened: " + str(failed_gate.get("detail") or
                                         reconciliation.get("reason_code") or
                                         "delivery_target_regressed")
        ]
    elif receipt["ready"]:
        state["current_action"] = "delivery_reconciled"
        state["next_action"] = "completion_oracle"
        next_phase = "delivering" if current_state not in {"verified", "done"} else "validating"
    else:
        state["current_action"] = "delivery_reconciliation_failed"
        state["next_action"] = "collect_missing_delivery_evidence"
        next_phase = "partial"
        state.setdefault("blockers", [])
        fail_gate = next((gate for gate in receipt.get("gates", []) if gate.get("status") == "fail"), None)
        if fail_gate:
            state["blockers"] = [fail_gate.get("detail", "delivery reconciliation failed")]
    _write_json(run_dir / "state.json", state)
    _emit_event(run_dir, state, "delivery_reconciled", receipt=str(run_dir / "delivery-receipt.json"),
                blocker="" if receipt["ready"] else "delivery_reconciliation_failed",
                message="delivery state reconciled", current_state=receipt["current_state"],
                reconciliation=reconciliation, execution_route=execution_route,
                route_receipt_sha=receipt.get("route_receipt_sha", ""))
    if reconciliation.get("status") == "reopened":
        _emit_event(run_dir, state, "rollback", receipt=str(run_dir / "delivery-receipt.json"),
                    blocker=str(reconciliation.get("reason_code") or "delivery_reopened"),
                    message="delivery regression reopened the run")
    if receipt["ready"]:
        completion = _completion_state(run_dir, state.get("completion"))
        _emit_event(run_dir, state, "oracle_verdict", receipt=(
            str(run_dir / "completion-receipt.json")
            if (run_dir / "completion-receipt.json").exists()
            else str(run_dir / "delivery-receipt.json")),
            blocker="" if completion.get("ready") else "oracle_incomplete",
            message=str(completion.get("verdict") or "DELIVERY_PENDING"),
            verdict=str(completion.get("verdict") or "DELIVERY_PENDING"))
    _transition(run_dir, state, next_phase, "delivery state reconciled", receipt=str(run_dir / "delivery-receipt.json"))
    return read_status(repo, run_id)


def apply_human_decision(repo: str, run_id: str, decision_id: str, answer: str,
                         impact: str = "behavior-change") -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    state = status["state"]
    contract_payload = _load_json(_contract_path(run_dir))
    tasks = contract_payload.get("tasks") or []
    if not tasks:
        raise ValueError("task contract collection is empty")
    changed = False
    for task in tasks:
        ledger = task.setdefault("decision_ledger", [])
        for item in ledger:
            if item.get("id") == decision_id:
                item["resolved"] = True
                item["answer"] = answer
                item["resolved_at"] = _now()
                item["resolution_impact"] = impact
                changed = True
        for bucket_name in ("questions", "assumptions", "blockers"):
            for item in task.get(bucket_name) or []:
                if item.get("id") == decision_id:
                    item["resolved"] = True
                    item["answer"] = answer
                    item["resolved_at"] = _now()
                    item["resolution_impact"] = impact
                    changed = True
    if not changed:
        raise ValueError(f"decision id not found: {decision_id}")
    contract_payload["revision"] = int(contract_payload.get("revision", 1)) + 1
    contract_payload["updated_at"] = _now()
    _write_json(_contract_path(run_dir), contract_payload)
    _emit_event(run_dir, state, "handoff", receipt=str(_contract_path(run_dir)),
                task_id=str(tasks[0].get("id") or ""), ac_ids=_task_ac_ids(tasks[0]),
                message="human decision handed off to replanning", decision_id=decision_id,
                execution_route=state.get("execution_route") or {},
                route_receipt_sha=str((state.get("execution_route") or {}).get("receipt_sha") or ""))
    invalidated = []
    for name in ("plan.json", "operator-receipt.json", "evidence-receipt.json", "delivery-receipt.json"):
        path = run_dir / name
        if path.exists():
            path.unlink()
            invalidated.append(name)
    state["phase"] = "awaiting_decision"
    state["updated_at"] = _now()
    state["current_action"] = "human_decision_applied"
    state["next_action"] = "rebuild_plan_from_updated_contract"
    state["operator"] = {"ready": False, "receipt": "", "target": "", "execution_state": "invalidated"}
    state["evidence"] = {"ready": False, "receipt": "", "status": "INVALIDATED"}
    state["delivery"] = {"target": state.get("delivery_target"), "current_state": "planned", "ready": False, "receipt": ""}
    state["completion"] = _default_completion_state()
    state["blockers"] = []
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "awaiting_decision", "human decision applied; dependent artifacts invalidated",
                receipt=str(_contract_path(run_dir)), extra={"decision_id": decision_id, "invalidated": invalidated})
    return read_status(repo, run_id)


def sync_source_state(repo: str, run_id: str, source: str, external_repo: str = "",
                      pr: int | None = None, tag: str = "") -> Dict[str, Any]:
    status = read_status(repo, run_id)
    manifest = status["manifest"]
    target = manifest.get("delivery_target") or "verified"
    if source != "github":
        raise ValueError(f"unsupported source: {source!r}")
    payload = github_delivery_payload(external_repo, pr=pr, tag=tag, target_state=target)
    current_state = infer_github_delivery_state(payload)
    return reconcile_delivery(repo, run_id, current_state, source_kind="github", source_payload=payload)
