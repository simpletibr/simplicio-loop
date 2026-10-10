"""One dispatch lane: build the dispatch item, run one attempt and the supervised child-process retry loop (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
)
from . import dashboard_events as _dashboard_events
from .receipt_verifier import (
    EVIDENCE_RECEIPT_SCHEMA as _EVIDENCE_RECEIPT_CONTENT_SCHEMA,
    OPERATOR_RECEIPT_SCHEMA as _OPERATOR_RECEIPT_CONTENT_SCHEMA,
    ReceiptStatus,
    verify_receipt,
)
from .planning_gate import content_hash as _planning_content_hash
from .execution_route import (
    _stable_hash as _execution_route_hash,
    capability_fingerprint,
    normalize_capability_manifest,
    decide_route,
    verify_route_hash,
)
from .runner_core import (
    _classify_devcli_receipt_failure,
    _classify_operator_exception_reason_code,
    _is_deterministic_operator_failure,
    _receipt_max_age_seconds,
    _now,
    _load_json,
    _write_json,
    _auto_merge_enabled,
    _dispatch_merge_pr,
    _mapper_journal_enabled,
    read_status,
)
from .runner_plan import (
    _ensure_mapper_operations_store,
    _claim_mapper_operation_attempt,
)
from .runner_execute import execute_operator

def _operator_dispatch_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize one typed operator dispatch item.

    The adapter deliberately accepts only the real ``execute_operator`` boundary.  In
    particular, it has no command/echo fallback: callers that need a dry run must arm a
    run first and use that run's normal preflight receipts.
    """
    repo = str(item.get("repo") or "").strip()
    run_id = str(item.get("run_id") or "").strip()
    try:
        task_index = int(item.get("task_index"))
    except (TypeError, ValueError) as exc:
        raise ValueError("operator dispatch task_index must be an integer") from exc
    if not repo or not run_id or task_index < 1:
        raise ValueError("operator dispatch items require repo, run_id, and a positive task_index")
    normalized = {
        "repo": str(Path(repo).resolve()),
        "run_id": run_id,
        "task_index": task_index,
        "worker_id": str(item.get("worker_id") or f"operator-{task_index}"),
        "task_id": str(item.get("task_id") or f"task-{run_id}-{task_index}"),
    }
    # An isolation key is intentionally explicit.  Two tasks in one run share state.json,
    # operator-receipt.json, and the working tree and therefore cannot safely overlap until
    # the worktree adapter supplies separate contexts.
    normalized["isolation_key"] = str(item.get("isolation_key") or normalized["repo"])
    normalized["isolation"] = str(item.get("isolation") or "worktree")
    if isinstance(item.get("task_spec"), Mapping):
        normalized["task_spec"] = dict(item["task_spec"])
    if item.get("provider_worker") is not None:
        normalized["provider_worker"] = str(item.get("provider_worker") or "").strip().lower()
    normalized["admission_fence"] = max(1, int(item.get("admission_fence") or 1))
    normalized["authority_attempt"] = max(1, int(item.get("authority_attempt") or 1))
    normalized["expected_base_ref"] = str(item.get("expected_base_ref") or "")
    normalized["expected_base_sha"] = str(item.get("expected_base_sha") or "")
    authority = item.get("authority_receipt")
    if authority is not None:
        if not isinstance(authority, Mapping):
            raise ValueError("authority_receipt must be an object")
        authority = dict(authority)
        supplied = str(authority.pop("receipt_hash", ""))
        if not supplied or supplied != _planning_content_hash(authority):
            raise ValueError("authority_receipt hash mismatch")
        source = authority.get("source")
        targets = authority.get("targets")
        task_spec = normalized.get("task_spec") or {}
        expected_issue = normalized["task_id"].removeprefix("issue-")
        if (authority.get("operator") != "simplicio-dev-cli"
                or not isinstance(source, Mapping)
                or str(source.get("issue") or "") != expected_issue
                or not str(source.get("revision") or "")
                or not str(source.get("planning_receipt") or "")
                or not isinstance(targets, list) or not targets
                or any(not isinstance(target, str) or not target.strip() for target in targets)
                or sorted(targets) != sorted(task_spec.get("files_affected") or [])):
            raise ValueError("authority_receipt binding mismatch")
        authority["receipt_hash"] = supplied
        normalized["authority_receipt"] = authority
    if isinstance(item.get("operator_context"), Mapping):
        normalized["operator_context"] = dict(item["operator_context"])
    if isinstance(item.get("context_pack"), Mapping):
        normalized["context_pack"] = dict(item["context_pack"])
    if item.get("source_repo"):
        normalized["source_repo"] = str(item["source_repo"])
    if item.get("source_run_id"):
        normalized["source_run_id"] = str(item["source_run_id"])
    if item.get("worktree_context"):
        normalized["worktree_context"] = dict(item["worktree_context"])
    if item.get("worktree_error"):
        normalized["worktree_error"] = str(item["worktree_error"])
    return normalized


def _verify_worker_receipt_pair(operator_receipt_path: str, evidence_receipt_path: str) -> Dict[str, str]:
    """Gate `receipt_status` on real content/schema/hash/freshness/provenance (issue #288).

    Previously this reduced to ``Path(receipt).is_file() and Path(evidence_receipt).is_file()``
    -- an empty ``{}`` file passed just as readily as a genuine receipt. Both receipts are now
    parsed and run through ``receipt_verifier.verify_receipt`` against the schema each producer
    (``_prepare_operator_receipt`` / ``evidence.py::build_evidence_receipt``) actually emits.
    Only a fully verified pair returns ``VERIFIED``; every other case names a specific,
    non-existence reason (``STALE``, ``TAMPERED``, ``INVALID_SCHEMA``, ``MISSING_FIELD``, or the
    legacy ``UNVERIFIED`` when a path is simply absent).
    """
    if not operator_receipt_path or not evidence_receipt_path:
        return {"status": "UNVERIFIED", "reason": "operator or evidence receipt path missing"}
    op_path = Path(operator_receipt_path)
    ev_path = Path(evidence_receipt_path)
    if not op_path.is_file() or not ev_path.is_file():
        return {"status": "UNVERIFIED", "reason": "operator or evidence receipt file missing"}
    try:
        operator_payload = json.loads(op_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": ReceiptStatus.INVALID_SCHEMA, "reason": f"operator receipt unreadable: {exc}"}
    try:
        evidence_payload = json.loads(ev_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": ReceiptStatus.INVALID_SCHEMA, "reason": f"evidence receipt unreadable: {exc}"}

    now = time.time()
    operator_verdict = verify_receipt(
        operator_payload, schema=_OPERATOR_RECEIPT_CONTENT_SCHEMA,
        max_age_seconds=_receipt_max_age_seconds(), now=now,
    )
    if not operator_verdict.verified:
        return {"status": operator_verdict.status, "reason": f"operator receipt: {operator_verdict.reason}"}
    evidence_verdict = verify_receipt(
        evidence_payload, schema=_EVIDENCE_RECEIPT_CONTENT_SCHEMA,
        max_age_seconds=_receipt_max_age_seconds(), now=now,
    )
    if not evidence_verdict.verified:
        return {"status": evidence_verdict.status, "reason": f"evidence receipt: {evidence_verdict.reason}"}
    return {
        "status": ReceiptStatus.VERIFIED,
        "reason": "operator and evidence receipts passed content/schema/hash/freshness/provenance checks",
    }


def _fanout_execution_route(item: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Persist one independently verifiable route before any fan-out LLM call."""
    context = item.get("context_pack") if isinstance(item.get("context_pack"), Mapping) else {}
    goal = str(context.get("goal") or item.get("task_id") or "").strip()
    capabilities = normalize_capability_manifest(
        context.get("worker_capabilities") or item.get("worker_capabilities") or ()
    )
    worker_available = bool(capabilities) or os.environ.get(
        "SIMPLICIO_DETERMINISTIC_WORKER", "1"
    ).lower() not in {"0", "false", "no", "off"}
    manifest = {
        "declared": capabilities,
        "deterministic_worker_available": worker_available,
    }
    record = decide_route(
        goal,
        has_deterministic_worker=worker_available,
        is_ambiguous=bool(context.get("ambiguous") or context.get("requires_semantic_review")),
    ).to_dict()
    if os.environ.get("SIMPLICIO_STORAGE_ROUTE", "").strip().lower() == "mapper":
        record.update({
            "mapper_required": True,
            "mapper_mode": "targeted",
            "mapper_reason": "Mapper storage route is mandatory for every dispatched task",
        })
    record.update({
        "run_id": str(item.get("run_id") or ""),
        "task_index": int(item.get("task_index") or 0),
        "task_id": str(item.get("task_id") or ""),
        "evidence_handles": sorted({
            str(value) for value in (
                context.get("mapper_envelope_hash"),
                context.get("context_pack_hash"),
                context.get("context_graph_handle"),
            ) if str(value or "")
        }),
        "causal_ids": [str(item.get("run_id") or ""), str(item.get("task_id") or "")],
        "route_authority": "loop-runner-fanout",
        "capability_manifest": manifest,
        "capability_fingerprint": capability_fingerprint(manifest),
        "token_usage": (
            {"input_tokens": 0, "output_tokens": 0, "reason": "deterministic_worker_no_llm"}
            if record["route"] == "worker" else
            {"input_tokens": None, "output_tokens": None,
             "reason": "route_decision_precedes_provider_invocation"}
        ),
    })
    record["receipt_sha"] = _execution_route_hash({
        key: value for key, value in record.items() if key != "receipt_sha"
    })
    if not verify_route_hash(record):
        raise RuntimeError("fan-out execution-route receipt failed hash verification")
    route_path = run_dir / f"execution-route-{record['task_index']}.json"
    _write_json(route_path, record)
    _dashboard_events.emit_token_usage(run_dir, only=route_path.name)
    return record


def _operator_dispatch_run_dir(item: Mapping[str, Any]) -> Path:
    """Resolve canonical run storage, with isolated storage for synthetic dispatches."""
    try:
        status = read_status(item["repo"], item["run_id"])
    except FileNotFoundError:  # synthetic dispatch: no armed run on disk
        status = {}
    if status.get("run_dir"):
        return Path(status["run_dir"])

    repo_path = Path(item["repo"]).resolve()

    run_scope = hashlib.sha256(str(item["run_id"]).encode("utf-8")).hexdigest()[:16]
    run_dir = repo_path / ".simplicio-loop" / "orchestrator" / "dispatch-routes" / run_scope
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _operator_dispatch_attempt(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Call the production operator and reduce its status to a durable worker record."""
    started = _now()
    context = dict(item.get("worktree_context") or item.get("operator_context") or {})
    common = {
        "schema": "simplicio.operator-worker/v1",
        "worker_id": item["worker_id"],
        "repo": item["repo"],
        "source_repo": str(item.get("source_repo") or item["repo"]),
        "run_id": item["run_id"],
        "task_index": item["task_index"],
        "task_id": str(item.get("task_id") or ""),
        "worktree_context": context,
        "worktree_path": str(context.get("worktree_path") or context.get("path") or item.get("repo") or ""),
        "branch": str(context.get("branch") or item.get("branch") or ""),
        # These are deliberately worker-scoped aliases.  A fan-out consumer must never
        # infer a shared receipt from the coordinator's run-level state; every lane has
        # its own operator and evidence proof (or an explicit UNVERIFIED state).
        "operator_receipt": "",
        "evidence_receipt": "",
        "receipt_status": "UNVERIFIED",
        "authority_receipt": dict(item.get("authority_receipt") or {}),
        "admission_fence": int(item.get("admission_fence") or 1),
        "authority_attempt": int(item.get("authority_attempt") or 1),
        "expected_base_ref": str(item.get("expected_base_ref") or ""),
        "expected_base_sha": str(item.get("expected_base_sha") or ""),
    }
    run_dir = _operator_dispatch_run_dir(item)
    execution_route = _fanout_execution_route(item, run_dir)
    common["execution_route"] = execution_route
    common["route_receipt_sha"] = execution_route["receipt_sha"]
    mapper_operations = None
    mapper_attempt = None
    attempt_obj: Any = None
    if item.get("worktree_error"):
        return {
            **common,
            "status": "failed",
            "phase": "blocked",
            "execution_state": "error",
            "reason_code": "worktree_context_unpersisted",
            "receipt": "",
            "attempt": 0,
            "error": str(item["worktree_error"]),
            "failure_fingerprint": hashlib.sha256(
                str(item["worktree_error"]).encode("utf-8", "replace")
            ).hexdigest()[:16],
            "started_at": started,
            "finished_at": _now(),
        }
    if _mapper_journal_enabled():
        try:
            dispatch_repo_path = Path(str(item.get("repo") or ".")).resolve()
            # An isolated worktree lane relocates ``item["repo"]`` to a freshly
            # allocated, per-task path (see `_ensure_deferred_worktree_context`)
            # that the earlier batch-level pre-pass could not have known about --
            # ensure its Mapper operations store here too, not just the original
            # pre-worktree repo path.
            _ensure_mapper_operations_store(dispatch_repo_path)
            mapper_operations, mapper_attempt = _claim_mapper_operation_attempt(
                dispatch_repo_path,
                run_id=common["run_id"],
                task_index=int(common["task_index"]),
                task_id=common["task_id"],
                worker_id=common["worker_id"],
                targets=list(
                    (item.get("context_pack") or {}).get("allowed_paths") or []
                ),
            )
            mapper_lease = mapper_attempt.lease
            common["mapper_operation"] = {
                "task_id": mapper_lease.task_id,
                "attempt_id": mapper_lease.attempt_id,
                "lease_id": mapper_lease.lease_id,
                "worker_id": mapper_lease.worker_id,
                "fence_token": mapper_lease.fence_token,
            }
            if attempt_obj is None:
                attempt_obj = mapper_attempt
        except Exception as exc:
            return {
                **common,
                "status": "failed",
                "phase": "blocked",
                "execution_state": "error",
                "receipt": "",
                "operator_receipt": "",
                "evidence_receipt": "",
                "receipt_status": "UNVERIFIED",
                "attempt": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "reason_code": "mapper_operation_claim_failed",
                "dead_letter": True,
                "failure_fingerprint": hashlib.sha256(
                    f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
                ).hexdigest()[:16],
                "started_at": started,
                "finished_at": _now(),
            }
    try:
        payload = execute_operator(
            item["repo"], item["run_id"], task_index=item["task_index"],
            guarded_attempt=attempt_obj,
            authority_receipt=item.get("authority_receipt"),
            authority_attempt=int(item.get("authority_attempt") or 1),
            admission_fence=int(item.get("admission_fence") or 1),
            owned_process_registry=item.get("owned_process_registry"),
            owned_task_id=str(common.get("task_id") or ""),
            provider_worker=str(item.get("provider_worker") or "") or None,
            repair_feedback=item.get("repair_feedback"),
        )
        state = payload.get("state") or {}
        operator = state.get("operator") or {}
        execution_state = str(operator.get("execution_state") or "")
        success = execution_state == "applied"
        receipt = str(operator.get("receipt") or "")
        evidence = state.get("evidence") or {}
        evidence_receipt = str(evidence.get("receipt") or "")
        run_dir = str(payload.get("run_dir") or "")
        watcher_receipt = str(Path(run_dir) / "loop" / "watcher_state.json") if run_dir else ""
        failure_fingerprint = ""
        # #NOWASTE: derive the deterministic-vs-transient reason_code from whatever the
        # receipt actually carries (a discrete `_finish_operator_blocked` reason_code, or
        # -- for a dev-cli apply subprocess's own find/replace rejection -- its stdout/
        # stderr text) so the retry loop above can stop after one attempt instead of
        # burning the whole retry budget on a guaranteed repeat.
        reason_code = str(operator.get("reason_code") or "")
        if receipt:
            try:
                receipt_payload = _load_json(Path(receipt))
                failure_fingerprint = str(receipt_payload.get("failure_fingerprint") or "")
                if not success and not reason_code:
                    reason_code = _classify_devcli_receipt_failure(receipt_payload)
            except (OSError, ValueError, TypeError):
                # The worker result remains useful even when a crashed operator did not leave
                # a readable receipt; the scheduler will use the bounded exception path.
                failure_fingerprint = ""
        receipt_verdict = _verify_worker_receipt_pair(receipt, evidence_receipt)
        mapper_completion = None
        mapper_completion_error = ""
        if mapper_operations is not None and mapper_attempt is not None:
            mapper_lease = mapper_attempt.lease
            try:
                mapper_completion = mapper_operations.complete(
                    mapper_lease,
                    status="completed" if success else "failed",
                    receipt={
                        "run_id": common["run_id"],
                        "task_id": common["task_id"],
                        "task_index": common["task_index"],
                        "operator_receipt": receipt,
                        "evidence_receipt": evidence_receipt,
                        "status": "completed" if success else "failed",
                    },
                )
            except Exception as exc:
                mapper_completion_error = f"{type(exc).__name__}: {exc}"
                if success:
                    success = False
                try:
                    mapper_operations.release(mapper_lease)
                except Exception as release_exc:
                    mapper_completion_error += f"; release={type(release_exc).__name__}: {release_exc}"
        merge: Optional[Dict[str, Any]] = None
        if success and receipt_verdict["status"] == ReceiptStatus.VERIFIED and _auto_merge_enabled():
            # #288: once the receipt pair is genuinely VERIFIED, create/poll/merge the real
            # PR and reconcile against the remote before this dispatch attempt is reported
            # as done -- replaces the ad-hoc, hand-run "gh pr create / gh pr merge" pattern
            # this project's own delivery process previously left as prose only.
            merge = _dispatch_merge_pr(item, receipt=receipt, run_id=common["run_id"])
        return {
            **common,
            "status": "succeeded" if success else "failed",
            "phase": str(state.get("phase") or "blocked"),
            "execution_state": execution_state or "unknown",
            "receipt": receipt,
            "operator_receipt": receipt,
            "evidence_receipt": evidence_receipt,
            "watcher_receipt": watcher_receipt if Path(watcher_receipt).exists() else "",
            "receipt_status": receipt_verdict["status"],
            "receipt_verdict_reason": receipt_verdict["reason"],
            "attempt": int(state.get("attempts") or 0),
            "reason_code": reason_code,
            "failure_fingerprint": failure_fingerprint,
            "merge": merge,
            "mapper_operation_completion": mapper_completion,
            "mapper_operation_completion_error": mapper_completion_error,
            "started_at": started,
            "finished_at": _now(),
        }
    except Exception as exc:  # worker failures are receipts, not scheduler crashes
        if mapper_operations is not None and mapper_attempt is not None:
            try:
                mapper_operations.release(mapper_attempt.lease)
            except Exception:
                pass
        return {
            **common,
            "status": "failed",
            "phase": "blocked",
            "execution_state": "error",
            "receipt": "",
            "operator_receipt": "",
            "evidence_receipt": "",
            "receipt_status": "UNVERIFIED",
            "attempt": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "reason_code": _classify_operator_exception_reason_code(exc),
            "failure_fingerprint": hashlib.sha256(
                f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
            ).hexdigest()[:16],
            "started_at": started,
            "finished_at": _now(),
        }


def _run_operator_item_process(item: Mapping[str, Any], retry_budget: int, owned_process_registry: Any = None) -> List[Dict[str, Any]]:
    """Run one complete operator lane in a supervised child process.

    The input is a plain dispatch item and the returned records are compact JSON-like
    values, so the coordinator can persist the existing journal and receipt contracts.
    Queue/worktree release remains coordinator-owned after the child exits.
    """
    attempts: List[Dict[str, Any]] = []
    previous_fingerprint = ""
    for attempt_no in range(1, max(0, int(retry_budget)) + 2):
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
        if record.get("status") == "succeeded":
            break
        if _is_deterministic_operator_failure(record):
            # #NOWASTE: this exact task/plan/repo-state will fail the same way every
            # time -- record it once and dead-letter instead of burning the retry
            # budget on a guaranteed repeat.
            record["retry_skipped_reason"] = "deterministic_failure_no_retry"
            break
        previous_fingerprint = str(record.get("failure_fingerprint") or "")
    final = attempts[-1]
    final["dead_letter"] = final.get("status") != "succeeded"
    final["attempt_count"] = len(attempts)
    final["retry_scope"] = "worker-process"
    final["attempt_history"] = [
        {"dispatch_attempt": int(record.get("dispatch_attempt") or index),
         "status": record.get("status", "UNVERIFIED"),
         "failure_fingerprint": record.get("failure_fingerprint", "")}
        for index, record in enumerate(attempts, start=1)
    ]
    return attempts
