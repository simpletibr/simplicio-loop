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
from .runner_core import (_subprocess_env, OPERATOR_RECEIPT_SCHEMA, MAX_PROVIDER_CURRENT_TARGET_CHARS, HOST_EDIT_PLAN_SCHEMAS, PLAN_REQUIRED, DETERMINISTIC_OPERATOR_REASON_CODES, BatchPreflightError, _classify_devcli_receipt_failure, _classify_operator_exception_reason_code, _is_deterministic_operator_failure, _receipt_max_age_seconds, PHASES, MAPPER_MIN_VERSION, MAPPER_REQUIRED_VERBS, DEVCLI_REQUIRED_TOKENS, DEVCLI_MIN_VERSION, DEVCLI_REQUIRED_CAPABILITIES, BATCH_SCHEMA, BATCH_PREFLIGHT_SCHEMA, NATIVE_PRISM_SCHEMA, _now, _rand_token, _load_json, _default_completion_state, _completion_state, _write_json, _verify_run_stack_lock, STORAGE_ROUTE_RECEIPT, _storage_route_requested, _verify_storage_route, _append_jsonl, _run_cmd, _run_repo_path, _git_current_branch, _dispatch_identity_fields, _hookwall_digest, _is_loop_generated_path, _repo_fingerprint, _repo_state_equivalent, _parse_version_tuple, _preflight_override, _resolved_identity, _criteria_text, _constraints_text, _task_goal, _task_spec_payload, _task_spec_hash, _derive_context_handle, _context_handoff_args, _auto_merge_enabled, _dispatch_merge_pr, WAVE_INLINE_MAX_TASKS, _auto_worktree_dispatch, _is_tool_cache_path, _dependency_references, _task_dependency_references, _task_aliases, _assert_task_dependencies_ready, _item_dependencies, _completed_task_aliases, _omit_satisfied_dispatch_dependencies, _ordered_dispatch_items, read_status)
from .runner_mapper_env import (_operator_env, _operator_timeout, _mapper_timeout_seconds, _mapper_supports_command, _mapper_inspection_is_fresh, _mapper_inspection_reports_stale, _degraded_mapper_fallback_enabled, _degraded_mapper_payload, _devcli_env, _devcli_command_path, _devcli_cmd, _execution_profile, _mapper_journal_enabled)
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
from .runner_plan import (_mapper_operations_database, _ensure_mapper_operations_store, _claim_mapper_operation_attempt, _validate_minimal_host_plan_paths, _compile_minimal_host_plan, _resolve_host_edit_plan, _finish_operator_blocked, _hookwall_ledger, _extract_repo_file_hints, _build_plan_with_hints, _fallback_targets, _candidate_targets, _build_anchor, _operator_receipt_hash)
from .runner_plan_providers import (_provider_worker_plan)
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
from .runner_execute import (_EffectRequest, _terminate_owned_process, _execute_operator_effect_unchecked, _execute_operator_effect, _changed_paths, _plan_relevant_changed_paths, _restore_operator_checkpoint, _operator_run_diff_coverage, conclude_run, execute_operator)
from .runner_execute_unleased import (_execute_operator_unleased)
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
from .runner_dispatch import (_dispatch_journal_backend, execute_operator_batch)
from .runner_dispatch_batch import (dispatch_operator_batch)

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


# Moved to runner_entry (#1818). Re-exported here so import paths and patch targets keep working.
# Late imports (#1818): bound after this module's definitions so the runner modules can import each other.
from .runner_entry import (arm_run, _conduct_run, verify_run)  # noqa: E402
