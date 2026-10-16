"""Run entry points for the runner: arm_run, conduct and verify (#1818 split of runner).

Functions moved verbatim from `simplicio_loop/runner.py` (#1818).
`runner` re-exports them, so import paths and patch targets on `runner` keep working.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from .delivery import normalize_delivery_target
from .evidence import redact_sensitive_text
from . import dashboard_events as _dashboard_events
from .task_contract import compile_many, validate_contract
from .loop_execution_receipt import LoopExecutionReceiptError
from .openrouter_operator import external_preflight_admissible as _external_preflight_admissible


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

    run_id = _runner._run_id()
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
        "created_at": _runner._now(),
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
        "created_at": _runner._now(),
        "updated_at": _runner._now(),
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
            "requested": _runner._storage_route_requested(),
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
        "ts": _runner._now(),
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
        _runner._ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
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
        _runner._transition(run_root, state, "mapping", "stack and storage routes frozen; mapper required",
                    receipt=str(run_root / "stack-lock.json"))
        primary_goal = _task_goal(tasks[0]) if tasks else raw.strip()
        mapper_payload = _run_with_operator_recovery(
            "simplicio-mapper",
            run_root,
            lambda: _runner._run_mapper(
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
            _runner._transition(run_root, state, "planning", "local context fallback persisted; mapper evidence is UNVERIFIED",
                        receipt=str(run_root / "mapper-context.json"))
        else:
            _emit_event(run_root, state, "mapper_fresh", receipt=str(run_root / "mapper-context.json"),
                        message="mapper scan, inspect, and handoff are fresh")
            _runner._transition(run_root, state, "planning", "mapper scan/inspect/handoff persisted",
                        receipt=str(run_root / "mapper-context.json"))
        plan = _build_plan_with_hints(tasks, mapper_payload, repo_path, raw,
                                      contract_hash=compiled["collection_hash"])
        plan["run_id"] = run_id
        plan["mapper_context_hash"] = hashlib.sha256(
            (run_root / "mapper-context.json").read_bytes()
        ).hexdigest()
        plan_validation = _runner.validate_plan(
            plan, tasks, repo_path,
            contract_hash=compiled["collection_hash"],
            current_state=_runner._repo_fingerprint(repo_path),
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
        evidence = _runner.build_evidence_receipt(str(run_root))
        _write_json(run_root / "evidence-receipt.json", evidence)
        state["evidence"] = {
            "ready": False,
            "receipt": str(run_root / "evidence-receipt.json"),
            "status": evidence.get("status", "UNVERIFIED"),
        }
        delivery_receipt = _runner.build_delivery_receipt(str(run_root), delivery, current_state="implemented")
        _runner.write_delivery_receipt(str(run_root), delivery_receipt)
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
        _runner._transition(run_root, state, "awaiting_decision", "plan derived from task contract + mapper",
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
                evidence = _runner.build_evidence_receipt(str(run_root))
                _write_json(evidence_path, evidence)
                state["evidence"] = {
                    "ready": False,
                    "receipt": str(evidence_path),
                    "status": evidence.get("status", "UNVERIFIED"),
                }
        _write_json(run_root / "state.json", state)
        _runner._transition(run_root, state, "blocked", "mapper integration failed",
                    receipt=str(run_root / "mapper-context.json"), extra={"error": str(exc)})
    return {"manifest": manifest, "state": _load_json(run_root / "state.json"), "run_dir": str(run_root)}


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
    armed = _runner.arm_run(repo, task_path, delivery, max_iterations)
    run_id = armed["manifest"]["run_id"]
    if armed["state"].get("phase") == "blocked":
        return armed
    try:
        # The public ``run`` path is intentionally zero-config: let the operator
        # derive its worker demand from the task set and let the physical admission
        # monitor choose the safe concurrency.  Callers that need a deterministic
        # serial lane can still use the explicit ``batch --serial`` surface.
        batch = _runner.execute_operator_batch(
            repo,
            run_id,
            max_workers=None,
            retry_budget=retry_budget,
            auto_fan_out=None,
            provider_worker=provider_worker,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        status = _runner.read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        state = status["state"]
        if state.get("phase") != "blocked":
            # Defensive fallback: execute_operator_batch's own preflight boundary is
            # expected to have already persisted a blocked diagnostic before raising, but
            # guarantee the run never surfaces as anything other than explicitly blocked.
            _runner._transition(run_dir, state, "blocked",
                        "batch dispatch failed before dispatch", extra={"error": str(exc)})
            status = _runner.read_status(repo, run_id)
        return status
    status = _runner.read_status(repo, run_id)
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
            _runner._transition(
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
        return _runner.read_status(repo, run_id)
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
            state = _runner.read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("reason", "quality provider blocked the run")]
            state["current_action"] = "quality_blocked"
            state["next_action"] = "inspect_and_recover"
            state["evidence"] = {
                "ready": False,
                "receipt": str(run_dir / "quality-matrix.json"),
                "status": "UNVERIFIED",
            }
            _write_json(run_dir / "state.json", state)
            _runner._transition(run_dir, state, "blocked",
                        "quality provider blocked the run (fail-closed)",
                        receipt=str(run_dir / "quality-matrix.json"))
            return _runner.read_status(repo, run_id)
        # A FAIL provider returns to recovery/implementation per the issue spec
        # (not a direct provider fix); surface it and stop short of verify.
        if q.get("status") == "FAIL":
            state = _runner.read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("detail", "quality provider reported FAIL")]
            state["current_action"] = "quality_failed"
            state["next_action"] = "inspect_and_recover"
            _write_json(run_dir / "state.json", state)
            _runner._transition(run_dir, state, "blocked",
                        "quality provider reported FAIL -> recovery",
                        receipt=str(run_dir / "quality-matrix.json"))
            return _runner.read_status(repo, run_id)
    return _runner.verify_run(repo, run_id)


def verify_run(repo: str, run_id: str, *, flow: str = "run") -> Dict[str, Any]:
    """Run the independent watcher and advance a run without a manual tick."""
    status = _runner.read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    state = status["state"]
    if state.get("phase") in {"done", "cancelled"}:
        return status
    watcher = _runner._watcher_script()
    if not watcher.exists():
        state["blockers"] = ["watcher_verify.py is unavailable"]
        state["current_action"] = "watcher_unavailable"
        state["next_action"] = "inspect_and_recover"
        _write_json(run_dir / "state.json", state)
        _runner._transition(run_dir, state, "blocked", "independent watcher is unavailable", receipt=str(run_dir / "state.json"))
        return _runner.read_status(repo, run_id)
    # Parallel lanes each write evidence after their own task; re-measure on the
    # final tree so the watcher compares against the diff it will actually see.
    # This must run BEFORE `_ensure_current_quality_matrix` below: rebuilding
    # the quality matrix runs the task's own lane commands (pytest, coverage,
    # ...), which write byproducts (e.g. `.coverage`) to the tree -- doing
    # that first would make the evidence receipt's diff-coverage check see
    # those byproducts as an "uncovered diff outside operator receipt".
    _write_json(run_dir / "evidence-receipt.json", _runner.build_evidence_receipt(str(run_dir)))
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
    _runner._transition(run_dir, state, "watching", "automatic conduct reached independent verification", receipt=str(run_dir / "operator-receipt.json"))
    env = _subprocess_env()
    env["SIMPLICIO_RUN_DIR"] = str(run_dir)
    env["SIMPLICIO_LOOP_REPO"] = str(repo_path)
    env["SIMPLICIO_LOOP_DIR"] = str(run_dir / "loop")
    result = subprocess.run([sys.executable, str(watcher), "verify"], cwd=str(repo_path), capture_output=True, text=True, timeout=180, env=env)
    output = redact_sensitive_text((result.stdout or "") + (result.stderr or "")).strip()
    _write_json(run_dir / "watcher-receipt.json", {"schema": "simplicio.watcher-invocation/v1", "returncode": result.returncode, "output": output, "receipt": str(run_dir / "loop" / "watcher_state.json"), "checked_at": _runner._now()})
    watcher_path = run_dir / "loop" / "watcher_state.json"
    watcher_state = _load_json(watcher_path) if watcher_path.exists() else {}
    if result.returncode != 0 or watcher_state.get("status") != "MEASURED" or not watcher_state.get("match"):
        state = _runner.read_status(repo, run_id)["state"]
        state["blockers"] = [watcher_state.get("reported") or output or "watcher verification failed"]
        state["current_action"] = "watcher_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {"ready": False, "receipt": str(watcher_path), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _runner._transition(run_dir, state, "blocked", "independent watcher rejected the run", receipt=str(watcher_path))
        return _runner.read_status(repo, run_id)
    state = _runner.read_status(repo, run_id)["state"]
    state["evidence"] = {"ready": True, "receipt": str(watcher_path), "status": "MEASURED"}
    state["current_action"] = "watcher_verified"
    state["next_action"] = "delivery_reconciliation"
    _write_json(run_dir / "state.json", state)
    _runner._transition(run_dir, state, "delivering", "independent watcher measured all acceptance criteria", receipt=str(watcher_path))
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
    delivered = _runner.reconcile_delivery(
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
        state = _runner.read_status(repo, run_id)["state"]
        state["blockers"] = [_qm_verdict.get("reason", "quality matrix incomplete")]
        state["current_action"] = "quality_matrix_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "quality_matrix_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "quality-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _runner._transition(run_dir, state, "blocked", "quality matrix gate rejected the run", receipt=str(run_dir / "quality-matrix.json"))
        return _runner.read_status(repo, run_id)
    _persist_external_completion_response(run_dir)
    _oracle_matrix = _oracle.evaluate_matrix(str(run_dir / "loop"), str(run_dir))
    _write_json(run_dir / "oracle-matrix.json", _oracle_matrix)
    if not _oracle_matrix.get("parity") or not all(a["ready"] for a in _oracle_matrix.get("adapters", [])):
        state = _runner.read_status(repo, run_id)["state"]
        state["blockers"] = ["completion oracle incomplete: " + str(_oracle_matrix.get("signature"))]
        state["current_action"] = "oracle_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "oracle_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "oracle-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _runner._transition(run_dir, state, "blocked", "completion oracle rejected the run", receipt=str(run_dir / "oracle-matrix.json"))
        return _runner.read_status(repo, run_id)
    try:
        _ensure_verified_loop_journal(run_dir)
        publication_args = {
            "repo": repo_path,
            "run_dir": run_dir,
            "manifest": status["manifest"],
        }
        if flow != "run":
            publication_args["flow"] = flow
        loop_execution = _runner.publish_loop_execution_receipt(**publication_args)
        if loop_execution.get("status") != "VERIFIED":
            raise LoopExecutionReceiptError(
                "loop-execution receipt did not reach VERIFIED status"
            )
    except LoopExecutionReceiptError as exc:
        state = _runner.read_status(repo, run_id)["state"]
        state["blockers"] = [f"loop-execution receipt publication failed: {exc}"]
        state["current_action"] = "loop_execution_receipt_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {
            "ready": False,
            "receipt": str(repo_path / ".simplicio-loop" / "loop-execution.json"),
            "status": "UNVERIFIED",
        }
        _write_json(run_dir / "state.json", state)
        _runner._transition(
            run_dir,
            state,
            "blocked",
            "loop-execution receipt could not be published",
            receipt=str(run_dir / "state.json"),
        )
        return _runner.read_status(repo, run_id)
    state = _runner.read_status(repo, run_id)["state"]
    state["loop_execution"] = loop_execution
    state["blockers"] = []
    state["degraded"] = False
    _runner._transition(run_dir, state, "done", "automatic task-to-verify conduct completed", receipt=str(watcher_path))
    return _runner.read_status(repo, run_id)

from .runner_core import (_write_json, _append_jsonl, _default_completion_state, _load_json, STORAGE_ROUTE_RECEIPT, OPERATOR_RECEIPT_SCHEMA, _subprocess_env)  # noqa: E402
from .runner_lifecycle import (_write_scratchpad, _write_watcher_challenge, _emit_event, _run_with_operator_recovery, _maybe_auto_build_planning_receipt, _task_ac_ids, _persist_external_completion_response, _ensure_verified_loop_journal)  # noqa: E402
from .runner_plan import (_build_anchor, _build_plan_with_hints, _candidate_targets, _extract_repo_file_hints)  # noqa: E402
from .runner_taskspec import (_task_goal)  # noqa: E402
from .runner import (RUNNER_SCHEMA, STATE_SCHEMA, _coverage, _default_maintenance_state, _freeze_stack_lock, _freeze_storage_route, _prepare_operator_receipt, _ensure_current_quality_matrix)  # noqa: E402
from . import runner as _runner  # noqa: E402
