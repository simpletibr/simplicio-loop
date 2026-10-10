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
from .runner_core import (
    OPERATOR_RECEIPT_SCHEMA,
    PLAN_REQUIRED,
    _now,
    _load_json,
    _write_json,
    _verify_run_stack_lock,
    STORAGE_ROUTE_RECEIPT,
    _verify_storage_route,
    _run_cmd,
    _git_current_branch,
    _operator_env,
    _operator_timeout,
    _devcli_env,
    _devcli_cmd,
    _execution_profile,
    _hookwall_digest,
    _is_loop_generated_path,
    _repo_fingerprint,
    _repo_state_equivalent,
    _criteria_text,
    _constraints_text,
    _task_goal,
    _task_spec_payload,
    _task_spec_hash,
    _context_handoff_args,
    _is_tool_cache_path,
    _assert_task_dependencies_ready,
    _mapper_journal_enabled,
    read_status,
)
from .runner_lifecycle import _transition, _emit_event, _task_ac_ids
from .runner_plan import (
    _ensure_mapper_operations_store,
    _claim_mapper_operation_attempt,
    _validate_minimal_host_plan_paths,
    _compile_minimal_host_plan,
    _resolve_host_edit_plan,
    _finish_operator_blocked,
    _provider_worker_plan,
    _hookwall_ledger,
    _operator_receipt_hash,
)
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
    status = read_status(repo, run_id)
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
    _ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
    status["state"]["stack_lock"] = {
        **dict(status["state"].get("stack_lock") or {}),
        "ready": True,
        "path": str(run_dir / "stack-lock.json"),
        "route": stack_lock.route,
        "lock_hash": stack_lock.lock_hash,
        "status": "VERIFIED",
        "verified_at": _now(),
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
        "verified_at": _now(),
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
    before = _repo_fingerprint(repo_path)
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
    plan_validation = validate_plan(effective_plan, tasks, repo_path,
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
    _preflight_operator(repo_path, run_dir)
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
    would_call_provider = bool(selected_provider_worker) or _openrouter_operator_enabled()
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
            "started_at": _now(),
            "finished_at": _now(),
            "measured_at": _now(),
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
            "measured_at": _now(),
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
            "measured_at": _now(),
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
    checkpoint["dirty_before"] = _changed_paths(repo_path)
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
    effect_outcome = _execute_operator_effect(
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
    hookwall_verified, hookwall_gate_reason = gate_completion(hookwall_evidence)
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
    after = _repo_fingerprint(repo_path)
    changed = _changed_paths(repo_path)
    rollback = {"attempted": False, "restored": False, "reason": "not_needed"}
    if returncode != 0 and not uncertain:
        rollback = _restore_operator_checkpoint(checkpoint, repo_path, changed)
        if rollback.get("restored"):
            changed = _changed_paths(repo_path)
            after = _repo_fingerprint(repo_path)
    if uncertain:
        execution_state = "uncertain"
        no_change_proof = None
    elif returncode == 0 and not changed:
        execution_state = "no_change"
        no_change_proof = {
            "satisfying_state": "repository already satisfied the AC; no production diff produced",
            "measured_at": _now(),
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
        "started_at": _now(),
        "finished_at": _now(),
        # #288: receipt_verifier.OPERATOR_RECEIPT_SCHEMA requires "measured_at" for its
        # freshness check. This receipt never carried it, so every real (non-mocked)
        # execute_operator() dispatch was permanently INVALID_SCHEMA/MISSING_FIELD in
        # _verify_worker_receipt_pair() -- the merge gate below could never fire for a genuine
        # attempt. Same instant as finished_at; this is a receipt-completeness fix, not a new
        # measurement.
        "measured_at": _now(),
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
    _transition(run_dir, state, "validating" if returncode == 0 else "blocked",
                "dev-cli execution receipt persisted", receipt=str(operator_path),
                extra={"changed_paths": changed})
    if returncode == 0:
        evidence = build_evidence_receipt(str(run_dir))
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
