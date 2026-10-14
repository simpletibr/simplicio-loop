"""Mapper and Dev CLI preflight: capability probes, receipt validation and ``_run_mapper`` (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Sequence,
    Tuple,
)
from .plan_contract import validate_plan
from .ecc_guidance import (
    ecc_required,
    ensure_ecc_ready,
    extract_guidance_reference,
    inspect_ecc,
)
from .openrouter_operator import (
    external_preflight_admissible as _external_preflight_admissible,
)
from .runner_core import (
    MAPPER_MIN_VERSION,
    MAPPER_REQUIRED_VERBS,
    DEVCLI_REQUIRED_TOKENS,
    DEVCLI_MIN_VERSION,
    DEVCLI_REQUIRED_CAPABILITIES,
    BATCH_PREFLIGHT_SCHEMA,
    _now,
    _load_json,
    _write_json,
    _verify_storage_route,
    _run_cmd,
    _mapper_timeout_seconds,
    _mapper_supports_command,
    _mapper_inspection_is_fresh,
    _mapper_inspection_reports_stale,
    _degraded_mapper_fallback_enabled,
    _degraded_mapper_payload,
    _devcli_env,
    _devcli_cmd,
    _repo_fingerprint,
    _repo_state_equivalent,
    _parse_version_tuple,
    _preflight_override,
    _resolved_identity,
)
from .runner_lifecycle import _transition, _emit_event
from .runner_plan import _build_plan_with_hints

# Zero-probe cache: static capability info (identity/help/version banner) never
# changes within a run, so it is probed at most ONCE per run_root and reused by
# every subsequent task attempt. `repo_state` is NOT cached here -- it is
# recomputed fresh on every call (cheap, no subprocess) so the receipt's
# staleness check in `_validate_run_receipts` keeps working unchanged.
_CAPABILITY_PROBE_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _mapper_capability_probe(repo_path: Path) -> Dict[str, Any]:
    """One subprocess pair for mapper identity/version/help -- callers cache the result."""
    identity = _resolved_identity("simplicio-mapper", ("simplicio-mapper",))
    version = _run_cmd(["simplicio-mapper", "--version"], repo_path)
    help_result = _run_cmd(["simplicio-mapper", "--help"], repo_path)
    return {
        "identity": identity,
        "version_stdout": (version.stdout or "").strip(),
        "version_rc": version.returncode,
        "help_stdout": (help_result.stdout or "").strip(),
        "help_rc": help_result.returncode,
    }


def _cached_mapper_capability_probe(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    key = ("mapper", str(run_root))
    cached = _CAPABILITY_PROBE_CACHE.get(key)
    if cached is None:
        cached = _mapper_capability_probe(repo_path)
        _CAPABILITY_PROBE_CACHE[key] = cached
    return cached


def reset_capability_probe_cache() -> None:
    """Test/utility hook: drop every cached capability probe (all run_roots)."""
    _CAPABILITY_PROBE_CACHE.clear()


def _preflight_mapper(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    override = _preflight_override("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON")
    if override is not None:
        identity = {"command": "simplicio-mapper", "path": "", "identity_ok": True}
        version_stdout = str(override.get("version_stdout", ""))
        help_stdout = str(override.get("help_stdout", ""))
        version_rc = int(override.get("version_returncode", 0))
        help_rc = int(override.get("help_returncode", 0))
    else:
        cached = _cached_mapper_capability_probe(repo_path, run_root)
        identity = cached["identity"]
        version_stdout = cached["version_stdout"]
        help_stdout = cached["help_stdout"]
        version_rc = cached["version_rc"]
        help_rc = cached["help_rc"]
    parsed_version = _parse_version_tuple(version_stdout)
    missing_verbs = [verb for verb in MAPPER_REQUIRED_VERBS if verb not in help_stdout]
    task_aware_flags = ("--goal", "--task-file", "--task-fingerprint")
    supported_task_aware_flags = [flag for flag in task_aware_flags if flag in help_stdout]
    receipt = {
        "tool": "simplicio-mapper",
        "returncode": version_rc,
        "stdout": version_stdout,
        "help_returncode": help_rc,
        "help_stdout": help_stdout,
        "version": ".".join(str(part) for part in parsed_version),
        "min_version": ".".join(str(part) for part in MAPPER_MIN_VERSION),
        "version_ok": parsed_version >= MAPPER_MIN_VERSION,
        "required_verbs": list(MAPPER_REQUIRED_VERBS),
        "missing_verbs": missing_verbs,
        "task_aware_flags": list(task_aware_flags),
        "supported_task_aware_flags": supported_task_aware_flags,
        "task_aware_supported": len(supported_task_aware_flags) == len(task_aware_flags),
        "repo_state": _repo_fingerprint(repo_path),
        "path": identity["path"],
        "identity_ok": identity["identity_ok"],
        "checked_at": _now(),
    }
    _write_json(run_root / "mapper-preflight.json", receipt)
    if version_rc != 0 or help_rc != 0:
        raise RuntimeError("simplicio-mapper unavailable")
    if not receipt["identity_ok"]:
        raise RuntimeError("simplicio-mapper identity mismatch")
    if parsed_version < MAPPER_MIN_VERSION:
        raise RuntimeError("simplicio-mapper below minimum version")
    if missing_verbs:
        raise RuntimeError("simplicio-mapper missing required capabilities")
    return receipt


def _operator_capability_gaps(help_stdout: str, task_help_stdout: str) -> Tuple[List[str], List[str]]:
    """Derive dev-cli capability gaps from the exact persisted help surfaces."""
    capability_surface = " ".join(part for part in (help_stdout, task_help_stdout) if part)
    missing_tokens = [
        token for token in DEVCLI_REQUIRED_TOKENS
        if token not in (" " + capability_surface)
    ]
    missing_capabilities = [
        capability for capability in DEVCLI_REQUIRED_CAPABILITIES
        if capability not in capability_surface
    ]
    return missing_tokens, missing_capabilities


class DevCliCapabilitiesUnavailableError(RuntimeError):
    """Neither the in-process capabilities manifest nor `capabilities --json`
    resolved. No backward-compat layer -- fail closed with a typed reason."""

    def __init__(self, message: str, *, reason_code: str = "devcli_capabilities_unavailable") -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _devcli_capability_probe(repo_path: Path) -> Dict[str, Any]:
    """One in-process manifest read when available, else one `capabilities --json`
    subprocess. No legacy --help/--version fallback: an install that supports
    neither path fails closed (`devcli_capabilities_unavailable`).
    Callers cache the result -- this must run at most once per run_root."""
    identity = _resolved_identity("simplicio-dev-cli", ("simplicio-dev-cli", "simplicio-py"))
    manifest: Dict[str, Any] | None = None
    try:
        from simplicio.capabilities import load_capabilities_manifest  # type: ignore

        manifest = load_capabilities_manifest()
    except Exception:
        manifest = None
    env = _devcli_env(repo_path)
    if manifest is None:
        try:
            probe = subprocess.run(
                _devcli_cmd(repo_path, "capabilities", "--json"),
                cwd=str(repo_path), capture_output=True, text=True, timeout=180, env=env,
            )
            if probe.returncode == 0 and probe.stdout:
                manifest = json.loads(probe.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            manifest = None
    if manifest is None:
        raise DevCliCapabilitiesUnavailableError(
            "simplicio-dev-cli capabilities are unavailable: neither the in-process "
            "simplicio.capabilities manifest nor `simplicio-dev-cli capabilities --json` "
            "resolved. Install simplicio-loop>=3.46.0."
        )
    commands = manifest.get("commands") or {}
    edit_spec = commands.get("edit") or {}
    surface_parts = [manifest.get("schema", ""), " ".join(manifest.get("top_level_flags") or [])]
    for name, spec in commands.items():
        if not isinstance(spec, Mapping):
            continue
        surface_parts.append(name)
        surface_parts.append(" ".join(spec.get("flags") or []))
        surface_parts.append(str(spec.get("help", "")))
    help_stdout = " ".join(part for part in surface_parts if part)
    task_help_stdout = " ".join(
        part for part in (
            "edit", " ".join(edit_spec.get("flags") or []), str(edit_spec.get("help", "")),
        ) if part
    )
    version = str((manifest.get("package") or {}).get("version") or "")
    return {
        "identity": identity,
        "help_stdout": help_stdout,
        "help_rc": 0,
        "task_help_stdout": task_help_stdout,
        "task_help_rc": 0,
        "version_stdout": f"simplicio-dev-cli {version}".strip() if version else "",
        "version_rc": 0 if version else 1,
    }


def _cached_devcli_capability_probe(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    key = ("devcli", str(run_root))
    cached = _CAPABILITY_PROBE_CACHE.get(key)
    if cached is None:
        cached = _devcli_capability_probe(repo_path)
        _CAPABILITY_PROBE_CACHE[key] = cached
    return cached


def _preflight_operator(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    # Issue #135: the operator bridge validates identity + capability + MIN_VERSION,
    # not merely `which`. A wrong homonym (PATH resolves but the stem mismatches) or a
    # version below DEVCLI_MIN_VERSION blocks before any mutation.
    override = _preflight_override("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON")
    if override is not None:
        identity = {"command": "simplicio-dev-cli", "path": str(override.get("path", "")), "identity_ok": True}
        help_stdout = str(override.get("help_stdout", ""))
        help_rc = int(override.get("help_returncode", 0))
        task_help_stdout = str(override.get("task_help_stdout", help_stdout))
        task_help_rc = int(override.get("task_help_returncode", help_rc))
        version_stdout = str(override.get("version_stdout", "simplicio-py 0.14.0"))
        version_rc = int(override.get("version_returncode", 0))
    else:
        cached = _cached_devcli_capability_probe(repo_path, run_root)
        identity = cached["identity"]
        help_stdout = cached["help_stdout"]
        help_rc = cached["help_rc"]
        task_help_stdout = cached["task_help_stdout"]
        task_help_rc = cached["task_help_rc"]
        version_stdout = cached["version_stdout"]
        version_rc = cached["version_rc"]
    missing_tokens, missing_capabilities = _operator_capability_gaps(help_stdout, task_help_stdout)
    parsed_version = _parse_version_tuple(version_stdout)
    receipt = {
        "tool": "simplicio-dev-cli",
        "returncode": help_rc,
        "help_stdout": help_stdout,
        "task_help_returncode": task_help_rc,
        "task_help_stdout": task_help_stdout,
        "required_tokens": list(DEVCLI_REQUIRED_TOKENS),
        "missing_tokens": missing_tokens,
        "path": identity["path"],
        "identity_ok": identity["identity_ok"],
        "version_stdout": version_stdout,
        "version_returncode": version_rc,
        "version": ".".join(str(part) for part in parsed_version),
        "min_version": ".".join(str(part) for part in DEVCLI_MIN_VERSION),
        "version_ok": parsed_version >= DEVCLI_MIN_VERSION,
        "required_capabilities": list(DEVCLI_REQUIRED_CAPABILITIES),
        "missing_capabilities": missing_capabilities,
        "repo_state": _repo_fingerprint(repo_path),
        "checked_at": _now(),
    }
    _write_json(run_root / "operator-preflight.json", receipt)
    if help_rc != 0 or task_help_rc != 0:
        raise RuntimeError("simplicio-dev-cli unavailable")
    if not receipt["identity_ok"]:
        raise RuntimeError("simplicio-dev-cli identity mismatch")
    if missing_tokens or missing_capabilities:
        raise RuntimeError("simplicio-dev-cli missing required capabilities")
    if version_rc != 0:
        raise RuntimeError("simplicio-dev-cli version probe failed")
    if not receipt["version_ok"]:
        raise RuntimeError(
            "simplicio-dev-cli below minimum version %s (found %s)"
            % (receipt["min_version"], receipt["version"])
        )
    return receipt


def _validate_mapper_receipt(payload: Mapping[str, Any], repo_path: Path) -> None:
    """Require the mapper's own artifact receipt, not a caller-supplied freshness flag."""
    inspect = payload.get("inspect") or {}
    inspect_out = inspect.get("stdout") or {}
    status = inspect_out.get("status") or {}
    evidence = inspect_out.get("evidence") or {}
    artifacts = evidence.get("artifacts") or {}
    if not status.get("artifacts_present") or not status.get("fresh"):
        raise RuntimeError("mapper artifacts are missing or stale")
    # context_cache is an optional cache artifact the mapper does not always emit;
    # it must not block the loop when only that one is missing. A worktree served by an overlay (#1673) has
    # `not_served_by_overlay` artifacts by design: they do not exist there and are not missing. The served ones stay required.
    required_artifacts = {
        key: item for key, item in artifacts.items()
        if isinstance(item, Mapping) and key != "context_cache" and item.get("state") != "not_served_by_overlay"
    }
    if not required_artifacts or any(
        not bool(item.get("exists")) for item in required_artifacts.values()
    ):
        raise RuntimeError("mapper artifact evidence is incomplete")
    handoff = ((payload.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    for item in handoff.get("files") or []:
        raw = item.get("path") if isinstance(item, Mapping) else ""
        if not raw:
            continue
        try:
            candidate = (repo_path / str(raw)).resolve() if not Path(str(raw)).is_absolute() else Path(str(raw)).resolve()
            candidate.relative_to(repo_path.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"mapper returned path outside authorized repo: {raw}") from exc


def _mapper_generation(repo_path: Path) -> Dict[str, str]:
    """Read the immutable Mapper index identity for the active attempt.

    Identity is exactly Mapper's ``head`` + ``tree_hash`` -- never
    ``index-state.json``'s ``updated_at``, and never its ``status_hash``.

    ``updated_at`` is rewritten to "now" on *every* Mapper invocation,
    including a purely read-only re-survey (e.g. the host running
    ``simplicio-loop orient`` again between ``prepare`` and ``wave`` to
    refresh context before a retry) that touches no source file.

    ``status_hash`` is a hash of Mapper's own ``git status`` snapshot at
    survey time. Empirically (see the multiprocess/orient regression this
    guards), it also changes across back-to-back re-surveys of an unchanged
    tree -- Mapper's own scan writes timestamped bookkeeping under its own
    excluded output directory, and that housekeeping alone was observed to
    shift ``status_hash`` with no tracked or working-tree file touched.
    ``head`` (the resolved commit) and ``tree_hash`` (a content/mtime digest
    over the actual working tree, excluding Mapper's own output dir) are the
    two fields that stayed stable across every read-only re-survey tested and
    still change on any real source edit -- that pair is the right identity
    for "did the tree Mapper surveyed actually change", not a field that
    churns on Mapper's own bookkeeping and would turn every such read-only
    re-survey into a false "active attempt mapper generation changed" block.
    """
    path = repo_path / ".simplicio-loop" / "index-state.json"
    try:
        document = _load_json(path)
    except (OSError, TypeError, ValueError):
        return {}
    signature = document.get("signature") if isinstance(document, Mapping) else None
    if not isinstance(signature, Mapping):
        return {}
    return {
        key: str(signature.get(key) or "")
        for key in ("head", "tree_hash")
        if str(signature.get(key) or "")
    }


def _receipt_run_id(payload: Mapping[str, Any], expected_run_id: str) -> str:
    """Bind a receipt to its run directory when it omitted run_id."""
    raw = payload.get("run_id")
    if raw in {None, ""}:
        return expected_run_id
    return str(raw)


def _require_matching_run_id(payload: Mapping[str, Any], expected_run_id: str, label: str) -> None:
    if _receipt_run_id(payload, expected_run_id) != expected_run_id:
        raise RuntimeError(f"{label} receipt is not bound to the current run")


def _require_json_receipt(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing required {label} receipt: {path.name}")
    try:
        payload = _load_json(path)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"invalid required {label} receipt: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid required {label} receipt: {path.name}")
    return payload


def _validate_run_receipts(
    repo_path: Path,
    run_dir: Path,
    contract: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    require_dry_run: bool = True,
) -> Dict[str, Any]:
    """Require a current, run-bound mapper -> plan -> operator receipt chain."""
    storage_route = _verify_storage_route(run_dir)
    mapper = _require_json_receipt(run_dir / "mapper-context.json", "mapper context")
    plan = _require_json_receipt(run_dir / "plan.json", "plan")
    mapper_preflight = _require_json_receipt(run_dir / "mapper-preflight.json", "mapper preflight")
    operator_preflight = _require_json_receipt(run_dir / "operator-preflight.json", "operator preflight")
    operator = _require_json_receipt(run_dir / "operator-receipt.json", "operator")
    if ecc_required() and extract_guidance_reference(operator) is None:
        raise RuntimeError("required ECC guidance reference is missing from operator receipt")

    expected_run_id = str((manifest or {}).get("run_id") or run_dir.name)
    if run_dir.name != expected_run_id:
        raise RuntimeError("run receipts are not bound to the current run")
    if state is not None and str(state.get("run_id") or "") != expected_run_id:
        raise RuntimeError("run state is not bound to the current run")
    expected_contract_hash = str((manifest or {}).get("collection_hash") or "")
    contract_hash = str(contract.get("collection_hash") or "")
    if expected_contract_hash and contract_hash != expected_contract_hash:
        raise RuntimeError("task contract is not bound to the current run")
    if mapper.get("run_id") != expected_run_id or plan.get("run_id") != expected_run_id:
        raise RuntimeError("mapper and plan receipts are not bound to the current run")
    _require_matching_run_id(operator, expected_run_id, "operator")
    if mapper.get("task_contract_hash") != contract_hash or plan.get("task_contract_hash") != contract_hash:
        raise RuntimeError("mapper and plan receipts do not match the task contract")
    mapper_context_hash = str(plan.get("mapper_context_hash") or "")
    if not mapper_context_hash:
        raise RuntimeError("plan receipt has no mapper context hash")
    actual_mapper_context_hash = hashlib.sha256(
        (run_dir / "mapper-context.json").read_bytes()
    ).hexdigest()
    if actual_mapper_context_hash != mapper_context_hash:
        raise RuntimeError("plan receipt does not match the current mapper context bytes")
    mapper_generation = dict(mapper.get("foreground_generation") or {})
    plan_generation = dict(plan.get("mapper_generation") or {})
    if mapper_generation != plan_generation:
        raise RuntimeError("plan receipt does not match the pinned mapper generation")
    if mapper_generation:
        current_generation = _mapper_generation(repo_path)
        if current_generation and current_generation != mapper_generation:
            raise RuntimeError("active attempt mapper generation changed")

    degraded_mapper = bool(mapper.get("degraded_local"))
    if degraded_mapper:
        if not _degraded_mapper_fallback_enabled():
            raise RuntimeError("degraded mapper context requires standalone local fallback")
        context_pack = ((mapper.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
        if not context_pack.get("pack_hash"):
            raise RuntimeError("degraded mapper context has no local context-pack hash")
    else:
        for name, payload in (("scan", mapper.get("scan")), ("inspect", mapper.get("inspect")),
                              ("handoff", mapper.get("handoff"))):
            if not isinstance(payload, Mapping) or payload.get("returncode") != 0:
                raise RuntimeError(f"stale mapper context: {name} did not complete successfully")
        _validate_mapper_receipt(mapper, repo_path)
    planned_state = mapper.get("repo_state_after") or {}
    current_state = _repo_fingerprint(repo_path)
    mapper_before = mapper.get("repo_state_before") or {}
    if not mapper_before.get("tree_hash") or not planned_state.get("tree_hash"):
        raise RuntimeError("mapper context has no repository fingerprint")
    if not _repo_state_equivalent(mapper_before, planned_state) or not _repo_state_equivalent(planned_state, current_state):
        raise RuntimeError("stale mapper context: repository changed after planning")

    if not mapper_preflight.get("identity_ok") or not mapper_preflight.get("version_ok"):
        raise RuntimeError("mapper preflight receipt is not valid")
    if mapper_preflight.get("missing_verbs"):
        raise RuntimeError("mapper preflight receipt is missing required capabilities")
    mapper_preflight_state = mapper_preflight.get("repo_state") or {}
    if not mapper_preflight_state.get("tree_hash") or not _repo_state_equivalent(mapper_preflight_state, current_state):
        raise RuntimeError("stale mapper preflight receipt: repository changed")
    if not operator_preflight.get("identity_ok") or not operator_preflight.get("version_ok"):
        raise RuntimeError("operator preflight receipt is not valid")
    list_fields = (
        "required_tokens", "missing_tokens", "required_capabilities", "missing_capabilities",
    )
    text_fields = ("help_stdout", "task_help_stdout")
    for field in list_fields:
        value = operator_preflight.get(field)
        if field not in operator_preflight:
            raise RuntimeError(f"operator preflight receipt is missing required field: {field}")
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RuntimeError(f"operator preflight receipt has invalid field type: {field}")
    for field in text_fields:
        if field not in operator_preflight:
            raise RuntimeError(f"operator preflight receipt is missing required field: {field}")
        if not isinstance(operator_preflight[field], str):
            raise RuntimeError(f"operator preflight receipt has invalid field type: {field}")
    if operator_preflight["required_tokens"] != list(DEVCLI_REQUIRED_TOKENS):
        raise RuntimeError("operator preflight receipt required_tokens do not match the canonical contract")
    if operator_preflight["required_capabilities"] != list(DEVCLI_REQUIRED_CAPABILITIES):
        raise RuntimeError("operator preflight receipt required_capabilities do not match the canonical contract")
    recomputed_missing_tokens, recomputed_missing_capabilities = _operator_capability_gaps(
        operator_preflight["help_stdout"], operator_preflight["task_help_stdout"],
    )
    if operator_preflight["missing_tokens"] != recomputed_missing_tokens:
        raise RuntimeError("operator preflight receipt missing_tokens do not match persisted help")
    if operator_preflight["missing_capabilities"] != recomputed_missing_capabilities:
        raise RuntimeError("operator preflight receipt missing_capabilities do not match persisted help")
    if recomputed_missing_tokens or recomputed_missing_capabilities:
        raise RuntimeError("operator preflight receipt is missing required capabilities")
    operator_preflight_state = operator_preflight.get("repo_state") or {}
    if not operator_preflight_state.get("tree_hash") or not _repo_state_equivalent(operator_preflight_state, current_state):
        raise RuntimeError("stale operator preflight receipt: repository changed")

    tasks = list(contract.get("tasks") or [])
    validation = validate_plan(
        plan, tasks, repo_path,
        contract_hash=contract_hash,
        current_state=current_state,
    )
    if not validation["valid"]:
        raise RuntimeError("stale or invalid plan receipt: " + ", ".join(validation["errors"]))
    if (plan.get("deterministic") or {}).get("verified") is not True:
        raise RuntimeError("plan receipt is not deterministic")
    context_pack = ((mapper.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    mapper_pack_hash = str(plan.get("mapper_pack_hash") or "")
    context_pack_hash = str(context_pack.get("pack_hash") or "")
    if mapper_pack_hash and context_pack_hash and mapper_pack_hash != context_pack_hash:
        raise RuntimeError("plan receipt does not match the mapper context fingerprint")

    plan_hash = hashlib.sha256((run_dir / "plan.json").read_bytes()).hexdigest()
    if operator.get("task_contract_hash") != contract_hash:
        raise RuntimeError("operator receipt does not match the task contract")
    if operator.get("plan_hash") != plan_hash:
        raise RuntimeError("operator receipt does not match the current plan")
    if operator.get("mapper_pack_hash") != plan.get("mapper_pack_hash"):
        raise RuntimeError("operator receipt does not match the mapper context")
    if operator.get("mapper_context_hash") != mapper_context_hash:
        raise RuntimeError(
            "operator receipt does not match the mapper receipt "
            f"(operator mapper_context_hash={operator.get('mapper_context_hash')!r}, "
            f"mapper mapper_context_hash={mapper_context_hash!r}). "
            "Open a new run; this blocked run will not reapply the stale receipt."
        )
    operator_state = operator.get("repo_state_before") or {}
    if not operator_state.get("tree_hash") or not _repo_state_equivalent(operator_state, current_state):
        raise RuntimeError("stale operator receipt: repository changed")
    if require_dry_run:
        dry_run_ok = operator.get("execution_state") == "dry_run" and operator.get("returncode") == 0
        external_ok = bool(operator.get("preflight_admitted")) and _external_preflight_admissible(operator)
        if not dry_run_ok and not external_ok:
            raise RuntimeError("operator receipt is not a fresh successful dry-run preflight")
    if not operator.get("target_within_repo") or not operator.get("authorized_targets"):
        raise RuntimeError("operator receipt has no authorized target")
    target = str(operator.get("target") or "")
    authorized_targets = {str(item) for item in operator.get("authorized_targets") or []}
    planned_targets = {
        str(item) for step in plan.get("steps") or []
        if isinstance(step, Mapping) for item in step.get("candidate_targets") or []
    }
    try:
        (repo_path / target).resolve().relative_to(repo_path.resolve())
    except (OSError, ValueError):
        raise RuntimeError("operator receipt target is outside the authorized repository")
    if not target or target not in authorized_targets or target not in planned_targets:
        raise RuntimeError("operator receipt target is not authorized by the plan")
    if state is not None:
        if state.get("phase") in {"blocked", "done", "cancelled"}:
            raise RuntimeError(f"run is not runnable: {state.get('phase')}")
        if not (state.get("mapper") or {}).get("ready") or not (state.get("operator") or {}).get("ready"):
            raise RuntimeError("run is not runnable: mapper/operator receipts are not ready")
    return {
        "mapper": mapper,
        "plan": plan,
        "operator_preflight": operator_preflight,
        "operator": operator,
        "storage_route": storage_route,
        "repo_state": current_state,
        "plan_hash": plan_hash,
    }


def _persist_batch_preflight_block(
    run_dir: Path,
    state: Dict[str, Any],
    repo_path: Path,
    reason: str,
    task_indices: Sequence[int] = (),
) -> Path:
    diagnostic_path = run_dir / "operator-batch-preflight.json"
    blocker = {
        "kind": "operator_batch_preflight",
        "reason_code": "operator_batch_preflight_failed",
        "message": reason,
        "run_id": str(state.get("run_id") or run_dir.name),
        "scope": "global",
    }
    diagnostic = {
        "schema": BATCH_PREFLIGHT_SCHEMA,
        "status": "BLOCKED",
        "run_id": blocker["run_id"],
        "task_indices": [int(index) for index in task_indices],
        "blocker": blocker,
        "repo_state": _repo_fingerprint(repo_path),
        "checked_at": _now(),
    }
    _write_json(diagnostic_path, diagnostic)
    state["blockers"] = [blocker]
    state["current_action"] = "operator_batch_preflight_blocked"
    state["next_action"] = "repair_mapper_or_repo"
    _write_json(run_dir / "state.json", state)
    if state.get("phase") not in {"done", "cancelled"}:
        _transition(
            run_dir, state, "blocked", "operator batch prerequisite validation failed",
            receipt=str(diagnostic_path), extra={"error": reason, "scope": "global"},
        )
    _emit_event(
        run_dir, state, "blocked", receipt=str(diagnostic_path),
        blocker=blocker["reason_code"], message="operator batch blocked before dispatch", scope="global",
    )
    return diagnostic_path


def _run_mapper(repo_path: Path, run_root: Path, task_path: str = "", goal: str = "",
                task_fingerprint: str = "", target_hint: str = "") -> Dict[str, Any]:
    # Task metadata is assembled from optional contract fields. Normalize it
    # before the task-aware path calls ``.strip()``.
    task_path = str(task_path or "")
    goal = str(goal or "")
    task_fingerprint = str(task_fingerprint or "")
    target_hint = str(target_hint or "")
    before = _repo_fingerprint(repo_path)
    mapper_preflight = _preflight_mapper(repo_path, run_root)
    ecc_admission = inspect_ecc(repo_path, run_root)
    ensure_ecc_ready(ecc_admission)
    mapper_timeout = str(_mapper_timeout_seconds())
    rollback_sync = os.environ.get("SIMPLICIO_LOOP_MAPPER_SYNC_ROLLBACK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    route_started = time.monotonic()
    phase_timings: Dict[str, Any] = {}
    scan_started = time.monotonic()
    scan = _run_cmd(
        # The foreground route must return the mapper's macro receipt without
        # waiting for the deep index.  Deep completion is polled/reconciled by
        # the subsequent inspect/handoff stages and is never a prerequisite
        # for obtaining the first bounded context.
        [
            "simplicio-mapper", "scan", ".", "--json",
            *( ["--sync"] if rollback_sync else [] ),
            "--timeout", mapper_timeout,
        ],
        repo_path,
    )
    phase_timings["scan_wall_seconds"] = round(time.monotonic() - scan_started, 6)
    inspect_started = time.monotonic()
    inspect = _run_cmd(
        [
            "simplicio-mapper", "inspect", ".", "--json",
            *( ["--await"] if rollback_sync else [] ),
            "--timeout", mapper_timeout,
        ],
        repo_path,
    )
    if not rollback_sync and _mapper_inspection_reports_stale(inspect):
        # The default Mapper route is macro-first/background.  A cold repository can
        # still be indexing when the first inspect returns, which used to surface as
        # a stale-artifact block and force callers to know the private sync toggle.
        # Reconcile that normal warm-up inside the zero-config run once, then keep the
        # existing receipt/freshness gate unchanged.
        await_scan = _run_cmd(
            [
                "simplicio-mapper", "scan", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
        if await_scan.returncode == 0:
            scan = await_scan
        inspect = _run_cmd(
            [
                "simplicio-mapper", "inspect", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
    phase_timings["inspect_wall_seconds"] = round(time.monotonic() - inspect_started, 6)
    if _mapper_supports_command(mapper_preflight, "snapshot"):
        snapshot = _run_cmd(["simplicio-mapper", "snapshot", "build", "--json", "."], repo_path)
    else:
        # Snapshot is an optional capability and is not present in current Mapper
        # releases. Do not turn an otherwise usable inspect/handoff into a hard block.
        snapshot = subprocess.CompletedProcess(
            ["simplicio-mapper", "snapshot", "build", "--json", "."],
            0,
            json.dumps({"status": "skipped", "reason": "optional_command_unavailable"}),
            "",
        )
    handoff_argv = ["simplicio-mapper", "handoff", ".", "--json"]
    if rollback_sync:
        handoff_argv.append("--await")
    handoff_argv.extend(["--timeout", mapper_timeout, "--execution-context"])
    task_aware_supported = bool(mapper_preflight.get("task_aware_supported"))
    mapper_token_budget = os.environ.get("SIMPLICIO_LOOP_MAPPER_TOKEN_BUDGET", "").strip()
    if mapper_token_budget.isdigit() and int(mapper_token_budget) > 0:
        handoff_argv.extend(["--token-budget", mapper_token_budget])
    if task_aware_supported and goal.strip():
        handoff_argv.extend(["--goal", goal.strip()])
    if task_aware_supported and task_path.strip():
        handoff_argv.extend(["--task-file", task_path.strip()])
    if task_aware_supported and task_fingerprint.strip():
        handoff_argv.extend(["--task-fingerprint", task_fingerprint.strip()])
    if task_aware_supported and target_hint.strip():
        handoff_argv.extend(["--target", target_hint.strip()])
    handoff_started = time.monotonic()
    handoff = _run_cmd(handoff_argv, repo_path)
    phase_timings["handoff_wall_seconds"] = round(time.monotonic() - handoff_started, 6)
    handoff_recovery = None
    try:
        handoff_stdout = json.loads(handoff.stdout) if handoff.stdout.strip() else {}
    except ValueError:
        handoff_stdout = {}
    handoff_pack = handoff_stdout.get("context_pack") if isinstance(handoff_stdout, Mapping) else {}
    configured_budget = int(mapper_token_budget) if mapper_token_budget.isdigit() else 8_000
    estimated_tokens = (
        handoff_pack.get("estimated_tokens")
        if isinstance(handoff_pack, Mapping) else None
    )
    over_budget = (
        isinstance(estimated_tokens, (int, float))
        and not isinstance(estimated_tokens, bool)
        and estimated_tokens > configured_budget
    )
    serialization_budget = (
        handoff_pack.get("serialization_budget")
        if isinstance(handoff_pack, Mapping) and isinstance(handoff_pack.get("serialization_budget"), Mapping)
        else {}
    )
    budget_compacted_over_limit = (
        bool(serialization_budget.get("compacted"))
        and isinstance(serialization_budget.get("estimated_tokens"), int)
        and isinstance(serialization_budget.get("token_budget"), int)
        and serialization_budget["estimated_tokens"] > serialization_budget["token_budget"]
    )
    if (
        task_aware_supported
        and task_path.strip()
        and target_hint.strip()
        and handoff.returncode == 0
        and isinstance(handoff_pack, Mapping)
        and (
            bool(handoff_pack.get("needs_broader_context"))
            or over_budget
            or not str(handoff_pack.get("pack_hash") or "").strip()
            or budget_compacted_over_limit
        )
    ):
        recovery_argv = ["simplicio-mapper", "handoff", ".", "--json"]
        if rollback_sync:
            recovery_argv.append("--await")
        recovery_argv.extend(["--timeout", mapper_timeout, "--execution-context"])
        recovery_budget = min(
            128_000,
            max(
                configured_budget,
                128_000 if budget_compacted_over_limit else (
                    int(estimated_tokens) if over_budget else configured_budget
                ),
            ),
        )
        recovery_argv.extend(["--token-budget", str(recovery_budget)])
        if goal.strip():
            recovery_argv.extend(["--goal", goal.strip()])
        recovery_argv.extend(["--target", target_hint.strip()])
        limit = os.environ.get("SIMPLICIO_LOOP_MAPPER_CONTEXT_LIMIT", "8").strip()
        if limit.isdigit() and int(limit) > 0:
            recovery_argv.extend(["--limit", limit])
        recovery = _run_cmd(recovery_argv, repo_path)
        try:
            recovery_stdout = json.loads(recovery.stdout) if recovery.stdout.strip() else {}
        except ValueError:
            recovery_stdout = {}
        handoff_recovery = {
            "strategy": "goal-target-without-task-file",
            "returncode": recovery.returncode,
            "stdout": recovery_stdout,
            "stderr": (recovery.stderr or "").strip(),
        }
        if recovery.returncode == 0:
            handoff = recovery
    # A macro-first scan may finish while handoff is assembling its context. In
    # that race the handoff can already carry a fresh Mapper status while the
    # earlier inspect receipt is still stale. Reconcile the persisted inspect
    # receipt once, without requiring the private synchronous-rollback toggle.
    if not rollback_sync and not _mapper_inspection_is_fresh(inspect):
        reconcile_started = time.monotonic()
        reconciled_inspect = _run_cmd(
            [
                "simplicio-mapper", "inspect", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
        if reconciled_inspect.returncode == 0:
            inspect = reconciled_inspect
        phase_timings["inspect_reconcile_wall_seconds"] = round(
            time.monotonic() - reconcile_started, 6
        )
    scan_stdout = json.loads(scan.stdout) if scan.stdout.strip() else {}
    inspect_stdout = json.loads(inspect.stdout) if inspect.stdout.strip() else {}
    snapshot_stdout = json.loads(snapshot.stdout) if snapshot.stdout.strip() else {}
    handoff_stdout = json.loads(handoff.stdout) if handoff.stdout.strip() else {}
    foreground_generation = _mapper_generation(repo_path)
    payload = {
        "scan": {
            "returncode": scan.returncode,
            "stdout": scan_stdout,
            "stderr": (scan.stderr or "").strip(),
        },
        "inspect": {
            "returncode": inspect.returncode,
            "stdout": inspect_stdout,
            "stderr": (inspect.stderr or "").strip(),
        },
        "snapshot": {
            "returncode": snapshot.returncode,
            "stdout": snapshot_stdout,
            "stderr": (snapshot.stderr or "").strip(),
        },
        "handoff": {
            "returncode": handoff.returncode,
            "stdout": handoff_stdout,
            "stderr": (handoff.stderr or "").strip(),
        },
        "handoff_recovery": handoff_recovery,
        "ecc_admission": dict(ecc_admission),
        "execution_route": {
            "mode": "synchronous_rollback" if rollback_sync else "foreground_first",
            "rollback_flag": "SIMPLICIO_LOOP_MAPPER_SYNC_ROLLBACK" if rollback_sync else None,
            "deep_completion_required_for_first_context": rollback_sync,
            "scan_wait": rollback_sync,
            "inspect_wait": rollback_sync,
            "handoff_wait": rollback_sync,
            "background": {
                "status": "queued" if not rollback_sync else "consumed_by_sync_rollback",
                "work_id": (
                    (scan_stdout.get("deep") or {}).get("job_id")
                    if isinstance(scan_stdout, Mapping) else None
                ),
                "pid": (
                    (scan_stdout.get("deep") or {}).get("pid")
                    if isinstance(scan_stdout, Mapping) else None
                ),
                "state_path": (
                    (scan_stdout.get("deep") or {}).get("state_path")
                    if isinstance(scan_stdout, Mapping) else None
                ),
            },
            "foreground_generation": foreground_generation,
            "phase_timings_seconds": phase_timings,
            "route_wall_seconds": round(time.monotonic() - route_started, 6),
        },
        "foreground_generation": foreground_generation,
        "generated_at": _now(),
        "repo_state_before": before,
        "repo_state_after": _repo_fingerprint(repo_path),
    }
    # Mapper may return a fresh, goal-relevant pack that omits a caller's
    # explicit target. Preserve the target as an authorized, local hint so the
    # downstream operator preflight does not reject an otherwise valid run.
    if target_hint.strip() and handoff.returncode == 0:
        target_path = target_hint.strip().replace("\\", "/")
        try:
            resolved_target = (repo_path / target_path).resolve()
            resolved_target.relative_to(repo_path.resolve())
            if resolved_target.is_file():
                context_pack = payload["handoff"]["stdout"].get("context_pack")
                if isinstance(context_pack, dict):
                    files = context_pack.setdefault("files", [])
                    known = {
                        str(item.get("path") or "").replace("\\", "/")
                        for item in files if isinstance(item, dict)
                    }
                    if target_path not in known:
                        files.append({
                            "path": target_path,
                            "selection_reason": "explicit_task_target",
                            "tests": [],
                        })
                        context_pack["explicit_target_added"] = target_path
        except (OSError, ValueError):
            pass
    _write_json(run_root / "mapper-context.json", payload)
    if (scan.returncode != 0 or inspect.returncode != 0 or snapshot.returncode != 0
            or handoff.returncode != 0):
        if _degraded_mapper_fallback_enabled():
            degraded = _degraded_mapper_payload(
                repo_path, before, mapper_preflight, scan, inspect, snapshot, handoff,
                target_hint,
                ecc_admission=ecc_admission,
            )
            _write_json(run_root / "mapper-context.json", degraded)
            return degraded
        raise RuntimeError("mapper scan/inspect/snapshot/handoff failed")
    if not _repo_state_equivalent(payload["repo_state_before"], payload["repo_state_after"]):
        raise RuntimeError("repository changed during mapper survey; freshness cannot be proven")
    # Test fixtures intentionally replace the operator preflight; production runs
    # always use the mapper's own artifact/freshness receipt.
    if _preflight_override("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON") is None:
        _validate_mapper_receipt(payload, repo_path)
    return payload


def _build_plan(tasks: List[Dict[str, Any]], mapper_payload: Dict[str, Any], repo_path: Path,
                contract_hash: str = "") -> Dict[str, Any]:
    return _build_plan_with_hints(tasks, mapper_payload, repo_path, "", contract_hash=contract_hash)
