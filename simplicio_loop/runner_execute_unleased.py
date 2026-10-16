"""Unleased operator execution (the body that runs one operator effect without a lease) for the runner (#1818 split of runner_execute).

Functions moved verbatim from `simplicio_loop/runner_execute.py` (#1818).
`runner_execute` re-exports them, so import paths and patch targets on `runner_execute` keep working.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from .planning_gate import content_hash as _planning_content_hash, evaluate_mutation_authority, mutation_authority_required
from .execution_route import _stable_hash as _execution_route_hash, capability_fingerprint, normalize_capability_manifest, route_receipt_is_current, decide_route, verify_route_hash


def _execute_operator_unleased(repo: str, run_id: str, task_index: int = 1, *,
                      guarded_attempt: Any = None,
                      authority_receipt: Optional[Mapping[str, Any]] = None,
                      authority_attempt: Optional[int] = None,
                      admission_fence: int = 1,
                      owned_process_registry: Any = None,
                      owned_task_id: str = "",
                      provider_worker: str | None = None,
                      repair_feedback: str | None = None) -> Dict[str, Any]:
    """Execute one planned task through the real dev-cli and persist an immutable receipt.

    `run` intentionally arms and dry-runs only.  This explicit tick is the mutation boundary;
    it cannot run without the mapper/plan/operator preflight artifacts created by `arm_run`.

    ``guarded_attempt`` (a Mapper OperationsStore attempt) supplies the lease and fence the
    Hookwall envelope is sealed with. It is deliberately named apart from this function's own
    ``attempt`` local (the per-task retry counter) so the two can never collide.
    """
    status = _runner_execute.read_status(repo, run_id)
    _raise_if_maintenance_deferred(repo, run_id, status)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    contract = _load_json(run_dir / "task-contract.json")
    tasks = contract.get("tasks") or []
    if task_index < 1 or task_index > len(tasks):
        raise ValueError(f"task index out of range: {task_index}")
    _assert_task_dependencies_ready(run_dir, tasks, task_index, run_id)
    stack_lock = _verify_run_stack_lock(run_dir)
    storage_route = _verify_storage_route(run_dir)
    _runner_execute._ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
    status["state"]["stack_lock"] = {
        **dict(status["state"].get("stack_lock") or {}),
        "ready": True,
        "path": str(run_dir / "stack-lock.json"),
        "route": stack_lock.route,
        "lock_hash": stack_lock.lock_hash,
        "status": "VERIFIED",
        "verified_at": _runner_execute._now(),
    }
    status["state"]["storage_route"] = {
        **dict(status["state"].get("storage_route") or {}),
        "ready": True,
        "path": str(run_dir / STORAGE_ROUTE_RECEIPT),
        "requested": storage_route.get("requested", ""),
        "selected": storage_route.get("selected", ""),
        "generation": storage_route.get("generation", ""),
        "receipt_hash": storage_route.get("receipt_hash", ""),
        "status": "VERIFIED",
        "verified_at": _runner_execute._now(),
    }
    _write_json(run_dir / "state.json", status["state"])
    plan_path = run_dir / "plan.json"
    mapper_path = run_dir / "mapper-context.json"
    operator_path = run_dir / "operator-receipt.json"
    if not plan_path.exists() or not mapper_path.exists() or not operator_path.exists():
        raise RuntimeError("execution requires fresh mapper, plan, and operator preflight receipts")
    plan = _load_json(plan_path)
    planned_step = (plan.get("steps") or [])[task_index - 1] if task_index <= len(plan.get("steps") or []) else {}
    _assert_task_dependencies_ready(run_dir, tasks, task_index, run_id, step=planned_step)
    before = _runner_execute._repo_fingerprint(repo_path)
    current = before
    planned_state = plan.get("repo_state") or {}
    # A shared-run batch intentionally advances the checkout from one dependent
    # task to the next: task 2's dispatch attempt must see the tree task 1 left,
    # not the tree the plan was frozen against at `prepare` time. Comparing
    # `current` against the run's own last *applied* fingerprint (persisted on
    # `state["repo_state_chain"]` right after each successful tick, below) lets
    # this task chain onto its predecessors while still failing closed on any
    # drift this run did not itself produce -- an external edit never matches
    # that chained baseline either. Falls back to the original frozen
    # `plan["repo_state"]` for task 1 (nothing has been applied yet).
    expected_state = dict(status["state"].get("repo_state_chain") or {}) or planned_state
    effective_plan = plan
    if expected_state and expected_state.get("tree_hash") != planned_state.get("tree_hash"):
        effective_plan = {**plan, "repo_state": expected_state}
    plan_validation = _runner_execute.validate_plan(effective_plan, tasks, repo_path,
                                   contract_hash=contract.get("collection_hash", ""),
                                   current_state=current)
    if not plan_validation["valid"]:
        raise RuntimeError("plan validation failed before operator execution: " + ", ".join(plan_validation["errors"]))
    if expected_state and not _repo_state_equivalent(expected_state, current):
        raise RuntimeError("repository changed after planning; re-run mapper before execution")
    task = tasks[task_index - 1]
    authority_path = None
    if authority_receipt is not None:
        authority = dict(authority_receipt)
        supplied = str(authority.pop("receipt_hash", ""))
        targets = list(((plan.get("steps") or [{}])[task_index - 1].get("candidate_targets") or []))
        source = authority.get("source") or {}
        if (not supplied or supplied != _planning_content_hash(authority)
                or authority.get("operator") != "simplicio-dev-cli"
                or sorted(authority.get("targets") or []) != sorted(targets)
                or not str(source.get("revision") or "")
                or not str(source.get("planning_receipt") or "")):
            raise RuntimeError("authority_receipt invalid at mutation boundary")
        authority_path = run_dir / f"mutation-authority-{task_index}.json"
        _write_json(authority_path, {**authority, "receipt_hash": supplied,
                                     "admission_fence": max(1, int(admission_fence))})
    # #694: every production item gets an authoritative route receipt before
    # mutation authority or an execution backend is selected.  The route is a
    # deterministic gate.
    task_text = _task_goal(task)
    worker_capabilities = task.get("worker_capabilities") or task.get("capabilities") or ()
    worker_available = bool(worker_capabilities) or os.environ.get("SIMPLICIO_DETERMINISTIC_WORKER", "1").lower() not in {"0", "false", "no", "off"}
    capability_manifest = {
        "declared": normalize_capability_manifest(worker_capabilities),
        "deterministic_worker_available": worker_available,
    }
    capability_hash = capability_fingerprint(capability_manifest)
    route_path = run_dir / "execution-route.json"
    previous_route = None
    if route_path.exists():
        try:
            candidate = _load_json(route_path)
            if verify_route_hash(candidate):
                previous_route = candidate
        except (OSError, TypeError, ValueError):
            previous_route = None
    route_cache_status = "new"
    route_record = None
    if previous_route and route_receipt_is_current(previous_route, capability_manifest):
        route_record = previous_route
        route_cache_status = "reused"
    else:
        invalidation = {}
        if previous_route:
            route_cache_status = "invalidated"
            invalidation = {
                "status": "invalidated",
                "reason_code": (
                    "capability_manifest_changed"
                    if previous_route.get("capability_fingerprint")
                    else "capability_manifest_missing"
                ),
                "previous_receipt_sha": str(previous_route.get("receipt_sha") or ""),
                "previous_capability_fingerprint": str(previous_route.get("capability_fingerprint") or ""),
            }
        route = decide_route(
            task_text,
            has_deterministic_worker=worker_available,
            is_ambiguous=bool(task.get("ambiguous") or task.get("requires_semantic_review")),
        )
        route_record = route.to_dict()
        route_record.update({
            "run_id": run_id,
            "task_index": task_index,
            "task_id": str(task.get("id") or ""),
            "evidence_handles": sorted({
                str(value) for value in (
                    (plan.get("steps") or [])[task_index - 1].get("mapper_context_hash", ""),
                    (plan.get("steps") or [])[task_index - 1].get("context_pack_hash", ""),
                ) if str(value)
            }),
            "causal_ids": [run_id, str(task.get("id") or task_index)],
            "route_authority": "loop-runner",
            "capability_manifest": capability_manifest,
            "capability_fingerprint": capability_hash,
        })
        if invalidation:
            route_record["invalidation"] = invalidation
        route_record["receipt_sha"] = _execution_route_hash(
            {key: value for key, value in route_record.items() if key != "receipt_sha"}
        )
    if os.environ.get("SIMPLICIO_STORAGE_ROUTE", "").strip().lower() == "mapper":
        route_record = dict(route_record)
        route_record.update({
            "mapper_required": True,
            "mapper_mode": "targeted",
            "mapper_reason": "Mapper storage route is mandatory for every dispatched task",
        })
        route_record["receipt_sha"] = _execution_route_hash(
            {key: value for key, value in route_record.items() if key != "receipt_sha"}
        )
    if not verify_route_hash(route_record):
        raise RuntimeError("execution-route receipt failed deterministic hash verification")
    _write_json(route_path, route_record)
    operator_state = status["state"].setdefault("operator", {})
    operator_state["execution_route"] = route_record
    operator_state["execution_route_cache"] = {
        "status": route_cache_status,
        "capability_fingerprint": capability_hash,
        "previous_receipt_sha": str((previous_route or {}).get("receipt_sha") or ""),
    }
    _write_json(run_dir / "state.json", status["state"])
    attempt = int((status["state"] or {}).get("attempts", 0)) + 1
    # #284: mutation-authority gate, mandatory by default. execute_operator()
    # refuses to run without a valid planning-receipt.json whose mutation_authority
    # token matches THIS run/attempt/task-contract/plan identity -- any drift (stale
    # plan hash, rotated lease/fence, missing/invalid receipt) blocks fail-closed
    # instead of silently proceeding. Opt out only via an explicit falsy
    # SIMPLICIO_REQUIRE_MUTATION_AUTHORITY (see planning_gate.mutation_authority_required());
    # see simplicio_loop/planning_gate.py and scripts/planning_gate.py.
    if mutation_authority_required():
        # GitHub source drift: if the caller re-captured a fresh source snapshot
        # immediately before this tick (`scripts/planning_gate.py capture-source`,
        # written to `source-snapshot-current.json`), compare its hash against the
        # one the receipt/authority was minted with. Absent that file (local/
        # non-GitHub runs, or a caller that hasn't wired re-capture yet), this is a
        # no-op -- identical to previous behavior.
        current_source_hash = ""
        current_snapshot_path = run_dir / "source-snapshot-current.json"
        if current_snapshot_path.exists():
            try:
                current_source_hash = str((_load_json(current_snapshot_path).get("source") or {}).get("snapshot_hash") or "")
            except Exception:
                current_source_hash = ""
        authority_verdict = evaluate_mutation_authority(
            run_dir, run_id=run_id,
            attempt=int(authority_attempt or attempt),
            task_contract_hash=str(contract.get("collection_hash") or _planning_content_hash(contract)),
            plan_hash=_planning_content_hash(plan),
            source_snapshot_hash=current_source_hash,
        )
        if not authority_verdict["ok"]:
            raise RuntimeError(
                "mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}"
            )
    targets = (plan.get("steps") or [])[task_index - 1].get("candidate_targets") or []
    target = targets[0] if targets else status["state"].get("operator", {}).get("target", "")
    if not target:
        raise RuntimeError("plan has no authorized operator target")
    # Issue #135: the decided change is AC-scoped and MUST point at a plan target. Any target
    # expansion beyond authorized_targets routes back to the planner/impact gate before continuing.
    if target not in (targets or []):
        raise RuntimeError(
            "operator target '%s' is outside the plan's authorized_targets %s; "
            "route back to planner/impact gate before continuing" % (target, targets)
        )
    _runner_execute._preflight_operator(repo_path, run_dir)
    task_spec_path = run_dir / "task-spec.json"
    task_spec = _task_spec_payload(task)
    task_spec_hash = _task_spec_hash(task_spec)
    _write_json(task_spec_path, task_spec)
    lease = str(getattr(getattr(guarded_attempt, "lease", None), "lease_id", "") or f"loop-run:{run_id}")
    fence = str(getattr(getattr(guarded_attempt, "lease", None), "fencing_token", "") or "1")
    profile = _execution_profile()
    context_args, context_handoff = _context_handoff_args(
        repo_path,
        run_dir,
        attempt_id=f"{run_id}:attempt:{attempt}",
        lease_id=lease,
        fencing_token=fence,
    )
    operator_mode = "standalone"
    task_input = (
        [_task_goal(task) or str(task.get("id") or "execute task"),
         "--criteria", _criteria_text(task) or "- true state",
         "--constraints", _constraints_text(task) or "- build passes"]
        if operator_mode == "standalone"
        else ["--task-spec", str(task_spec_path)]
    )
    mechanical_plan, mechanical_path, plan_source = _resolve_host_edit_plan(
        run_dir, task_index=task_index,
    )
    provider_path: Optional[Path] = None
    provider_receipt: Optional[Dict[str, Any]] = None
    provider_receipt_paths: List[str] = []
    provider_proposal_attempts = 0
    selected_provider_worker = str(
        provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER") or ""
    ).strip().lower()
    would_call_provider = bool(selected_provider_worker) or _runner_execute._openrouter_operator_enabled()
    if selected_provider_worker:
        provider_plan, provider_receipt = _provider_worker_plan(
            task=task,
            context={
                "mapper_context": _load_json(mapper_path),
                "handoff": context_handoff,
                "plan": plan,
                "task_spec": task_spec,
            },
            run_id=run_id,
            task_index=task_index,
            attempt=attempt,
            root=repo_path,
            allowed_paths=targets,
            run_dir=run_dir,
            provider_worker=selected_provider_worker,
            repair_feedback=repair_feedback,
        )
        provider_path = (
            Path(str(provider_receipt.get("receipt_path")))
            if provider_receipt and provider_receipt.get("receipt_path")
            else None
        )
        provider_receipt_paths = [str(provider_path)] if provider_path else []
        provider_proposal_attempts = 1 if provider_receipt else 0
        if provider_plan is not None:
            mechanical_plan = provider_plan
            plan_source = "provider-worker"
    if mechanical_plan is None and os.environ.get(
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", ""
    ).strip():
        # Hermetic test seam (#1290): SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON substitutes the
        # whole operator effect in `_execute_operator_effect_unchecked()` -- the write_files
        # it applies are fully scripted by the fixture, not derived from a host edit plan --
        # so the separate host-written-plan requirement below is not meaningful on that path.
        # Never applies to a real run: the env var is a test-only fixture, unset in production.
        mechanical_plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": list(targets),
            "operations": [{"op": "fake_exec_seam", "path": target}],
            "validation": [],
        }
        plan_source = "env:SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON"
    if mechanical_plan is None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "execute",
            "tool": "simplicio-dev-cli",
            "run_id": run_id,
            "execution_state": "blocked",
            "status": "blocked",
            "reason_code": PLAN_REQUIRED,
            "attempt": attempt,
            "retry_budget": 3,
            "target": target,
            "authorized_targets": list(targets),
            "target_within_repo": True,
            "goal": _task_goal(task),
            "argv": [],
            "returncode": 2,
            "stdout": {
                "reason_code": PLAN_REQUIRED,
                "required_schema": "simplicio.dev-cli.edit-plan/v1",
            },
            "stderr": "host must write simplicio.dev-cli.edit-plan/v1; loop does not call OpenRouter",
            "timed_out": False,
            "started_at": _runner_execute._now(),
            "finished_at": _runner_execute._now(),
            "measured_at": _runner_execute._now(),
            "source": "loop-plan-gate",
            "context_handoff": context_handoff,
            "provider_config": {
                "route": "openrouter-to-mechanical-edit" if would_call_provider else "host-edit-plan",
                "reason_code": PLAN_REQUIRED,
                "provider_receipt": "",
                "provider_receipts": [],
                "provider_proposal_attempts": 0,
                "mechanical_plan": "",
            },
            "provider_receipt": "",
            "mechanical_plan": "",
            "execution_profile": profile,
            "changed_paths": [],
            "diff_hash": str(before.get("tree_hash") or ""),
            "task_contract_hash": contract.get("collection_hash", ""),
            "plan_hash": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "mapper_pack_hash": plan.get("mapper_pack_hash", ""),
            "repo_state_before": before,
            "repo_state_after": before,
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
        return _finish_operator_blocked(
            repo=repo,
            run_id=run_id,
            run_dir=run_dir,
            status=status,
            receipt=blocked_receipt,
            operator_path=operator_path,
            task_index=task_index,
            reason="plan_required: host must supply simplicio.dev-cli.edit-plan/v1",
        )
    dest = run_dir / f"edit-plan-{task_index}.json"
    try:
        same_file = mechanical_path is not None and dest.resolve() == mechanical_path.resolve()
    except OSError:
        same_file = False
    if not same_file:
        _write_json(dest, mechanical_plan)
        mechanical_path = dest
    # Precise preflight before ever shelling out to dev-cli's compile: a bad
    # path (outside the plan's authorized_targets, or one that does not exist)
    # gets a named, actionable reason instead of the generic
    # PLAN_REQUIRED/plan_compile_failed the subprocess would otherwise report.
    path_issue = _validate_minimal_host_plan_paths(mechanical_plan, repo_path, targets)
    if path_issue is not None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "apply",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "reason_code": path_issue["reason_code"],
            "target": target,
            "stdout": {},
            "stderr": path_issue["message"],
            "measured_at": _runner_execute._now(),
        }
        return _finish_operator_blocked(
            repo=repo, run_id=run_id, run_dir=run_dir, status=status,
            receipt=blocked_receipt, operator_path=operator_path,
            task_index=task_index, reason=path_issue["message"],
        )
    compiled_plan, compile_reason_code, compile_error = _compile_minimal_host_plan(repo_path, mechanical_path)
    if compiled_plan is None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "apply",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "reason_code": compile_reason_code or "plan_compile_failed",
            "target": target,
            "stdout": {},
            "stderr": compile_error,
            "measured_at": _runner_execute._now(),
        }
        return _finish_operator_blocked(
            repo=repo, run_id=run_id, run_dir=run_dir, status=status,
            receipt=blocked_receipt, operator_path=operator_path,
            task_index=task_index, reason=compile_error,
        )
    mechanical_plan = compiled_plan
    verb = "edit" if mechanical_plan.get("schema") == "simplicio.dev-cli.edit-plan/v1" else "mechanical-edit"
    argv = _devcli_cmd(
        repo_path, verb, "--root", str(repo_path),
        "--plan", str(mechanical_path), "--apply", "--json",
    )
    checkpoint = _capture_operator_checkpoint(run_dir, repo_path, targets or [target])
    checkpoint["dirty_before"] = _runner_execute._changed_paths(repo_path)
    # #285 remaining gap: this dispatch has a real guarded lease (when the caller wired
    # one) and a real repo checkout/branch on hand -- surface them on the event so
    # `_sync_github_lifecycle()` projects the actual lease/fencing token and branch onto
    # the CLAIMED comment instead of falling back to a blank/best-effort default.
    _emit_event(run_dir, status["state"], "worker_claimed",
                receipt=str(run_dir / "task-contract.json"),
                task_id=str(task.get("id") or ""),
                ac_ids=_task_ac_ids(task),
                message="operator worker claimed task",
                lease_id=str(getattr(getattr(guarded_attempt, "lease", None), "lease_id", "") or ""),
                fencing_token=str(getattr(getattr(guarded_attempt, "lease", None), "fencing_token", "") or ""),
                branch=_git_current_branch(repo_path))
    if item_context := (status["state"].get("operator") or {}).get("worktree_context"):
        _emit_event(run_dir, status["state"], "worktree_created",
                    receipt=str(item_context.get("lock_receipt") or operator_path),
                    message="isolated worktree context available", worktree=item_context)
    op_env = _devcli_env(repo_path, _operator_env())
    # The external coordinator consumes the credential in this Loop process;
    # deterministic Dev CLI must never inherit or persist it.
    op_env.pop("OPENROUTER_API_KEY", None)
    op_env["SIMPLICIO_ADMISSION_FENCE"] = str(max(1, int(admission_fence)))
    if authority_path is not None:
        op_env["SIMPLICIO_MUTATION_AUTHORITY_RECEIPT"] = str(authority_path)
    provider_config = {
        "model": op_env.get("SIMPLICIO_MODEL", ""),
        "planner": "host",
        "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
        "route": "host-edit-plan",
        "plan_source": plan_source,
        "provider_receipt": str(provider_path) if provider_path else "",
        "provider_receipts": provider_receipt_paths,
        "provider_proposal_attempts": provider_proposal_attempts,
        "mechanical_plan": str(mechanical_path) if mechanical_path else "",
        "provider_usage": dict((provider_receipt or {}).get("usage") or {}),
    }
    effect_request = _build_effect_request(
        repo_path, run_id, task_index, task, attempt, targets, route_record, guarded_attempt,
        storage_route=storage_route.get("selected"),
    )
    effect_outcome = _runner_execute._execute_operator_effect(
        request=effect_request,
        argv=argv,
        env=op_env,
        repo_path=repo_path,
        source_hash=str(before.get("tree_hash") or ""),
        storage_route=storage_route.get("selected"),
        owned_process_registry=owned_process_registry,
        owned_task_id=owned_task_id,
    )
    returncode = effect_outcome["returncode"]
    stdout = effect_outcome["stdout"]
    stderr = effect_outcome["stderr"]
    source = effect_outcome["source"]
    uncertain = bool(effect_outcome.get("uncertain"))
    hookwall_evidence = effect_outcome.get("hookwall_evidence")
    hookwall_verified, hookwall_gate_reason = _runner_execute.gate_completion(hookwall_evidence)
    # A deterministically rejected operator has no successful Hookwall evidence,
    # but it may have an explicit Mapper ``failed`` reconciliation.  Preserve
    # that more precise reason in the durable operator receipt instead of
    # collapsing every non-success into ``hookwall_evidence_missing``.
    hookwall_reason = str(
        effect_outcome.get("hookwall_reason") or hookwall_gate_reason
    )
    devcli_returncode = returncode
    verification_failed = returncode == 0 and not uncertain and _devcli_verification_failed(stdout)
    if verification_failed:
        # #1346: dev-cli exits 0 with ``applied`` even when its own nested
        # verification failed. Treat it as a failed, retryable attempt so the
        # changes roll back and a corrected edit-plan can be re-applied.
        returncode = 1
    after = _runner_execute._repo_fingerprint(repo_path)
    changed = _runner_execute._changed_paths(repo_path)
    rollback = {"attempted": False, "restored": False, "reason": "not_needed"}
    if returncode != 0 and not uncertain:
        rollback = _restore_operator_checkpoint(checkpoint, repo_path, changed)
        if rollback.get("restored"):
            changed = _runner_execute._changed_paths(repo_path)
            after = _runner_execute._repo_fingerprint(repo_path)
    if uncertain:
        execution_state = "uncertain"
        no_change_proof = None
    elif returncode == 0 and not changed:
        execution_state = "no_change"
        no_change_proof = {
            "satisfying_state": "repository already satisfied the AC; no production diff produced",
            "measured_at": _runner_execute._now(),
            "evidence": str(after.get("tree_hash", "")),
        }
    else:
        execution_state = "applied" if returncode == 0 else "blocked"
        no_change_proof = None
    receipt = {
        "schema": OPERATOR_RECEIPT_SCHEMA,
        "mode": "execute",
        "tool": "simplicio-dev-cli",
        "run_id": run_id,
        "execution_state": execution_state,
        "status": execution_state,
        "attempt": attempt,
        "retry_budget": 3,
        "target": target,
        "authorized_targets": targets,
        "target_within_repo": True,
        "goal": _task_goal(task),
        "argv": argv,
        "returncode": returncode,
        "devcli_returncode": devcli_returncode,
        "reason_code": "verification_failed" if verification_failed else "",
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": returncode is None,
        "started_at": _runner_execute._now(),
        "finished_at": _runner_execute._now(),
        # #288: receipt_verifier.OPERATOR_RECEIPT_SCHEMA requires "measured_at" for its
        # freshness check. This receipt never carried it, so every real (non-mocked)
        # execute_operator() dispatch was permanently INVALID_SCHEMA/MISSING_FIELD in
        # _verify_worker_receipt_pair() -- the merge gate below could never fire for a genuine
        # attempt. Same instant as finished_at; this is a receipt-completeness fix, not a new
        # measurement.
        "measured_at": _runner_execute._now(),
        "source": source,
        "context_handoff": context_handoff,
        "provider_config": provider_config,
        "provider_receipt": str(provider_path) if provider_path else "",
        "mechanical_plan": str(mechanical_path) if mechanical_path else "",
        "provider_worker": provider_receipt.get("provider") if provider_receipt else None,
        "provider_model": provider_receipt.get("model") if provider_receipt else None,
        "provider_worker_receipt": str(provider_receipt.get("receipt_path") or "") if provider_receipt else "",
        "provider_usage_status": provider_receipt.get("usage_status", "unknown") if provider_receipt else "unknown",
        "provider_input_tokens": provider_receipt.get("input_tokens") if provider_receipt else None,
        "provider_output_tokens": provider_receipt.get("output_tokens") if provider_receipt else None,
        "provider_cached_tokens": provider_receipt.get("cached_tokens") if provider_receipt else None,
        "provider_reasoning_tokens": provider_receipt.get("reasoning_tokens") if provider_receipt else None,
        "provider_cost": provider_receipt.get("cost") if provider_receipt else None,
        "execution_profile": profile,
        "hookwall_envelope": effect_outcome.get("hookwall_envelope"),
        "hookwall_pre_decision": effect_outcome.get("hookwall_pre_decision"),
        "hookwall_mutation_receipt": effect_outcome.get("hookwall_mutation_receipt"),
        "hookwall_post_decision": effect_outcome.get("hookwall_post_decision"),
        "hookwall_evidence": hookwall_evidence,
        "hookwall_verified": hookwall_verified,
        "hookwall_reason": hookwall_reason,
        "hookwall_reconciliation": effect_outcome.get("hookwall_reconciliation"),
        "hookwall_reconciliation_error": effect_outcome.get("hookwall_reconciliation_error", ""),
        "checkpoint": checkpoint,
        "rollback": rollback,
        "failure_fingerprint": "" if returncode == 0 else _operator_failure_fingerprint(returncode, stderr, stdout),
        "task_contract_hash": contract.get("collection_hash", ""),
        "plan_hash": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "mapper_pack_hash": plan.get("mapper_pack_hash", ""),
        "repo_state_before": before,
        "repo_state_after": after,
        "changed_paths": changed,
        "diff_hash": after.get("tree_hash", ""),
        "no_change_proof": no_change_proof,
        "task_spec_path": str(task_spec_path),
        "task_spec_hash": task_spec_hash,
    }
    receipt["receipt_hash"] = _operator_receipt_hash(receipt)
    _write_json(operator_path, receipt)
    # A run may execute multiple ordered tasks through the direct ``tick`` API.
    # The historical run-level path is intentionally preserved for compatibility,
    # but each task also needs an immutable receipt of its own so a later task
    # cannot overwrite the evidence used to validate the earlier one.
    _write_json(run_dir / f"operator-receipt-{task_index}.json", receipt)
    state = status["state"]
    if rollback.get("restored"):
        _emit_event(run_dir, state, "rollback", receipt=str(operator_path),
                    blocker=str(rollback.get("reason") or "operator execution failed"),
                    message="operator changes rolled back")
    state["operator"] = {
        "ready": returncode == 0 and not uncertain and hookwall_verified,
        "receipt": str(operator_path),
        "target": target,
        "execution_state": receipt["execution_state"],
    }
    state["current_action"] = "operator_executed" if returncode == 0 else "operator_failed"
    state["next_action"] = "watcher_behavioral_verification" if returncode == 0 else "repair_operator_or_plan"
    state["attempts"] = int(state.get("attempts", 0)) + 1
    if returncode == 0 or uncertain:
        # Advance this run's own chained baseline so the next dependent task's
        # plan_repo_state_stale check compares against the tree this task
        # actually left, not the frozen `prepare`-time snapshot. A failed/rolled
        # back attempt must never advance it -- `before`/`after` are identical
        # once `_restore_operator_checkpoint` runs, but skip the write outright
        # to keep the intent explicit.
        #
        # `uncertain` (issue #1328 bug 1) is included deliberately: a client-side
        # timeout does not prove the underlying dev-cli subprocess never wrote to
        # disk (see `_execute_operator_effect_unchecked`'s own comment on this).
        # `_restore_operator_checkpoint` is never invoked for an uncertain outcome
        # (only for a clean `returncode != 0`), so `after` here is always the real,
        # current tree -- whether or not this attempt actually mutated it. Binding
        # the chain to that real tree is what lets a later dependent task's
        # freshness check compare against what is ACTUALLY on disk, instead of
        # permanently misreporting this run's own (possibly-already-applied)
        # attempt as external drift. A genuine external edit between `prepare`
        # and the first dispatch attempt is unaffected: it is caught by the
        # pre-attempt freshness check at the top of this function, before any
        # attempt (and therefore before any chain rebind) ever runs.
        state["repo_state_chain"] = after
    _write_json(run_dir / "state.json", state)
    _runner_execute._transition(run_dir, state, "validating" if returncode == 0 else "blocked",
                "dev-cli execution receipt persisted", receipt=str(operator_path),
                extra={"changed_paths": changed})
    if returncode == 0:
        evidence = _runner_execute.build_evidence_receipt(str(run_dir))
        _write_json(run_dir / "evidence-receipt.json", evidence)
        state = _load_json(run_dir / "state.json")
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "evidence-receipt.json"), "status": evidence.get("status", "UNVERIFIED")}
        _write_json(run_dir / "state.json", state)
        _emit_event(run_dir, state, "operator_receipt", receipt=str(operator_path),
                    message="operator execution receipt persisted")
        _emit_event(run_dir, state, "test_gate", receipt=str(run_dir / "evidence-receipt.json"),
                    blocker="" if evidence.get("status") == "VERIFIED" else "evidence_unverified",
                    message="test and evidence gate evaluated", status=evidence.get("status", "UNVERIFIED"))
    if returncode == 0 and not uncertain and hookwall_verified:
        _write_json(run_dir / f"task-{task_index}-result.json", {
            "schema": "simplicio.task-result/v1",
            "run_id": run_id,
            "task_index": task_index,
            "status": receipt["execution_state"],
            "operator_receipt": str(operator_path),
            "evidence_receipt": str(run_dir / "evidence-receipt.json"),
        })
    return _runner_execute.read_status(repo, run_id)

from .runner_core import (_load_json, _verify_run_stack_lock, _verify_storage_route, _write_json, OPERATOR_RECEIPT_SCHEMA, PLAN_REQUIRED, STORAGE_ROUTE_RECEIPT, _repo_state_equivalent, _git_current_branch)  # noqa: E402
from .runner_deps import (_assert_task_dependencies_ready)  # noqa: E402
from .runner_taskspec import (_task_goal, _task_spec_payload, _task_spec_hash, _context_handoff_args, _criteria_text, _constraints_text)  # noqa: E402
from .runner_mapper_env import (_execution_profile, _devcli_cmd, _devcli_env, _operator_env)  # noqa: E402
from .runner_plan import (_resolve_host_edit_plan, _validate_minimal_host_plan_paths, _compile_minimal_host_plan, _operator_receipt_hash, _finish_operator_blocked)
from .runner_plan_providers import (_provider_worker_plan)
from .runner_lifecycle import (_emit_event, _task_ac_ids)  # noqa: E402
from .runner_execute import (_raise_if_maintenance_deferred, _capture_operator_checkpoint, _build_effect_request, _devcli_verification_failed, _restore_operator_checkpoint, _operator_failure_fingerprint)  # noqa: E402
from . import runner_execute as _runner_execute  # noqa: E402
