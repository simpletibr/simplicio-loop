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
import stat
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .evidence import redact_sensitive_text
from .execution_envelope import PHASES, build_execution_envelope
from .execution_report import SCHEMA as EXECUTION_REPORT_SCHEMA
from .receipt_verifier import (
    EVIDENCE_RECEIPT_SCHEMA,
    OPERATOR_RECEIPT_SCHEMA,
    ReceiptStatus,
    verify_receipt,
)

ENVELOPE_FILENAME = "execution-envelope.json"
ARTIFACT_DIRECTORY = ".simplicio-loop/loop-executions"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_PHASE_STATUSES = {"not_run", "running", "complete", "partial", "blocked", "error"}
_TASK_STATUSES = {"queued", "running", "complete", "partial", "blocked", "error", "cancelled"}

_PHASE_RECEIPT_KEYS = {
    "mapper": {"mapper", "mapper_receipt", "mapper_context", "context", "context_receipt"},
    "fast": {"fast", "fast_receipt", "ingest", "ingest_receipt", "plan", "plan_receipt"},
    "dev_cli": {"dev_cli", "dev_cli_receipt", "operator", "operator_receipt", "mutation", "mutation_receipt"},
    "loop": {"loop", "loop_receipt", "watcher", "watcher_receipt", "evidence", "evidence_receipt", "completion", "completion_receipt"},
}
_PHASE_FILE_NAMES = {
    "mapper": ("mapper-context.json", "mapper-receipt.json", "context-receipt.json"),
    "fast": ("plan.json", "fast-receipt.json", "fast-ingest-receipt.json", "fast-plan-receipt.json", "ingest-receipt.json", "plan-receipt.json"),
    "dev_cli": ("operator-receipt.json", "dev-cli-receipt.json", "mutation-receipt.json"),
    "loop": (
        "evidence-receipt.json", "watcher-receipt.json", "independent-watcher-receipt.json",
        "completion-receipt.json", "oracle-matrix.json",
    ),
}
_PHASE_SCHEMAS = {
    "mapper": frozenset({"simplicio.mapper-receipt/v1", "simplicio.mapper-index/v1"}),
    "fast": frozenset({
        "simplicio.loop-fast-receipt/v1", "simplicio.fast-ingest-receipt/v1",
        "simplicio.fast-plan-receipt/v1", "simplicio.fast.ingest/v2",
        "simplicio.fast.understanding/v2", "simplicio.fast.plandag/v2",
        "simplicio.plan/v1",
    }),
    "dev_cli": frozenset({
        "simplicio.operator-receipt/v0", "simplicio.mutation-receipt/v1",
        "simplicio.dev-cli-changeset-receipt/v1", "simplicio.stage-receipt/v1",
    }),
    "loop": frozenset({
        "simplicio.watcher-receipt/v1", "simplicio.independent-watcher-receipt/v1",
        "simplicio.watcher-invocation/v1", "simplicio.evidence-receipt/v1",
        "simplicio.completion-receipt/v1", "simplicio.completion-oracle-matrix/v1",
    }),
}


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
        info = path.lstat()
    except (OSError, ValueError):
        return None
    if path.suffix.lower() != ".json" or not stat.S_ISREG(info.st_mode):
        return None
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
    candidates.append(repo / ".simplicio-loop" / "loop-runs" / resolved_id)
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


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _text_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_content_hash(value: Mapping[str, Any], *, prefix: bool = False) -> bool:
    supplied = value.get("receipt_hash")
    if not _text_value(supplied):
        return False
    unsigned = dict(value)
    unsigned.pop("receipt_hash", None)
    digest = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
    return supplied == (f"sha256:{digest}" if prefix else digest) or supplied == digest


def _valid_fast_hash(value: Mapping[str, Any]) -> bool:
    return _valid_content_hash(value, prefix=True)


def _valid_mapper_context(value: Mapping[str, Any]) -> bool:
    handoff = _mapping(value.get("handoff"))
    stdout = _mapping(handoff.get("stdout"))
    context_pack = _mapping(stdout.get("context_pack"))
    before = _mapping(value.get("repo_state_before"))
    after = _mapping(value.get("repo_state_after"))
    return (
        _text_value(value.get("run_id"))
        and _text_value(value.get("task_contract_hash"))
        and value.get("degraded_local") is not True
        and _text_value(before.get("tree_hash"))
        and _text_value(after.get("tree_hash"))
        and isinstance(value.get("scan"), Mapping)
        and isinstance(value.get("inspect"), Mapping)
        and isinstance(value.get("snapshot"), Mapping)
        and isinstance(value.get("handoff"), Mapping)
        and all(_mapping(value.get(name)).get("returncode") == 0 for name in ("scan", "inspect", "snapshot", "handoff"))
        and _text_value(context_pack.get("pack_hash"))
        and isinstance(context_pack.get("files"), list)
        and bool(context_pack.get("files"))
    )


def _valid_phase_receipt(value: Mapping[str, Any], phase: str) -> bool:
    """Validate the existing typed receipt families used by each phase.

    This deliberately does not accept a generic receipt shape.  The adapter only
    trusts durable files whose producer schema and result identity are known here.
    """
    if not isinstance(value, Mapping) or not value:
        return False
    schema = value.get("schema")
    if phase == "mapper" and not schema and _valid_mapper_context(value):
        return True
    if schema not in _PHASE_SCHEMAS.get(phase, frozenset()):
        return False

    if phase == "mapper":
        if schema == "simplicio.mapper-receipt/v1":
            return (
                value.get("verified") is True
                and _text_value(value.get("repo"))
                and _text_value(value.get("generation"))
                and (_nonempty(value.get("artifact_digest")) or _nonempty(value.get("source_receipt")))
            )
        return (
            value.get("status") in {"updated", "unchanged", "skipped"}
            and isinstance(value.get("paths"), Mapping)
            and any(_text_value(value.get(key)) for key in ("repo", "root", "generation"))
        )

    if phase == "fast":
        if schema == "simplicio.loop-fast-receipt/v1":
            return (
                _text_value(value.get("status"))
                and _text_value(value.get("generation"))
                and (_nonempty(value.get("fast_receipt")) or _text_value(value.get("stage")))
                and _valid_fast_hash(value)
            )
        if schema in {"simplicio.fast-ingest-receipt/v1", "simplicio.fast-plan-receipt/v1"}:
            return (
                _text_value(value.get("repo"))
                and _text_value(value.get("generation"))
                and isinstance(value.get("provenance"), Mapping)
                and _valid_fast_hash(value)
                and (schema != "simplicio.fast-plan-receipt/v1" or isinstance(value.get("nodes"), list))
            )
        if schema == "simplicio.fast.ingest/v2":
            metrics = _mapping(value.get("metrics"))
            return (
                _text_value(value.get("generation") or metrics.get("generation"))
                and _text_value(value.get("snapshot") or metrics.get("snapshot"))
                and (isinstance(value.get("receipt"), Mapping) or isinstance(value.get("result"), Mapping) or isinstance(value.get("metrics"), Mapping))
            )
        if schema == "simplicio.fast.understanding/v2":
            metrics = _mapping(value.get("metrics"))
            return (
                _text_value(value.get("generation") or metrics.get("generation"))
                and isinstance(value.get("context"), list)
                and bool(value.get("context"))
            )
        if schema == "simplicio.fast.plandag/v2":
            metrics = _mapping(value.get("metrics"))
            return (
                _text_value(value.get("generation") or metrics.get("generation"))
                and isinstance(value.get("nodes"), list)
                and bool(value.get("nodes"))
            )
        return (
            _text_value(value.get("task_contract_hash"))
            and isinstance(value.get("steps"), list)
            and isinstance(value.get("repo_state"), Mapping)
            and isinstance(value.get("freshness"), Mapping)
        )

    if phase == "dev_cli":
        if schema == "simplicio.operator-receipt/v0":
            verdict = verify_receipt(value, schema=OPERATOR_RECEIPT_SCHEMA)
            return verdict.status == ReceiptStatus.VERIFIED and value.get("execution_state") in {
                "dry_run", "applied", "committed", "blocked", "error",
            } and _text_value(value.get("run_id"))
        if schema == "simplicio.mutation-receipt/v1":
            required = ("envelope_id", "source_hash", "policy_hash", "idempotency_key", "result_hash", "receipt_hash")
            return (
                all(_text_value(value.get(key)) for key in required)
                and value.get("fence") is not None
                and value.get("status") in {"applied", "committed", "completed", "success", "blocked", "error"}
                and _valid_content_hash(value)
            )
        if schema == "simplicio.dev-cli-changeset-receipt/v1":
            return (
                _text_value(value.get("authority_lease"))
                and value.get("authority_fence") is not None
                and _text_value(value.get("source_revision"))
                and _text_value(value.get("issue"))
                and isinstance(value.get("targets"), list) and bool(value.get("targets"))
                and isinstance(value.get("touched_paths"), list) and bool(value.get("touched_paths"))
                and isinstance(value.get("first_edit_ms"), (int, float))
                and not isinstance(value.get("first_edit_ms"), bool)
                and value.get("first_edit_ms") >= 0
                and _valid_content_hash(value)
            )
        return all(_text_value(value.get(key)) for key in ("receipt_id", "agent_instance_id", "stage_id", "role_id", "verdict"))

    if schema in {"simplicio.evidence-receipt/v1"}:
        verdict = verify_receipt(value, schema=EVIDENCE_RECEIPT_SCHEMA)
        summary = _mapping(value.get("summary"))
        criteria = value.get("criteria")
        return (
            verdict.status == ReceiptStatus.VERIFIED
            and value.get("status") == "VERIFIED"
            and isinstance(value.get("summary"), Mapping)
            and isinstance(criteria, list)
            and all(isinstance(item, Mapping) for item in criteria)
            and summary.get("criteria_verified") is not None
        )
    if schema == "simplicio.watcher-receipt/v1":
        return (
            value.get("status") == "MEASURED"
            and value.get("match") is True
            and _text_value(value.get("checked_at"))
            and _text_value(value.get("run_id"))
            and _text_value(value.get("challenge"))
            and value.get("recomputed_truth") is True
            and isinstance(value.get("criteria_results"), list)
            and bool(value.get("criteria_results"))
        )
    if schema == "simplicio.independent-watcher-receipt/v1":
        return (
            value.get("status") == "MEASURED"
            and value.get("match") is True
            and _text_value(value.get("checked_at"))
            and _text_value(value.get("run_id"))
            and _text_value(value.get("challenge"))
            and isinstance(value.get("criteria_results"), list)
            and bool(value.get("criteria_results"))
        )
    if schema == "simplicio.watcher-invocation/v1":
        return value.get("returncode") == 0 and _text_value(value.get("receipt")) and _text_value(value.get("checked_at"))
    if schema == "simplicio.completion-receipt/v1":
        return (
            value.get("ready") is True
            and value.get("verdict") in {"VERIFIED", "COMPLETE", "PASSED"}
            and _text_value(value.get("run_id"))
            and _text_value(value.get("generated_at"))
            and _text_value(value.get("reason_code"))
            and value.get("watcher_status") == "MEASURED"
            and value.get("watcher_match") is True
        )
    if schema == "simplicio.completion-oracle-matrix/v1":
        return value.get("parity") is True and isinstance(value.get("adapters"), list) and bool(value.get("adapters"))
    return False


def _pointer(
    value: Any, *, root: Path, artifact_dir: Path, flow: str, phase: str,
    expected_run_id: str = "", expected_repo: str = "", expected_task_id: str = "",
    expected_task_index: int | None = None, require_task_identity: bool = False,
) -> dict[str, str] | None:
    """Return a pointer only for a durable, typed receipt inside ``root``."""
    if isinstance(value, Mapping):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        path = artifact_dir / path
    if path.suffix.lower() != ".json" or not path.is_file() or path.is_symlink() or not _within(root, path):
        return None
    payload = _read_json(path)
    if payload is None or not payload or not _valid_phase_receipt(payload, phase):
        return None
    if expected_run_id and _text_value(payload.get("run_id")) and payload.get("run_id") != expected_run_id:
        return None
    if expected_repo and _text_value(payload.get("repo")):
        try:
            if Path(str(payload["repo"])).resolve() != Path(expected_repo).resolve():
                return None
        except (OSError, TypeError, ValueError):
            return None
    if expected_task_id and _text_value(payload.get("task_id")) and payload.get("task_id") != expected_task_id:
        return None
    if expected_task_index is not None and payload.get("task_index") not in (None, expected_task_index):
        return None
    if require_task_identity:
        has_task_id = _text_value(payload.get("task_id"))
        has_task_index = (
            isinstance(payload.get("task_index"), int)
            and not isinstance(payload.get("task_index"), bool)
        )
        if not (has_task_id or has_task_index):
            # The production runner also emits immutable per-task filenames for
            # operator receipts. A scoped filename is an identity binding; the
            # run-level "operator-receipt.json" is deliberately not one.
            scoped = re.search(
                r"(?:operator|dev[-_]cli|mutation|evidence|watcher|completion)[-_]task[-_](\d+)|"
                r"(?:operator|dev[-_]cli|mutation|evidence|watcher|completion)[-_](\d+)",
                path.stem,
                re.IGNORECASE,
            )
            if not scoped:
                return None
            scoped_index = int(scoped.group(1) or scoped.group(2))
            if expected_task_index is None or scoped_index != expected_task_index:
                return None
    return {"kind": "receipt", "ref": _relative_ref(artifact_dir, path)}


def _phase_receipt_candidates(
    phase: str, *, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any]
) -> list[Any]:
    state_phase = _state_for_phase(state, phase)
    names = _PHASE_RECEIPT_KEYS[phase]
    values: list[Any] = []

    # A generic ``receipt`` is meaningful only below an already phase-scoped
    # object (for example ``mutation.receipt``).  Do not recursively search the
    # whole observation: evidence.operator.receipt_path must never become a
    # Dev CLI receipt, and result.receipt must never satisfy every phase.
    values.extend(
        state_phase.get(key)
        for key in ("receipt", "receipt_path", "path")
        if state_phase.get(key)
    )
    values.extend(
        value
        for key, value in observed.items()
        if str(key).strip().lower() in names and value
    )
    values.extend(
        value
        for key, value in result.items()
        if str(key).strip().lower() in names and value
    )
    scoped_objects: list[Mapping[str, Any]] = []
    for container in (state_phase, observed, result):
        for key, value in container.items():
            normalized = str(key).strip().lower()
            if normalized in names and isinstance(value, Mapping):
                scoped_objects.append(value)
    for scoped in scoped_objects:
        values.extend(
            scoped.get(key)
            for key in ("receipt", "receipt_path", "path")
            if scoped.get(key)
        )
    values.extend(str(root / name) for name in _PHASE_FILE_NAMES[phase])
    if phase == "loop":
        values.extend((str(root / "loop" / "watcher_state.json"), str(root / "loop" / "watcher-receipt.json")))
    return [value for value in values if value]


def _phase_evidence(
    phase: str, *, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any], receipt: dict[str, str] | None,
    expected_run_id: str = "", expected_repo: str = "",
) -> list[dict[str, str]]:
    if receipt is not None:
        return [receipt]
    state_phase = _state_for_phase(state, phase)
    if phase == "loop":
        for candidate in (root / "loop" / "watcher_state.json", root / "watcher-receipt.json", root / "evidence-receipt.json", root / "completion-receipt.json"):
            pointer = _pointer(str(candidate), root=root, artifact_dir=artifact_dir, flow=str(observed.get("flow") or "unknown"), phase=phase, expected_run_id=expected_run_id, expected_repo=expected_repo)
            if pointer is not None:
                return [pointer]
    return [{
        "kind": "phase-observation",
        "ref": f"adapter://{observed.get('flow') or 'unknown'}/{phase}/missing/{_digest({'state': state_phase, 'result': result.get(phase)})}",
        "status": "receipt_missing",
    }]


def _loop_complete(root: Path, state: Mapping[str, Any], result: Mapping[str, Any], *, run_id: str, repo: str) -> bool:
    def durable(path: Path) -> Mapping[str, Any] | None:
        pointer = _pointer(str(path), root=root, artifact_dir=root, flow="loop", phase="loop",
                           expected_run_id=run_id, expected_repo=repo)
        return _read_json(path) if pointer is not None else None

    watcher = durable(root / "loop" / "watcher_state.json") or durable(root / "watcher-receipt.json")
    evidence = durable(root / "evidence-receipt.json")
    completion = durable(root / "completion-receipt.json")
    if not watcher or not evidence or not completion:
        return False
    oracle_matrix = _read_json(root / "oracle-matrix.json")
    if oracle_matrix is not None and not _valid_phase_receipt(oracle_matrix, "loop"):
        return False
    return (
        watcher.get("status") == "MEASURED"
        and watcher.get("match") is True
        and evidence.get("status") == "VERIFIED"
        and completion.get("ready") is True
        and completion.get("verdict") in {"VERIFIED", "COMPLETE", "PASSED"}
        and _state_for_phase(state, "loop").get("ready") is True
        and _mapping(state.get("completion")).get("ready") is True
        and watcher.get("run_id") == completion.get("run_id")
        and evidence.get("run_id") == completion.get("run_id")
        and completion.get("run_id") == run_id
    )


def _phase(
    phase: str, *, flow: str, root: Path, artifact_dir: Path, observed: Mapping[str, Any], state: Mapping[str, Any], result: Mapping[str, Any], expected: bool, run_id: str, repo: str
) -> dict[str, Any]:
    state_phase = _state_for_phase(state, phase)
    candidates = _phase_receipt_candidates(phase, root=root, artifact_dir=artifact_dir, observed=observed, state=state, result=result)
    receipt = next((pointer for value in candidates if (pointer := _pointer(value, root=root, artifact_dir=artifact_dir, flow=flow, phase=phase, expected_run_id=run_id, expected_repo=repo))), None)
    evidence = _phase_evidence(phase, root=root, artifact_dir=artifact_dir, observed={**dict(observed), "flow": flow}, state=state, result=result, receipt=receipt, expected_run_id=run_id, expected_repo=repo)

    explicit = str(state_phase.get("status") or "").strip().lower()
    if explicit not in _PHASE_STATUSES:
        explicit = ""
    if phase == "loop":
        complete = _loop_complete(root, state, result, run_id=run_id, repo=repo)
        if complete:
            status = "complete"
        elif explicit in {"blocked", "error", "running", "partial"}:
            status = explicit
        elif receipt is not None:
            status = "partial"
        else:
            status = "not_run"
        if expected and receipt is None and status == "not_run":
            status = "blocked"
        return {"status": status, "provider_called": receipt is not None, "receipt": receipt, "evidence": evidence}

    if receipt is not None:
        status = "blocked" if explicit in {"blocked", "error"} else "complete"
    elif explicit in {"blocked", "error", "running", "partial"}:
        status = explicit
    elif state_phase or candidates:
        status = "blocked"
    else:
        status = "not_run"
    if expected and receipt is None:
        status = "blocked" if phase == "mapper" else "not_run"
    if receipt is None and expected:
        evidence.append({"kind": "governor", "ref": f"adapter://{flow}/governor"})
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
    failed = {int(value) for value in (result.get("failed_task_indices") or []) if str(value).lstrip("-").isdigit()}
    blocked = {int(value) for value in (result.get("blocked_task_indices") or []) if str(value).lstrip("-").isdigit()}
    state_tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    state_by_index: dict[int, Mapping[str, Any]] = {}
    state_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_task in state_tasks:
        item = _mapping(raw_task)
        try:
            task_index = int(item.get("task_index"))
        except (TypeError, ValueError):
            task_index = 0
        if task_index > 0:
            state_by_index[task_index] = item
        if item.get("task_id"):
            state_by_id[str(item["task_id"])] = item
    expected_run_id = str(state.get("run_id") or observed.get("run_id") or "")
    expected_repo = str(observed.get("repo") or "")
    if not expected_repo:
        manifest = _mapping(observed.get("manifest"))
        expected_repo = str(manifest.get("repo") or "")

    def first_pointer(source: Mapping[str, Any], keys: tuple[str, ...], *, phase: str, task_id: str, task_index: int) -> dict[str, str] | None:
        for key in keys:
            pointer = _pointer(
                source.get(key), root=artifact_dir, artifact_dir=artifact_dir,
                flow=flow, phase=phase, expected_run_id=expected_run_id,
                expected_repo=expected_repo, expected_task_id=task_id,
                expected_task_index=task_index,
            )
            if pointer is not None:
                if phase == "dev_cli" and pointer["ref"] in used_dev_refs:
                    continue
                return pointer
        return None

    used_dev_refs: set[str] = set()
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
        persisted_task = state_by_index.get(index + 1) or state_by_id.get(task_id) or {}
        worker_status = str(worker.get("status") or "").lower()
        task_status = str(persisted_task.get("status") or "").lower()
        dev_receipt = first_pointer(
            worker, ("dev_cli_receipt", "operator_receipt", "mutation_receipt"),
            phase="dev_cli", task_id=task_id, task_index=index + 1,
        ) or first_pointer(
            persisted_task, ("dev_cli_receipt", "operator_receipt", "mutation_receipt"),
            phase="dev_cli", task_id=task_id, task_index=index + 1,
        )
        if dev_receipt is None and len(raw_tasks) == 1:
            state_operator = _state_for_phase(state, "dev_cli")
            dev_receipt = first_pointer(
                state_operator, ("dev_cli_receipt", "operator_receipt", "mutation_receipt", "receipt"),
                phase="dev_cli", task_id=task_id, task_index=index + 1,
            )
        if dev_receipt is not None:
            used_dev_refs.add(dev_receipt["ref"])
        if expected or (index + 1) in blocked or worker_status in {"blocked", "paused", "cancelled"} or task_status in {"blocked", "paused", "cancelled"}:
            status = "blocked"
        elif (index + 1) in failed or worker_status in {"failed", "error"}:
            status = "error"
        elif task_status in {"error", "failed"}:
            status = "error"
        elif dev_receipt is not None:
            status = "complete"
        elif worker_status == "running" or task_status == "running":
            status = "running"
        else:
            status = "queued"
        evidence: list[dict[str, str]] = []
        if dev_receipt is not None:
            evidence.append(dev_receipt)
        for source in (worker, persisted_task):
            pointer = first_pointer(source, ("evidence_receipt", "watcher_receipt", "completion_receipt"), phase="loop", task_id=task_id, task_index=index + 1)
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
    return None


def _status(*, tasks: Sequence[Mapping[str, Any]], phases: Mapping[str, Mapping[str, Any]], observed: Mapping[str, Any], expected: bool, real_provider: bool) -> tuple[str, str]:
    if expected and not real_provider:
        return "expected_governor_blocked", "expected_governor_blocked"
    if expected and real_provider:
        return "blocked", "governor_provider_conflict"
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
    if not state and artifact_dir.is_dir():
        state = _read_json(artifact_dir / "state.json") or {}
    if not supplied.get("manifest") and artifact_dir.is_dir():
        supplied["manifest"] = _read_json(artifact_dir / "manifest.json") or {}
    result = _mapping(supplied.get("result") or supplied)
    contract = _mapping(supplied.get("contract"))
    if not contract and artifact_dir.is_dir():
        contract = _read_json(artifact_dir / "task-contract.json") or {}
    expected = expected_governor_blocked({**supplied, "result": result})
    phase_observed = {**supplied, "repo": str(root)}
    phases = {
        phase: _phase(
            phase, flow=flow, root=artifact_dir, artifact_dir=artifact_dir,
            observed=phase_observed, state=state, result=result,
            expected=expected is not None, run_id=resolved_run_id, repo=str(root),
        )
        for phase in PHASES
    }
    real_provider = any(bool(phases[phase].get("provider_called")) for phase in PHASES)
    task_rows = _task_rows(
        contract, observed=phase_observed, state=state, result=result,
        expected=expected is not None, artifact_dir=artifact_dir, flow=flow,
    )
    status, reason_code = _status(
        tasks=task_rows, phases=phases,
        observed={**phase_observed, "result": result},
        expected=expected is not None, real_provider=real_provider,
    )
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
