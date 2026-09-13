"""Thin public-flow adapters for the canonical loop-execution/v2 envelope.

The execution envelope core is deliberately pure.  This module is the small,
side-effecting boundary that observes existing run state and receipts, projects
them into that core, and writes one envelope for a public flow.  It never calls
a provider and it never treats a missing receipt as success.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .evidence import redact_sensitive_text
from .execution_envelope import PHASES, build_execution_envelope
from .execution_report import SCHEMA as EXECUTION_REPORT_SCHEMA

ENVELOPE_FILENAME = "execution-envelope.json"
ARTIFACT_DIRECTORY = ".simplicio/loop-executions"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_PHASE_STATUSES = {"not_run", "running", "complete", "partial", "blocked", "error"}
_TASK_STATUSES = {"queued", "running", "complete", "partial", "blocked", "error", "cancelled"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]


def _safe_id(value: Any, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    if candidate and _SAFE_ID.fullmatch(candidate) and candidate not in {".", ".."}:
        return candidate
    return fallback


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _state_for_phase(state: Mapping[str, Any], phase: str) -> Mapping[str, Any]:
    if phase == "dev_cli":
        return _mapping(state.get("dev_cli") or state.get("operator"))
    if phase == "loop":
        return _mapping(state.get("loop") or state.get("watcher"))
    return _mapping(state.get(phase))


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _run_dir(repo: Path, run_id: str, observed: Mapping[str, Any]) -> tuple[Path, str]:
    manifest = _mapping(observed.get("manifest"))
    state = _mapping(observed.get("state"))
    raw_id = run_id or str(observed.get("run_id") or manifest.get("run_id") or state.get("run_id") or "")
    fallback = "adapter-" + _digest({"flow": observed.get("flow"), "run_id": raw_id, "observed": observed})
    resolved_id = _safe_id(raw_id, fallback=fallback)

    supplied = observed.get("run_dir")
    candidates = []
    if supplied:
        candidates.append(Path(str(supplied)))
    candidates.append(repo / ".simplicio" / "loop-runs" / resolved_id)
    for candidate in candidates:
        candidate = candidate if candidate.is_absolute() else repo / candidate
        if candidate.is_dir() and not candidate.is_symlink() and _within(repo, candidate):
            return candidate.resolve(), resolved_id
    artifact = repo / ARTIFACT_DIRECTORY / resolved_id
    return artifact, resolved_id


def _relative_ref(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return "adapter://outside-artifact/" + _digest(str(path))


def _pointer(value: Any, *, root: Path, artifact_dir: Path, flow: str, phase: str) -> dict[str, str] | None:
    """Return a secret-free receipt pointer for a persisted or in-memory receipt."""
    if isinstance(value, Mapping) and value:
        return {"kind": "observed-receipt", "ref": f"adapter://{flow}/{phase}/{_digest(value)}"}
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        path = artifact_dir / path
        if not path.exists():
            path = root / value.strip()
    if not path.is_file() or path.is_symlink() or not _within(root, path):
        return None
    payload = _read_json(path)
    if payload is None:
        return None
    return {"kind": "receipt", "ref": _relative_ref(artifact_dir, path)}


def _nested_receipts(value: Any, *, names: set[str], depth: int = 0) -> list[Any]:
    if depth > 5:
        return []
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in names and child:
                found.append(child)
            found.extend(_nested_receipts(child, names=names, depth=depth + 1))
    elif isinstance(value, list):
        for child in value:
            found.extend(_nested_receipts(child, names=names, depth=depth + 1))
    return found


def _phase_receipt_candidates(
    phase: str, *, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any]
) -> list[Any]:
    state_phase = _state_for_phase(state, phase)
    values: list[Any] = [state_phase.get("receipt")]
    values.extend(observed.get(f"{phase}_receipt") for _ in (0,))
    result_names = {
        "mapper": {"mapper_receipt", "receipt"},
        "fast": {"fast_receipt", "ingest_receipt", "plan_receipt", "receipt"},
        "dev_cli": {"dev_cli_receipt", "operator_receipt", "mutation_receipt", "receipt"},
        "loop": {"loop_receipt", "watcher_receipt", "receipt"},
    }[phase]
    values.extend(_nested_receipts(result, names=result_names))
    file_names = {
        "mapper": ("mapper-context.json", "mapper-receipt.json"),
        "fast": ("fast-receipt.json", "fast-ingest-receipt.json", "fast-plan-receipt.json"),
        "dev_cli": ("operator-receipt.json", "dev-cli-receipt.json"),
        "loop": (),
    }[phase]
    values.extend(str(root / name) for name in file_names)
    return [value for value in values if value]


def _phase_evidence(
    phase: str, *, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any], receipt: dict[str, str] | None
) -> list[dict[str, str]]:
    if receipt is not None:
        return [receipt]
    state_phase = _state_for_phase(state, phase)
    if phase == "loop":
        for candidate in (root / "loop" / "watcher_state.json", state_phase.get("receipt"), observed.get("watcher_receipt")):
            pointer = _pointer(candidate, root=root, artifact_dir=artifact_dir, flow=str(observed.get("flow") or "unknown"), phase=phase)
            if pointer is not None:
                return [pointer]
    return [{
        "kind": "phase-observation",
        "ref": f"adapter://{observed.get('flow') or 'unknown'}/{phase}/missing/{_digest({'state': state_phase, 'result': result.get(phase)})}",
        "status": "receipt_missing",
    }]


def _loop_complete(root: Path, state: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    watcher = _read_json(root / "loop" / "watcher_state.json") or _state_for_phase(state, "loop")
    if watcher.get("match") is True and str(watcher.get("status") or "").upper() == "MEASURED":
        return True
    watcher_result = _mapping(result.get("watcher"))
    return watcher_result.get("ok") is True or watcher_result.get("match") is True


def _phase(
    phase: str, *, flow: str, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any], expected: bool
) -> dict[str, Any]:
    if expected:
        status = "blocked" if phase == "mapper" else "not_run"
        return {"status": status, "provider_called": False, "receipt": None,
                "evidence": [{"kind": "governor", "ref": f"adapter://{flow}/governor"}]}

    state_phase = _state_for_phase(state, phase)
    candidates = _phase_receipt_candidates(phase, root=root, artifact_dir=artifact_dir, observed=observed, state=state, result=result)
    receipt = next((pointer for value in candidates if (pointer := _pointer(value, root=root, artifact_dir=artifact_dir, flow=flow, phase=phase))), None)
    evidence = _phase_evidence(phase, root=root, artifact_dir=artifact_dir, observed={**dict(observed), "flow": flow}, state=state, result=result, receipt=receipt)

    explicit = str(state_phase.get("status") or "").strip().lower()
    if explicit not in _PHASE_STATUSES:
        explicit = ""
    if phase == "loop":
        status = "complete" if _loop_complete(root, state, result) else (explicit or "not_run")
        if status == "complete":
            return {"status": status, "provider_called": False, "receipt": None, "evidence": evidence}
        return {"status": status, "provider_called": False, "receipt": None, "evidence": evidence}

    if receipt is not None:
        status = "blocked" if explicit in {"blocked", "error"} else "complete"
    elif explicit in {"blocked", "error", "running", "partial"}:
        status = explicit
    elif state_phase or candidates:
        status = "blocked"
    else:
        status = "not_run"
    return {"status": status, "provider_called": receipt is not None, "receipt": receipt, "evidence": evidence}


def _task_rows(contract: Mapping[str, Any], *, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any], expected: bool, artifact_dir: Path, flow: str) -> list[dict[str, Any]]:
    raw_tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    if not raw_tasks:
        raw_tasks = observed.get("tasks") if isinstance(observed.get("tasks"), list) else []
    ids = [str(_mapping(task).get("task_id") or _mapping(task).get("id") or f"task-{index + 1}") for index, task in enumerate(raw_tasks)]
    aliases = {str(index + 1): task_id for index, task_id in enumerate(ids)}
    aliases.update({task_id: task_id for task_id in ids})
    workers = result.get("workers") if isinstance(result.get("workers"), list) else []
    workers_by_index = {}
    for worker in workers:
        if isinstance(worker, Mapping):
            try:
                workers_by_index[int(worker.get("task_index"))] = worker
            except (TypeError, ValueError):
                continue
    completed = {int(value) for value in (result.get("completed_task_indices") or []) if str(value).lstrip("-").isdigit()}
    failed = {int(value) for value in (result.get("failed_task_indices") or []) if str(value).lstrip("-").isdigit()}
    blocked = {int(value) for value in (result.get("blocked_task_indices") or []) if str(value).lstrip("-").isdigit()}
    result_status = str(result.get("status") or observed.get("status") or "").strip().lower()
    all_result_complete = result_status in {"completed", "succeeded", "success", "complete", "completed"}
    state_complete = str(state.get("phase") or "").lower() == "done" and _mapping(state.get("completion")).get("ready") is True
    rows: list[dict[str, Any]] = []
    for index, raw_task in enumerate(raw_tasks):
        task = _mapping(raw_task)
        task_id = ids[index]
        dependencies = task.get("depends_on") or task.get("dependencies") or []
        if isinstance(dependencies, Mapping):
            dependencies = dependencies.get("items") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not isinstance(dependencies, (list, tuple)):
            dependencies = []
        normalized_dependencies = [aliases[str(value)] for value in dependencies if str(value) in aliases]
        worker = workers_by_index.get(index + 1, {})
        worker_status = str(worker.get("status") or "").lower()
        if expected or (index + 1) in blocked or worker_status in {"blocked", "paused", "cancelled"}:
            status = "blocked" if not expected else "blocked"
        elif (index + 1) in failed or worker_status in {"failed", "error"}:
            status = "error"
        elif (index + 1) in completed or worker_status in {"succeeded", "completed", "success"} or all_result_complete or state_complete:
            status = "complete"
        elif worker_status == "running":
            status = "running"
        else:
            status = "queued"
        evidence: list[dict[str, str]] = []
        for key in ("operator_receipt", "evidence_receipt", "receipt"):
            pointer = _pointer(worker.get(key), root=artifact_dir, artifact_dir=artifact_dir, flow=flow, phase="dev_cli")
            if pointer is not None:
                evidence.append(pointer)
        if not evidence:
            evidence.append({"kind": "task-observation", "ref": f"adapter://{flow}/task/{task_id}/{_digest(task_id)}", "status": status})
        rows.append({"task_id": task_id, "order": index, "depends_on": normalized_dependencies, "status": status, "evidence": evidence})
    if not rows:
        rows.append({"task_id": "task-1", "order": 0, "depends_on": [], "status": "blocked", "evidence": [{"kind": "task-observation", "ref": f"adapter://{flow}/task/missing", "status": "task_contract_missing"}]})
    return rows


def _report(run_id: str, *, root: Path, artifact_dir: Path, observed: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]], status: str) -> dict[str, Any]:
    raw = observed.get("execution_report")
    if not isinstance(raw, Mapping):
        for path in (artifact_dir / "execution-report.json", root / "execution-report.json"):
            raw = _read_json(path)
            if raw is not None:
                break
    raw = _mapping(raw)
    def nonnegative_number(value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value if math.isfinite(float(value)) and value >= 0 else None

    report: dict[str, Any] = {
        "schema": EXECUTION_REPORT_SCHEMA,
        "run_id": run_id,
        "status": "COMPLETE" if status == "complete" else status.upper(),
        "wall_ms": nonnegative_number(raw.get("wall_ms")),
        "tasks": [],
        "consolidated": {},
    }
    for task in tasks:
        report["tasks"].append({
            "task_id": str(task.get("task_id") or ""),
            "outcome": str(task.get("status") or "").upper(),
            "wall_ms": None,
        })
    consolidated = _mapping(raw.get("consolidated"))
    for key in ("tokens_in_sum", "tokens_out_sum", "tokens_total_sum", "ram_mb_peak", "speed_items_per_hour"):
        value = consolidated.get(key)
        report["consolidated"][key] = nonnegative_number(value)
    return report


def expected_governor_blocked(observed: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return an explicit expected governor decision, if one was observed."""
    value = _mapping(observed)
    candidates = [value.get("governor"), value.get("task", {}).get("governor") if isinstance(value.get("task"), Mapping) else None, _mapping(value.get("state")).get("governor"), value.get("capacity_admission"), value.get("admission"), _mapping(value.get("result")).get("capacity_admission")]
    for candidate in candidates:
        candidate = _mapping(candidate)
        decision = str(candidate.get("decision") or "").lower()
        reason = str(candidate.get("reason_code") or "").strip()
        if candidate.get("expected") is True and decision == "blocked":
            return {"decision": "blocked", "expected": True, "reason_code": redact_sensitive_text(reason or "expected_governor_blocked")}
        if candidate.get("admitted") is False and (reason.upper().startswith("PHYSICAL_") or reason.upper().startswith("CAPACITY") or reason.lower().startswith("capacity_")):
            return {"decision": "blocked", "expected": True, "reason_code": redact_sensitive_text(reason or "physical_admission_blocked")}
    if str(value.get("status") or "").lower() == "expected_governor_blocked":
        reason = str(value.get("reason_code") or "expected_governor_blocked")
        return {"decision": "blocked", "expected": True, "reason_code": redact_sensitive_text(reason)}
    return None


def _status(*, tasks: Sequence[Mapping[str, Any]], phases: Mapping[str, Mapping[str, Any]], observed: Mapping[str, Any], expected: bool) -> tuple[str, str]:
    if expected:
        return "expected_governor_blocked", "expected_governor_blocked"
    result = _mapping(observed.get("result"))
    explicit = str(result.get("status") or observed.get("status") or _mapping(observed.get("state")).get("phase") or "").lower()
    if explicit in {"error", "failed", "failure"} or any(task.get("status") == "error" for task in tasks) or any(phase.get("status") == "error" for phase in phases.values()):
        return "error", "execution_error"
    if explicit in {"blocked", "held", "cancelled", "paused"} or any(task.get("status") == "blocked" for task in tasks) or any(phase.get("status") == "blocked" for phase in phases.values()):
        return "blocked", "execution_blocked"
    if all(task.get("status") == "complete" for task in tasks) and all(phases[phase].get("status") == "complete" for phase in PHASES):
        return "complete", "verified_execution"
    return "partial", "execution_incomplete"


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def persist_execution_envelope(*, flow: str, repo: str | Path, run_id: str = "", observed: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Persist exactly one validated v2 envelope for a public flow."""
    supplied = dict(observed or {})
    root = Path(repo).resolve()
    artifact_dir, resolved_run_id = _run_dir(root, run_id, supplied)
    state = _mapping(supplied.get("state"))
    result = _mapping(supplied.get("result") or supplied)
    contract = _mapping(supplied.get("contract"))
    if not contract and artifact_dir.is_dir():
        contract = _read_json(artifact_dir / "task-contract.json") or {}
    expected = expected_governor_blocked({**supplied, "result": result})
    task_rows = _task_rows(contract, observed=supplied, state=state, result=result, expected=expected is not None, artifact_dir=artifact_dir, flow=flow)
    phases = {phase: _phase(phase, flow=flow, root=artifact_dir, artifact_dir=artifact_dir, observed=supplied, state=state, result=result, expected=expected is not None) for phase in PHASES}
    status, reason_code = _status(tasks=task_rows, phases=phases, observed={**supplied, "result": result}, expected=expected is not None)
    evidence: list[Any] = []
    for phase in PHASES:
        evidence.extend(phases[phase].get("evidence") or [])
    if not evidence:
        evidence = [{"kind": "adapter", "ref": f"adapter://{flow}/{resolved_run_id}", "status": status}]
    report = _report(resolved_run_id, root=artifact_dir, artifact_dir=artifact_dir, observed=supplied, tasks=task_rows, status=status)
    completion = {"verified": status == "complete", "oracle": "MEASURED" if status == "complete" else "UNAVAILABLE"}
    envelope = build_execution_envelope(
        run_id=resolved_run_id,
        flow=flow,
        tasks=task_rows,
        phases=phases,
        status=status,
        evidence=evidence,
        execution_report=report,
        completion=completion,
        reason_code=reason_code,
        governor=expected,
    )
    _atomic_write(artifact_dir / ENVELOPE_FILENAME, envelope)
    return envelope


__all__ = ["ARTIFACT_DIRECTORY", "ENVELOPE_FILENAME", "expected_governor_blocked", "persist_execution_envelope"]
