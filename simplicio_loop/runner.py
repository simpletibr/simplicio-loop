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
