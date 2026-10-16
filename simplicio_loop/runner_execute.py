"""Single operator execution: effect boundary, owned-process supervision, checkpoints and ``execute_operator`` (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
import signal
import subprocess
from threading import Thread
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
)
from .evidence import build_evidence_receipt, redact_sensitive_text
from .plan_contract import validate_plan
from .planning_gate import (
    content_hash as _planning_content_hash,
    evaluate_mutation_authority,
    mutation_authority_required,
)
from .hookwall_gate import (
    HookwallBlocked,
    gate_completion,
    validate_envelope,
    validate_pre_decision,
)
from .store_adapter import StorageRoute
from .execution_route import (
    _stable_hash as _execution_route_hash,
    capability_fingerprint,
    normalize_capability_manifest,
    route_receipt_is_current,
    decide_route,
    verify_route_hash,
)
from .openrouter_operator import enabled as _openrouter_operator_enabled
from .runner_core import (OPERATOR_RECEIPT_SCHEMA, PLAN_REQUIRED, _now, _load_json, _write_json, _verify_run_stack_lock, STORAGE_ROUTE_RECEIPT, _verify_storage_route, _run_cmd, _git_current_branch, _hookwall_digest, _is_loop_generated_path, _repo_fingerprint, _repo_state_equivalent, _criteria_text, _constraints_text, _task_goal, _task_spec_payload, _task_spec_hash, _context_handoff_args, _is_tool_cache_path, _assert_task_dependencies_ready, read_status)
from .runner_mapper_env import (_operator_env, _operator_timeout, _devcli_env, _devcli_cmd, _execution_profile, _mapper_journal_enabled)
from .runner_lifecycle import _transition, _emit_event, _task_ac_ids
from .runner_plan import (_ensure_mapper_operations_store, _claim_mapper_operation_attempt, _validate_minimal_host_plan_paths, _compile_minimal_host_plan, _resolve_host_edit_plan, _finish_operator_blocked, _hookwall_ledger, _operator_receipt_hash)
from .runner_plan_providers import (_provider_worker_plan)
from .runner_preflight import _preflight_operator

@dataclass(frozen=True)
class _EffectRequest:
    """The identity of one mutable operator effect, sealed into its Hookwall envelope."""

    workspace: str
    idempotency_key: str
    write_set: tuple[str, ...]
    lease_id: str
    fencing_token: int | str
    attempt_id: str
    gate_id: str
    transaction_id: str


def _build_effect_request(repo_path: Path, run_id: str, task_index: int,
                          task: Mapping[str, Any], attempt: int,
                          targets: Sequence[str], route_record: Mapping[str, Any],
                          guarded_attempt: Any,
                          storage_route: StorageRoute | str | None = None) -> _EffectRequest:
    lease = getattr(guarded_attempt, "lease", None)
    lease_id = str(getattr(lease, "lease_id", "") or f"loop-run:{run_id}")
    raw_fence = getattr(lease, "fencing_token", 1)
    if _mapper_journal_enabled(storage_route) and str(raw_fence).strip():
        fencing_token: int | str = str(raw_fence)
    else:
        try:
            fencing_token = max(1, int(raw_fence))
        except (TypeError, ValueError):
            fencing_token = 1
    transaction_id = f"{run_id}:{task.get('id') or task_index}:{attempt}"
    return _EffectRequest(
        workspace=str(repo_path),
        idempotency_key=transaction_id,
        write_set=tuple(f"repo:{target}" for target in (targets or ["repo"])),
        lease_id=lease_id,
        fencing_token=fencing_token,
        attempt_id=str(getattr(guarded_attempt, "attempt_id", "") or lease_id),
        gate_id=str(route_record.get("receipt_sha") or "execution-route"),
        transaction_id=transaction_id,
    )


def _parse_effect_stdout(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"raw": redact_sensitive_text(value)}
        return dict(parsed) if isinstance(parsed, dict) else {"raw": redact_sensitive_text(value)}
    return {}


def _deterministic_no_mutation_proof(
    outcome: Mapping[str, Any], *, source_hash: str, repo_path: Path,
) -> Dict[str, Any] | None:
    """Prove a failed operator stopped before mutation, conservatively.

    A non-zero exit code alone is not proof: a process may have written files
    before failing.  Reconciliation is allowed only for the Dev CLI's explicit
    blocked result, with ``applied=false``, no reported files/errors, and an
    unchanged source-tree fingerprint.  Timeouts, runtime uncertainty, and
    ambiguous output remain ``unknown``.
    """
    if outcome.get("uncertain"):
        return None
    returncode = outcome.get("returncode")
    if isinstance(returncode, bool) or not isinstance(returncode, int) or returncode == 0:
        return None
    stdout = outcome.get("stdout")
    if not isinstance(stdout, Mapping):
        return None
    if stdout.get("status") != "blocked" or stdout.get("applied") is not False:
        return None
    blocked = stdout.get("blocked_preconditions")
    if not isinstance(blocked, list) or not blocked:
        return None
    codes: List[str] = []
    for item in blocked:
        if not isinstance(item, Mapping):
            return None
        code = str(item.get("code") or item.get("reason") or "").strip()
        if not code:
            return None
        codes.append(code)
    files = stdout.get("files")
    if files not in (None, []):
        return None
    errors = stdout.get("errors")
    if errors not in (None, []):
        return None

    after = _repo_fingerprint(repo_path)
    if not source_hash or after.get("tree_hash") != source_hash:
        return None
    proof: Dict[str, Any] = {
        "schema": "simplicio.loop.effect-reconciliation-proof/v1",
        "outcome": "failed",
        "reason_code": "deterministic_no_mutation",
        "returncode": returncode,
        "operator_source": str(outcome.get("source") or ""),
        "blocked_codes": sorted(set(codes)),
        "applied": False,
        "files_changed": [],
        "errors": [],
        "before_tree_hash": source_hash,
        "after_tree_hash": str(after.get("tree_hash") or ""),
        "fingerprint_scope": "source_tree_excluding_loop_owned_artifacts",
        "measured_at": _now(),
    }
    proof["proof_hash"] = _hookwall_digest(proof)
    return proof

def _owned_registry_path(registry: Any, task_id: str) -> Path | None:
    if isinstance(registry, (str, Path)) and task_id:
        digest = hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:32]
        return Path(registry) / f"{digest}.json"
    return None


def _owned_process_start_time(pid: int) -> str:
    """Return Linux process start time for safe PID-reuse checks when available."""
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return str(fields[19])
    except (OSError, IndexError, ValueError, TypeError):
        return ""


def _register_owned_process(registry: Any, task_id: str, process: Any) -> None:
    if registry is None or not task_id or getattr(process, "pid", None) is None:
        return
    pid = int(process.pid)
    entry = {"pid": pid, "pgid": pid if os.name == "posix" else None,
             "start_time": _owned_process_start_time(pid), "task_id": str(task_id)}
    path = _owned_registry_path(registry, task_id)
    try:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
        else:
            registry[str(task_id)] = entry
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def _read_owned_process(registry: Any, task_id: str) -> Mapping[str, Any] | None:
    path = _owned_registry_path(registry, task_id)
    try:
        if path is not None:
            if not path.is_file():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, Mapping) else None
        value = registry.get(str(task_id)) if registry is not None else None
        return value if isinstance(value, Mapping) else None
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _remove_owned_process(registry: Any, task_id: str, pid: int) -> None:
    path = _owned_registry_path(registry, task_id)
    try:
        entry = _read_owned_process(registry, task_id)
        if entry is None or int(entry.get("pid", -1)) != int(pid):
            return
        if path is not None:
            path.unlink(missing_ok=True)
        elif registry is not None:
            registry.pop(str(task_id), None)
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def _request_owned_supervisor_cancel(registry: Any, task_id: str, reason: str) -> bool:
    """Ask the owning worker to cancel without signalling an unverified PID."""
    path = _owned_registry_path(registry, task_id)
    try:
        entry = _read_owned_process(registry, task_id)
        if entry is None:
            return False
        payload = dict(entry)
        payload["cancel_requested"] = True
        payload["cancel_reason"] = str(reason)
        if path is not None:
            temporary = path.with_suffix(".cancel.tmp")
            temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
        elif isinstance(registry, dict):
            registry[str(task_id)] = payload
        else:
            return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _terminate_owned_process(registry: Any, task_id: str) -> Dict[str, Any] | None:
    """Terminate only after PID start-time and process-group ownership are proven."""
    entry = _read_owned_process(registry, task_id)
    if entry is None:
        return None
    pid = -1
    try:
        pid = int(entry.get("pid"))
        expected_start = str(entry.get("start_time") or "")
        actual_start = _owned_process_start_time(pid)
        if not expected_start or not actual_start:
            if _request_owned_supervisor_cancel(registry, task_id, "owned_identity_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_identity_unavailable"}
        if expected_start != actual_start:
            _remove_owned_process(registry, task_id, pid)
            return {"cancelled": False, "reason": "owned_pid_reused"}
        if os.name != "posix":
            if _request_owned_supervisor_cancel(registry, task_id, "owned_pgid_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_pgid_unavailable"}
        recorded_pgid = int(entry.get("pgid") or -1)
        if recorded_pgid != pid:
            return {"cancelled": False, "reason": "owned_pgid_mismatch"}
        try:
            actual_pgid = os.getpgid(pid)
        except ProcessLookupError:
            _remove_owned_process(registry, task_id, pid)
            return {"cancelled": False, "reason": "owned_process_already_exited"}
        except OSError:
            if _request_owned_supervisor_cancel(registry, task_id, "owned_pgid_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_pgid_unavailable"}
        if actual_pgid != recorded_pgid:
            return {"cancelled": False, "reason": "owned_pgid_mismatch"}
        os.killpg(recorded_pgid, signal.SIGTERM)
        return {"cancelled": True, "pid": pid, "scope": "owned_process_group"}
    except ProcessLookupError:
        if pid > 0:
            _remove_owned_process(registry, task_id, pid)
        return {"cancelled": False, "reason": "owned_process_already_exited"}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"cancelled": False, "reason": f"owned_process_termination_failed:{type(exc).__name__}"}


def _execute_operator_effect_unchecked(*, argv: List[str],
                             env: Mapping[str, str], repo_path: Path,
                             owned_process_registry: Any = None,
                             owned_task_id: str = "") -> Dict[str, Any]:
    fake = os.environ.get("SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", "").strip()
    if fake:
        payload = json.loads(fake)
        for rel, content in (payload.get("write_files") or {}).items():
            path = repo_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        return {
            "returncode": int(payload.get("returncode", 0)),
            "stdout": payload.get("stdout", {}),
            "stderr": redact_sensitive_text(str(payload.get("stderr", ""))),
            "source": "env_override",
            "uncertain": False,
        }

    try:
        if owned_process_registry is None:
            result = subprocess.run(
                argv, cwd=str(repo_path), capture_output=True, text=True,
                timeout=_operator_timeout("execute"), env=env,
            )
        else:
            process = subprocess.Popen(
                argv, cwd=str(repo_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, stdin=subprocess.DEVNULL, env=env,
                start_new_session=(os.name == "posix"),
            )
            _register_owned_process(owned_process_registry, owned_task_id, process)
            try:
                communication: Dict[str, Any] = {}

                def _communicate() -> None:
                    try:
                        communication["result"] = process.communicate(timeout=_operator_timeout("execute"))
                    except BaseException as exc:
                        communication["error"] = exc

                communication_thread = Thread(target=_communicate, name=f"simplicio-owned-{owned_task_id}", daemon=True)
                communication_thread.start()
                cancel_sent = False
                while communication_thread.is_alive():
                    owned_entry = _read_owned_process(owned_process_registry, owned_task_id)
                    if owned_entry and owned_entry.get("cancel_requested") and not cancel_sent:
                        try:
                            if os.name == "posix":
                                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            else:
                                process.terminate()
                        except ProcessLookupError:
                            pass
                        cancel_sent = True
                    communication_thread.join(0.05)
                if "error" in communication:
                    error = communication["error"]
                    if isinstance(error, subprocess.TimeoutExpired):
                        process.kill()
                        stdout, stderr = process.communicate()
                        raise subprocess.TimeoutExpired(
                            argv, error.timeout, output=stdout, stderr=stderr,
                        ) from error
                    raise error
                stdout, stderr = communication["result"]
            finally:
                _remove_owned_process(owned_process_registry, owned_task_id, process.pid)
            result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        return {
            "returncode": result.returncode,
            "stdout": _parse_effect_stdout((result.stdout or "").strip()),
            "stderr": redact_sensitive_text((result.stderr or "").strip()),
            "source": "live_cli",
            "uncertain": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": {},
            "stderr": f"timed out after {exc.timeout}s",
            "source": "live_cli",
            # A timeout does not prove that the child stopped before writing.
            # Keep the Mapper effect unknown until an explicit reconciliation
            # can establish what happened.
            "uncertain": True,
        }


def _execute_operator_effect(*, request: _EffectRequest, argv: List[str],
                             env: Mapping[str, str], repo_path: Path,
                             source_hash: Optional[str] = None,
                             storage_route: StorageRoute | str | None = None,
                             owned_process_registry: Any = None,
                             owned_task_id: str = "") -> Dict[str, Any]:
    """Run one mutable operator only inside a lineage-bound Hookwall chain."""
    source_hash = source_hash or str(_repo_fingerprint(repo_path).get("tree_hash") or "")
    plan_id = request.gate_id or request.transaction_id or request.idempotency_key
    policy_hash = _hookwall_digest({
        "gate_id": request.gate_id or "",
        "write_set": list(request.write_set),
    })
    envelope = validate_envelope({
        "schema": "simplicio.dispatch-envelope/v1",
        "envelope_id": request.transaction_id or request.idempotency_key,
        "run_id": request.idempotency_key.split(":task-", 1)[0],
        "plan_id": plan_id,
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "workspace": request.workspace,
        "fence": request.fencing_token,
        "attempt_id": request.attempt_id or request.lease_id,
        "effect_set": ["process", "write"],
        "write_set": list(request.write_set),
        "command": list(argv),
    })
    pre_decision = {
        "schema": "simplicio.hookwall-decision/v1",
        "phase": "pre",
        "verdict": "proceed",
        "reason_code": "policy_authorized",
        "envelope_id": envelope["envelope_id"],
        "envelope_hash": envelope["envelope_hash"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "fence": request.fencing_token,
    }
    validate_pre_decision(envelope, pre_decision)
    hookwall_ledger = _hookwall_ledger(repo_path, storage_route)
    reservation = hookwall_ledger.reserve(envelope, pre_decision)
    if reservation["action"] == "REPLAY_VERIFIED":
        return {
            "returncode": 0, "stdout": {}, "stderr": "",
            "source": "hookwall_verified_replay",
            "uncertain": False, "hookwall_envelope": envelope,
            "hookwall_pre_decision": pre_decision,
            "hookwall_evidence": reservation["evidence"],
            "hookwall_reason": "idempotent_replay",
        }

    outcome = _execute_operator_effect_unchecked(
        argv=argv,
        env=env,
        repo_path=repo_path,
        owned_process_registry=owned_process_registry,
        owned_task_id=owned_task_id,
    )
    outcome["hookwall_envelope"] = envelope
    outcome["hookwall_pre_decision"] = pre_decision
    if outcome.get("returncode") != 0 or outcome.get("uncertain"):
        unresolved_reason = "effect_uncertain" if outcome.get("uncertain") else "effect_not_committed"
        hookwall_ledger.mark_unresolved(request.idempotency_key, unresolved_reason)
        if not outcome.get("uncertain"):
            proof = _deterministic_no_mutation_proof(
                outcome,
                source_hash=source_hash,
                repo_path=repo_path,
            )
            reconcile_failed = getattr(hookwall_ledger, "reconcile_failed", None)
            if proof is not None and callable(reconcile_failed):
                try:
                    reconciliation = reconcile_failed(request.idempotency_key, proof)
                except Exception as exc:
                    # Keep the effect unknown if Mapper cannot persist the
                    # explicit transition.  Completion will therefore remain
                    # fail-closed instead of claiming a failed lease safely.
                    outcome["hookwall_reconciliation_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    outcome["hookwall_reconciliation"] = {
                        "proof": proof,
                        "mapper": reconciliation,
                    }
                    outcome["hookwall_evidence"] = None
                    outcome["hookwall_reason"] = "effect_failed_no_mutation"
                    return outcome
            elif proof is not None:
                outcome["hookwall_reconciliation_error"] = (
                    "Hookwall ledger does not expose explicit failed-effect reconciliation"
                )
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = unresolved_reason
        return outcome

    hookwall_ledger.effect_confirmed(
        request.idempotency_key,
        {"returncode": outcome.get("returncode"),
         "stdout": outcome.get("stdout") or {},
         "source": outcome.get("source") or ""},
    )

    mutation_receipt = {
        "schema": "simplicio.mutation-receipt/v1",
        "envelope_id": envelope["envelope_id"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "fence": request.fencing_token,
        "status": "committed",
        "result_hash": _hookwall_digest({
            "returncode": outcome.get("returncode"),
            "stdout": outcome.get("stdout") or {},
            "source": outcome.get("source") or "",
        }),
    }
    mutation_receipt["receipt_hash"] = _hookwall_digest(mutation_receipt)
    post_decision = {
        "schema": "simplicio.hookwall-decision/v1",
        "phase": "post",
        "verdict": "proceed",
        "reason_code": "effect_verified",
        "envelope_id": envelope["envelope_id"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "fence": request.fencing_token,
        "receipt_hash": mutation_receipt["receipt_hash"],
    }
    try:
        evidence = hookwall_ledger.verify_and_commit(
            envelope, pre_decision, mutation_receipt, post_decision
        )
    except HookwallBlocked as exc:
        hookwall_ledger.mark_unresolved(request.idempotency_key, exc.reason_code)
        outcome["returncode"] = None
        outcome["uncertain"] = True
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = exc.reason_code
        return outcome
    verified, reason = gate_completion(evidence)
    if not verified:
        hookwall_ledger.mark_unresolved(request.idempotency_key, reason)
        outcome["returncode"] = None
        outcome["uncertain"] = True
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = reason
        return outcome
    outcome["hookwall_mutation_receipt"] = mutation_receipt
    outcome["hookwall_post_decision"] = post_decision
    outcome["hookwall_evidence"] = evidence
    outcome["hookwall_reason"] = "ok"
    return outcome


def _changed_paths(repo_path: Path) -> List[str]:
    try:
        result = _run_cmd(["git", "diff", "--name-only", "HEAD"], repo_path)
        paths = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        status = _run_cmd(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo_path)
        for line in (status.stdout or "").splitlines():
            if len(line) > 3 and line[3:].strip() not in paths:
                paths.append(line[3:].strip())
        return sorted(set(paths))
    except Exception:
        return []


def _plan_relevant_changed_paths(repo_path: Path) -> List[str]:
    """Return worktree changes relevant to a frozen execution plan.

    The Loop writes its own Mapper, ledger, cache, and run receipts under
    ``.simplicio-loop/`` while a shared-run batch advances from one dependent task to
    the next. Those bookkeeping writes necessarily change the repository
    fingerprint, but they are not source drift and cannot be authorized by a
    task's candidate targets. Keep the strict stale-plan check for every
    production path while excluding only Loop-owned storage from that check.
    """
    return sorted({
        str(path).replace("\\", "/")
        for path in _changed_paths(repo_path)
        if str(path).replace("\\", "/") not in {".simplicio-loop"}
        and not str(path).replace("\\", "/").startswith(".simplicio-loop/")
        and not _is_loop_generated_path(str(path))
        and not _is_tool_cache_path(str(path).replace("\\", "/"))
        and str(path).strip()
    })


def _capture_operator_checkpoint(run_dir: Path, repo_path: Path, targets: List[str]) -> Dict[str, Any]:
    checkpoint_dir = run_dir / "checkpoint"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for target in sorted(set(t for t in targets if t)):
        path = repo_path / target
        exists = path.exists()
        content = path.read_text(encoding="utf-8") if exists else None
        files.append({
            "path": target,
            "exists": exists,
            "content": content,
        })
    return {
        "kind": "file-snapshot/v1",
        "created_at": _now(),
        "safe_targets": sorted(set(t for t in targets if t)),
        "files": files,
    }


def _restore_operator_checkpoint(checkpoint: Dict[str, Any], repo_path: Path, changed_paths: List[str]) -> Dict[str, Any]:
    targets = sorted(set(str(path) for path in (checkpoint.get("safe_targets") or []) if str(path)))
    dirty_before = set(str(path) for path in (checkpoint.get("dirty_before") or []))
    # Only this attempt's own source edits matter: verifier caches (__pycache__,
    # .pytest_cache) and non-target paths already dirty before it are not in scope.
    changed = sorted(set(
        str(path) for path in (changed_paths or [])
        if str(path) and not _is_tool_cache_path(str(path))
        and (str(path) in targets or str(path) not in dirty_before)
    ))
    snapshots = {item["path"]: item for item in (checkpoint.get("files") or []) if isinstance(item, dict) and item.get("path")}
    if not changed:
        for rel in targets:
            snap = snapshots.get(rel)
            if not snap:
                continue
            path = repo_path / rel
            exists_now = path.exists()
            content_now = path.read_text(encoding="utf-8") if exists_now else None
            if bool(snap.get("exists")) != exists_now or (snap.get("exists") and snap.get("content") != content_now):
                changed.append(rel)
    if not changed:
        return {"attempted": False, "restored": False, "reason": "no_changed_paths"}
    if not targets:
        return {"attempted": False, "restored": False, "reason": "checkpoint_targets_missing"}
    if any(path not in targets for path in changed):
        return {"attempted": False, "restored": False, "reason": "changed_paths_outside_checkpoint_scope"}
    for rel in changed:
        snap = snapshots.get(rel)
        if not snap:
            return {"attempted": False, "restored": False, "reason": f"missing_snapshot:{rel}"}
        path = repo_path / rel
        if snap.get("exists"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(snap.get("content") or "", encoding="utf-8")
        elif path.exists():
            path.unlink()
    return {"attempted": True, "restored": True, "reason": "restored_checkpoint"}


def _operator_failure_fingerprint(returncode: int | None, stderr: str, stdout: Any) -> str:
    parts = [f"returncode={returncode}"]
    if stderr:
        parts.append(f"stderr={stderr}")
    if stdout:
        if isinstance(stdout, dict):
            parts.append("stdout=" + json.dumps(stdout, ensure_ascii=False, sort_keys=True))
        else:
            parts.append(f"stdout={stdout}")
    blob = " | ".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _operator_run_diff_coverage(repo_path: Path, run_dir: Path) -> Dict[str, Any]:
    """Issue #135: every production diff path must be covered by an operator receipt.

    The bridge is the ONLY allowed mutation path. Any path `git diff` names that no operator
    receipt covers (i.e. was edited outside the bridge, or by a dev-cli failure that silently
    unlocked manual editing) makes the run non-concludable.
    """
    changed = _changed_paths(repo_path)
    covered: List[str] = []
    receipts: List[Dict[str, Any]] = []
    # Collect every operator receipt in this run (execute + batch lanes).
    for candidate in sorted(run_dir.glob("operator-receipt*.json")):
        try:
            receipts.append(_load_json(candidate))
        except (OSError, ValueError, TypeError):
            continue
    for receipt in receipts:
        status = str(receipt.get("status") or receipt.get("execution_state") or "")
        if status not in ("applied", "no_change"):
            continue
        covered.extend(str(p) for p in (receipt.get("changed_paths") or []) if str(p))
    covered_set = {str(p) for p in covered}
    uncovered = [p for p in changed if p not in covered_set]
    coverage_ok = not uncovered
    return {
        "changed_paths": changed,
        "covered_paths": sorted(covered_set),
        "uncovered_paths": uncovered,
        "coverage_ok": coverage_ok,
        "receipt_count": len(receipts),
    }


def conclude_run(repo: str, run_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Gate run conclusion on full operator-receipt diff coverage (issue #135).

    `force=True` is the explicit human override (the safety policy's human gate) and still
    records the violation rather than silently passing.
    """
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    coverage = _operator_run_diff_coverage(repo_path, run_dir)
    state = status["state"]
    if not coverage["coverage_ok"] and not force:
        raise RuntimeError(
            "cannot conclude run: production diff paths without an operator receipt: "
            + ", ".join(coverage["uncovered_paths"])
        )
    gate = {
        "kind": "operator_run_diff_coverage",
        "coverage_ok": coverage["coverage_ok"],
        "uncovered_paths": coverage["uncovered_paths"],
        "forced": bool(force),
        "checked_at": _now(),
    }
    state.setdefault("gates", []).append(gate)
    state["operator_run_gate"] = gate
    _write_json(run_dir / "state.json", state)
    _transition(
        run_dir, state, state.get("phase") or "done",
        "operator-run diff-coverage gate evaluated",
        receipt=str(run_dir / "state.json"),
        extra={"coverage": coverage},
    )
    return read_status(repo, run_id)


def _devcli_verification_failed(stdout: Any) -> bool:
    """True when dev-cli's JSON reports a failed nested verification (#1346)."""
    payload: Any = stdout
    if isinstance(stdout, str):
        try:
            payload = json.loads(stdout)
        except ValueError:
            return False
    if not isinstance(payload, Mapping):
        return False
    receipt = payload.get("mutation_receipt")
    verification = receipt.get("verification") if isinstance(receipt, Mapping) else None
    if not isinstance(verification, Mapping):
        verification = payload.get("verify")
    return isinstance(verification, Mapping) and str(verification.get("status") or "") in {"failed", "timeout"}


def _raise_if_maintenance_deferred(repo: str, run_id: str,
                                   status: Optional[Mapping[str, Any]] = None) -> None:
    status = status if status is not None else read_status(repo, run_id)
    if (status["state"].get("maintenance") or {}).get("disposition") == "backlog_only":
        raise RuntimeError("maintenance deferred: operator execution is blocked until explicit resume")


def execute_operator(repo: str, run_id: str, task_index: int = 1, *,
                     guarded_attempt: Any = None,
                     authority_receipt: Optional[Mapping[str, Any]] = None,
                     authority_attempt: Optional[int] = None,
                     admission_fence: int = 1,
                     owned_process_registry: Any = None,
                     owned_task_id: str = "",
                     provider_worker: str | None = None,
                     repair_feedback: str | None = None) -> Dict[str, Any]:
    """Execute one task, acquiring a Mapper OperationsStore lease for direct ticks.

    Batch workers already claim a Mapper lease in ``_operator_dispatch_attempt`` and pass
    it as ``guarded_attempt``.  The public ``tick`` command calls this boundary directly,
    so it must acquire the same lease itself when the Mapper route is selected; otherwise
    the Mapper-backed Hookwall correctly rejects the synthetic ``loop-run:<id>`` identity
    with ``STALE_FENCE``.
    """
    if guarded_attempt is not None:
        return _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            guarded_attempt=guarded_attempt,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )

    status = read_status(repo, run_id)
    _raise_if_maintenance_deferred(repo, run_id, status)
    run_dir = Path(status["run_dir"])
    storage_route = _verify_storage_route(run_dir)
    if storage_route.get("selected") != StorageRoute.MAPPER.value:
        return _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            guarded_attempt=None,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )

    contract = _load_json(run_dir / "task-contract.json")
    plan = _load_json(run_dir / "plan.json")
    tasks = list(contract.get("tasks") or [])
    if task_index < 1 or task_index > len(tasks):
        raise ValueError(f"task index out of range: {task_index}")
    step = (plan.get("steps") or [])[task_index - 1]
    targets = [
        str(path) for path in (step.get("candidate_targets") or [])
        if str(path).strip()
    ]
    task = tasks[task_index - 1]
    task_id = str(task.get("id") or f"{run_id}-task-{task_index}")
    worker_id = f"tick-{run_id}-{task_index}"
    # ``planning-receipt.json`` authorizes the armed run, while ``state.attempts``
    # counts every task mutation in that run.  A direct tick for task 2 therefore
    # may have a local execution attempt of 2 but must still validate against the
    # run-level authority attempt minted during arm (normally 1).  Batch dispatch
    # supplies this value explicitly; direct ticks need to recover it here.
    if authority_attempt is None:
        # A missing receipt is judged (fail-closed) by the mutation-authority gate.
        receipt_file = run_dir / "planning-receipt.json"
        planning_receipt = _load_json(receipt_file) if receipt_file.exists() else {}
        authority_attempt = max(1, int(planning_receipt.get("attempt") or 1))
    mapper_operations, mapper_attempt = _claim_mapper_operation_attempt(
        Path(status["manifest"]["repo"]).resolve(),
        run_id=run_id,
        task_index=task_index,
        task_id=task_id,
        worker_id=worker_id,
        targets=targets,
    )
    try:
        result = _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            guarded_attempt=mapper_attempt,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )
    except Exception:
        try:
            mapper_operations.release(mapper_attempt.lease)
        except Exception:
            pass
        raise

    result_state = result.get("state") or {}
    operator_state = result_state.get("operator") or {}
    execution_state = str(operator_state.get("execution_state") or "")
    operator_receipt = str(operator_state.get("receipt") or "")
    evidence_receipt = str((result_state.get("evidence") or {}).get("receipt") or "")
    completed = bool(operator_state.get("ready")) and execution_state in {"applied", "no_change"}
    completion_payload = {
        "run_id": run_id,
        "task_id": task_id,
        "task_index": task_index,
        "operator_receipt": operator_receipt,
        "evidence_receipt": evidence_receipt,
        "status": "completed" if completed else "failed",
    }
    try:
        completion = mapper_operations.complete(
            mapper_attempt.lease,
            status="completed" if completed else "failed",
            receipt=completion_payload,
        )
    except Exception:
        try:
            mapper_operations.release(mapper_attempt.lease)
        except Exception:
            pass
        raise
    completion_path = run_dir / f"mapper-operation-completion-{task_index}.json"
    _write_json(completion_path, {
        "schema": "simplicio.loop.mapper-operation-completion/v1",
        "status": "completed" if completed else "failed",
        "run_id": run_id,
        "task_id": task_id,
        "task_index": task_index,
        "worker_id": worker_id,
        "attempt_id": mapper_attempt.lease.attempt_id,
        "lease_id": mapper_attempt.lease.lease_id,
        "fence_token": mapper_attempt.lease.fence_token,
        "operator": completion_payload,
        "mapper": completion,
    })
    result["mapper_operation_completion"] = str(completion_path)
    return result


# Moved to runner_execute_unleased (#1818). Re-exported here so import paths and patch targets keep working.
from .runner_execute_unleased import (  # noqa: E402,F401
    _execute_operator_unleased,
)
