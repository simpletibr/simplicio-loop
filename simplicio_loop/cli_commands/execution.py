"""`resume`, `tick`, `batch`, `wave`, `prism` and `cancel`: dispatching planned tasks.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
import hashlib
import json

from ._base import impl

from .. import next_step
from ..economy_profile import prism_batches
from ..economy_profile import prism_is_eligible
from ..economy_profile import resolve_prism_batch_size
from ..evidence import redact_sensitive_text
from ..execution_adapters import expected_governor_blocked
from ..json_order import stable_first
from ..loop_execution_receipt import SCHEMA as LOOP_EXECUTION_SCHEMA
from ..loop_execution_receipt import publish_loop_execution_for_flow

def resume(repo: str, run_id: str) -> int:
    payload = impl().change_phase(repo, run_id, "awaiting_decision", "resume requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _dispatch_failure_payload(schema: str, repo: str, run_id: str, error: Exception,
                              task_indices: Optional[Sequence[int]] = None) -> dict:
    payload = {
        "schema": schema,
        "status": "blocked",
        "reason_code": "operator_dispatch_failed",
        "repo": str(repo),
        "run_id": str(run_id),
        "task_indices": list(task_indices or []),
        "error_type": type(error).__name__,
        "error": redact_sensitive_text(str(error)),
    }
    payload["receipt_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _dispatch_exit_code(payload: Mapping[str, Any]) -> int:
    """Return non-zero whenever a dispatch receipt is not a verified success."""
    if not payload:
        return 0  # preserve the thin CLI seam used by compatibility callers
    status = str(payload.get("status") or "").lower()
    if status in {"blocked", "held", "failed", "cancelled", "error"}:
        return 2
    if str(payload.get("phase") or "").lower() in {"blocked", "cancelled"}:
        return 2
    if str(payload.get("execution_state") or "").lower() in {"blocked", "uncertain"}:
        return 2
    if str(payload.get("action") or "") in {
        "operator_failed", "operator_batch_blocked", "operator_batch_preflight_blocked",
    }:
        return 2
    if payload.get("failed") or payload.get("blocked") or payload.get("dead_letter") or payload.get("blockers"):
        return 2
    admission = payload.get("capacity") or payload.get("admission")
    if isinstance(admission, Mapping) and admission.get("admitted") is False:
        return 2
    workers = payload.get("workers")
    if isinstance(workers, list) and any(
        not isinstance(worker, Mapping) or worker.get("status") not in {"succeeded", "completed"}
        for worker in workers
    ):
        return 2
    if payload.get("requested_tasks") and isinstance(workers, list) and not workers:
        return 2
    return 0


def _reconcile_prism_wave(task_indices: Sequence[int], result: Mapping[str, Any]) -> dict:
    requested = [int(index) for index in task_indices]
    requested_set = set(requested)
    workers = result.get("workers") if isinstance(result, Mapping) else None
    workers = workers if isinstance(workers, list) else []
    completed = {
        int(index) for index in (result.get("completed_tasks") or [])
        if isinstance(index, (int, str)) and str(index).lstrip("-").isdigit()
    } if isinstance(result, Mapping) else set()
    worker_by_task = {}
    failed = []
    for worker in workers:
        if not isinstance(worker, Mapping):
            failed.append(None)
            continue
        try:
            task_index = int(worker.get("task_index"))
        except (TypeError, ValueError):
            failed.append(None)
            continue
        worker_by_task[task_index] = worker
        if worker.get("status") not in {"succeeded", "completed"}:
            failed.append(task_index)
    missing = sorted(requested_set - set(worker_by_task) - completed)
    if failed:
        reason_code = "wave_worker_failed"
    elif missing:
        reason_code = "wave_receipt_missing"
    elif not workers and not completed:
        reason_code = "wave_receipt_invalid"
    elif isinstance(result, Mapping) and str(result.get("status") or "").lower() not in {"completed", "succeeded", "success"}:
        reason_code = "wave_not_terminal"
    else:
        reason_code = "wave_receipts_reconciled"
    ok = reason_code == "wave_receipts_reconciled"
    return {
        "schema": "simplicio.prism-wave-reconciliation/v1",
        "status": "reconciled" if ok else "held",
        "ok": ok,
        "requested_tasks": requested,
        "missing": missing,
        "failed": sorted(index for index in failed if index is not None),
        "reason_code": reason_code,
    }


def _public_flow_run_dir(repo: str, run_id: str) -> Path:
    """Resolve the run directory without inventing a successful artifact."""
    try:
        status = impl().read_status(repo, run_id)
        candidate = Path(status["run_dir"])
        return candidate
    except (KeyError, OSError, TypeError, ValueError):
        return Path(repo).resolve() / ".simplicio-loop" / "loop-runs" / str(run_id)


def _attach_dispatch(public_payload: Mapping[str, Any], dispatch: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(public_payload)
    payload["dispatch"] = dict(dispatch)
    for key in ("route", "reason_code", "missing_tools", "provider_worker"):
        if key in dispatch and (key not in payload or key == "reason_code"):
            payload[key] = dispatch[key]
    return payload


def _finalize_public_flow(repo: str, run_id: str, flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Return one v1 public result and persist the v2 adapter envelope once."""

    def _done(payload: Mapping[str, Any]) -> dict[str, Any]:
        impl().persist_execution_envelope(
            flow=flow,
            repo=repo,
            run_id=run_id,
            observed={"run_id": run_id, "result": dict(dispatch), **dict(dispatch)},
        )
        return dict(payload)

    raw_status = str(
        dispatch.get("status")
        or dispatch.get("phase")
        or dispatch.get("execution_state")
        or ""
    ).strip().lower()
    nonterminal = {
        "blocked", "partial", "error", "failed", "held", "cancelled", "canceled",
        "unverified", "infrastructure_failure",
    }
    if raw_status in nonterminal or _dispatch_exit_code(dispatch) != 0:
        flow_result = {"status": raw_status or "blocked", "run_id": run_id}
        if isinstance(dispatch.get("state"), Mapping):
            flow_result["state"] = dict(dispatch["state"])
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    try:
        verified_status = impl().verify_run(repo, run_id, flow=flow)
        state = verified_status.get("state") if isinstance(verified_status, Mapping) else {}
        loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
        if (
            isinstance(state, Mapping)
            and state.get("phase") == "done"
            and isinstance(loop_execution, Mapping)
            and loop_execution.get("status") == "VERIFIED"
        ):
            receipt_path = Path(repo).resolve() / ".simplicio-loop" / "loop-execution.json"
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                isinstance(envelope, Mapping)
                and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
                and (envelope.get("result") or {}).get("status") == "VERIFIED"
                and (envelope.get("result") or {}).get("verified") is True
            ):
                result = dict(envelope)
                result["status"] = "VERIFIED"
                result["verified"] = True
                return _done(_attach_dispatch(result, dispatch))
        phase = str((state or {}).get("phase") or "blocked")
        flow_result = {"status": phase, "run_id": run_id}
        if isinstance(state, Mapping):
            flow_result["state"] = dict(state)
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    except Exception as exc:
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result={"status": "blocked", "run_id": run_id},
        )
        diagnostic["reason_code"] = "v1_publication_failed"
        diagnostic["reason"] = f"public flow could not reach a verified v1 receipt: {redact_sensitive_text(str(exc))}"
        return _done(_attach_dispatch(diagnostic, dispatch))


def _public_flow_from_status(status: Mapping[str, Any], flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Project an already-conducted run without invoking publication again."""
    state = status.get("state") if isinstance(status, Mapping) else {}
    loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
    run_id = str(
        (status.get("manifest") or {}).get("run_id")
        or dispatch.get("run_id")
        or ""
    ) if isinstance(status, Mapping) else str(dispatch.get("run_id") or "")
    if (
        isinstance(state, Mapping)
        and state.get("phase") == "done"
        and isinstance(loop_execution, Mapping)
        and loop_execution.get("status") == "VERIFIED"
    ):
        repo = str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")
        receipt_path = Path(repo).resolve() / ".simplicio-loop" / "loop-execution.json"
        try:
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            envelope = {}
        if (
            isinstance(envelope, Mapping)
            and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
            and (envelope.get("result") or {}).get("status") == "VERIFIED"
            and (envelope.get("result") or {}).get("verified") is True
        ):
            result = dict(envelope)
            result["status"] = "VERIFIED"
            result["verified"] = True
            return _attach_dispatch(result, dispatch)
    phase = str((state or {}).get("phase") or "blocked")
    flow_result = {"status": phase, "run_id": run_id}
    if isinstance(state, Mapping):
        flow_result["state"] = dict(state)
    diagnostic = publish_loop_execution_for_flow(
        repo=Path(str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")),
        run_dir=Path(str(status.get("run_dir") or "")) if status.get("run_dir") else Path("."),
        flow=flow,
        flow_result=flow_result,
    )
    return _attach_dispatch(diagnostic, dispatch)


def _persist_prism_wave_receipt(repo: str, run_id: str, payload: dict) -> str:
    try:
        status = impl().read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        if not run_dir.is_dir():
            return ""
        path = run_dir / "prism-wave-dispatch.json"
        payload["receipt_path"] = str(path)
        unsigned = dict(payload)
        unsigned.pop("receipt_hash", None)
        payload["receipt_hash"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return str(path)
    except (KeyError, OSError, TypeError, ValueError):
        return ""


def tick(repo: str, run_id: str, task_index: int, provider_worker: str | None = None) -> int:
    try:
        current = impl().read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.tick-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "governor": governor,
            "run_id": run_id, "task_indices": [task_index],
        }
        public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
        print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)
    try:
        operator_kwargs = {"task_index": task_index}
        if provider_worker is not None:
            operator_kwargs["provider_worker"] = provider_worker
        payload = impl().execute_operator(repo, run_id, **operator_kwargs)
    except Exception as exc:
        payload = _dispatch_failure_payload("simplicio.tick-receipt/v1", repo, run_id, exc, [task_index])
    public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
    print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def batch(repo: str, run_id: str, task_indices: str, max_workers: int, retry_budget: int,
          serial: bool = False, batch_size: Optional[int] = None,
          provider_worker: str | None = None, *, flow: str = "batch") -> int:
    """One task stays direct. Two or more tasks enter the wave; Prism schedules a wave wider than three."""
    indices = None
    if task_indices.strip():
        try:
            indices = [int(value.strip()) for value in task_indices.split(",") if value.strip()]
        except ValueError as exc:
            payload = _dispatch_failure_payload(
                "simplicio.operator-batch-receipt/v1", repo, run_id, exc,
            )
            impl().persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                       observed={"run_id": run_id, "result": payload, "error": str(exc)})
            print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
            raise ValueError("--task-indices must be a comma-separated list of integers") from exc

    if indices is None:
        try:
            status = impl().read_status(repo, run_id)
            contract_path = Path(status["run_dir"]) / "task-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            indices = list(range(1, len(contract.get("tasks") or []) + 1))
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            indices = None

    try:
        current = impl().read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.operator-batch-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "run_id": run_id,
            "task_indices": list(indices or []), "governor": governor,
        }
        impl().persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                   observed={**current, "result": payload, "governor": governor})
        payload = next_step.annotate_blocked(payload, repo=repo, run_id=run_id, flow=flow,
                                             run_dir=_public_flow_run_dir(repo, run_id))
        print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
        return 2

    eligibility = prism_is_eligible(len(indices or []), explicit_serial=serial)
    if not eligibility["eligible"]:
        try:
            batch_kwargs = {
                "max_workers": max_workers or None,
                "retry_budget": retry_budget,
                "auto_fan_out": not serial,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            payload = impl().execute_operator_batch(repo, run_id, indices, **batch_kwargs)
        except Exception as exc:
            payload = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, indices)
        payload["prism"] = {**eligibility, "batch_size": None, "waves": 1}
        public_payload = _finalize_public_flow(repo, run_id, flow, payload)
        public_payload = next_step.annotate_blocked(public_payload, repo=repo, run_id=run_id, flow=flow,
                                                    run_dir=_public_flow_run_dir(repo, run_id))
        print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)

    width = resolve_prism_batch_size(batch_size)
    waves = prism_batches(indices, width)
    worker_limit = min(max_workers or width, width)
    wave_results = []
    all_reconciled = True
    for wave_number, wave in enumerate(waves, start=1):
        try:
            batch_kwargs = {
                "max_workers": worker_limit,
                "retry_budget": retry_budget,
                "auto_fan_out": True,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            result = impl().execute_operator_batch(repo, run_id, wave, **batch_kwargs)
        except Exception as exc:
            result = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, wave)
        reconciliation = _reconcile_prism_wave(wave, result)
        wave_results.append({"wave": wave_number, "task_indices": wave, "result": result,
                             "reconciliation": reconciliation})
        if not reconciliation["ok"]:
            all_reconciled = False
            break

    workers = [worker for wave in wave_results for worker in (wave["result"].get("workers") or [])]
    payload = {
        "schema": "simplicio.prism-wave-dispatch/v1",
        "status": "completed" if all_reconciled and len(wave_results) == len(waves) else "held",
        "prism": {
            **eligibility,
            "batch_size": width,
            "wave_barrier": "reconcile-before-next",
            "waves": len(waves),
            "requested_tasks": indices,
        },
        "waves": wave_results,
        "workers": workers,
    }
    _persist_prism_wave_receipt(repo, run_id, payload)
    public_payload = _finalize_public_flow(repo, run_id, flow, payload)
    public_payload = next_step.annotate_blocked(public_payload, repo=repo, run_id=run_id, flow=flow,
                                                run_dir=_public_flow_run_dir(repo, run_id))
    print(json.dumps(stable_first(public_payload), ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def cancel(repo: str, run_id: str) -> int:
    payload = impl().change_phase(repo, run_id, "cancelled", "cancel requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _configure_batch_parser(parser):
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("run_id", help="run id to dispatch")
    parser.add_argument(
        "--task-indices",
        default="",
        help="comma-separated 1-based task indices (default: every task in the contract)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="worker demand (default/0: automatic; live CPU/RAM/disk admission governs concurrency; positive values set an explicit ceiling)",
    )
    parser.add_argument("--retry-budget", type=int, default=3, help="retries after the first attempt")
    parser.add_argument(
        "--provider-worker", choices=("openrouter",), default=None,
        help="explicitly authorize the external OpenRouter proposal worker",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Prism wave width (default/minimum: 10; no logical upper bound, e.g. 30)",
    )
    parser.add_argument(
        "--serial", action="store_true",
        help="disable the default isolated fan-out and force the shared-run serial lane",
    )


def add_resume(sub):
    p_resume = sub.add_parser("resume", help="resume a non-terminal run")
    p_resume.add_argument("--repo", default=".", help="repository root")
    p_resume.add_argument("run_id", help="run id to resume")


def add_tick(sub):
    p_tick = sub.add_parser("tick", help="execute one planned task through simplicio-dev-cli")
    p_tick.add_argument("--repo", default=".", help="repository root")
    p_tick.add_argument("run_id", help="run id to tick")
    p_tick.add_argument("--task-index", type=int, default=1, help="1-based task index")
    p_tick.add_argument(
        "--provider-worker", choices=("openrouter",), default=None,
        help="explicitly authorize the external OpenRouter proposal worker",
    )


def add_batch(sub):
    p_batch = sub.add_parser("batch", help="continuously dispatch ready tasks through simplicio-dev-cli")
    _configure_batch_parser(p_batch)


def add_wave(sub):
    p_wave = sub.add_parser("wave", help="dispatch a governed wave with reconciliation barriers")
    _configure_batch_parser(p_wave)


def add_prism(sub):
    p_prism = sub.add_parser("prism", help="dispatch work through the governed Prism route")
    _configure_batch_parser(p_prism)


def add_cancel(sub):
    p_cancel = sub.add_parser("cancel", help="cancel a non-terminal run")
    p_cancel.add_argument("--repo", default=".", help="repository root")
    p_cancel.add_argument("run_id", help="run id to cancel")
