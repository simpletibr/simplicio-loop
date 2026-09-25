from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .delivery import delivery_rank, validate_delivery_receipt
from .evidence import watcher_truth_from_receipt
from .github_lifecycle import load_lifecycle_receipt
from .quality_matrix import evaluate_quality_matrix
from .execution_route import verify_route_hash

PROMISE_RE = re.compile(r"<promise>\s*(.*?)\s*</promise>", re.IGNORECASE | re.DOTALL)
COMPLETION_SCHEMA = "simplicio.completion-receipt/v1"
ORACLE_MATRIX_SCHEMA = "simplicio.completion-oracle-matrix/v1"
ADAPTERS = ("cursor", "claude", "codex", "vscode", "antigravity", "simplicio_agent", "hermes")


def _gate(name: str, ok: bool, reason_code: str, detail: str) -> Dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if ok else "fail",
        "reason_code": reason_code,
        "detail": detail,
    }


def _load_json(path: Path) -> Dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str] | None, str]:
    if not text.startswith("---"):
        return None, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, ""
    meta: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta, parts[2].strip()


def _read_response(loop_dir: Path, response_text: str) -> str:
    if response_text.strip():
        return response_text
    last_response = loop_dir / "last_response.txt"
    if last_response.exists():
        try:
            return last_response.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


def _anchor_gate(loop_dir: Path) -> Tuple[bool, Dict[str, Any], Dict[str, Any] | None]:
    anchor_path = loop_dir / "anchor.json"
    anchor = _load_json(anchor_path)
    if not anchor:
        return False, _gate("anchor", False, "anchor_missing", "anchor.json is missing or unreadable"), None
    criteria = anchor.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return False, _gate("anchor", False, "anchor_empty", "anchor criteria are missing or empty"), anchor
    pending = [c.get("id") for c in criteria if isinstance(c, dict) and c.get("status") != "done"]
    if pending:
        return False, _gate("anchor", False, "anchor_pending", f"open acceptance criteria: {', '.join(pending)}"), anchor
    return True, _gate("anchor", True, "anchor_complete", "all anchored acceptance criteria are done"), anchor


def _watcher_gate(loop_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    watcher_state = _load_json(loop_dir / "watcher_state.json")
    watcher_challenge = _load_json(loop_dir / "watcher_challenge.json")
    if not watcher_state or not watcher_challenge:
        return False, _gate("watcher", False, "watcher_missing", "watcher receipt or challenge is missing")
    if not (watcher_state.get("match") and watcher_state.get("status") == "MEASURED"):
        return False, _gate("watcher", False, "watcher_mismatch", "watcher receipt is not MEASURED/matching")
    if watcher_state.get("challenge") != watcher_challenge.get("challenge"):
        return False, _gate("watcher", False, "watcher_challenge_mismatch", "watcher receipt does not match the current challenge")
    expected_goal_fp = watcher_challenge.get("goal_fp") or ""
    if expected_goal_fp and watcher_state.get("goal_fp") != expected_goal_fp:
        return False, _gate("watcher", False, "watcher_goal_mismatch", "watcher goal fingerprint does not match the current challenge")
    checked_at = watcher_state.get("checked_at") or ""
    written_at = watcher_challenge.get("written_at") or ""
    if checked_at and written_at and checked_at < written_at:
        return False, _gate("watcher", False, "watcher_stale", "watcher receipt predates the active challenge")
    return True, _gate("watcher", True, "watcher_verified", "watcher receipt matches the current challenge")


def _run_artifacts_gate(run_dir: Path) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any] | None]:
    required = {
        "manifest": "manifest.json",
        "task_contract": "task-contract.json",
        "mapper_receipt": "mapper-context.json",
        "operator_receipt": "operator-receipt.json",
        "evidence_receipt": "evidence-receipt.json",
        "delivery_receipt": "delivery-receipt.json",
    }
    gates: List[Dict[str, Any]] = []
    loaded: Dict[str, Any] = {}
    ok = True
    for name, filename in required.items():
        payload = _load_json(run_dir / filename)
        if not payload:
            ok = False
            gates.append(_gate(name, False, f"{name}_missing", f"{filename} is missing or unreadable"))
            continue
        loaded[name] = payload
        gates.append(_gate(name, True, f"{name}_present", f"{filename} loaded"))
    if not ok:
        return False, gates, None
    contract = loaded["task_contract"]
    if not isinstance(contract.get("schema"), str) or not contract.get("schema"):
        gates.append(_gate("task_contract", False, "task_contract_invalid", "task-contract.json has no schema"))
        return False, gates, loaded
    evidence = loaded["evidence_receipt"]
    verdict = watcher_truth_from_receipt(evidence)
    if not verdict["ready"]:
        gates.append(_gate("evidence_verdict", False, "evidence_not_verified", verdict["reported"]))
        return False, gates, loaded
    gates.append(_gate("evidence_verdict", True, "evidence_verified", verdict["reported"]))
    delivery = loaded["delivery_receipt"]
    manifest = loaded["manifest"]
    target = (manifest.get("delivery_target") or "").strip().lower()
    validation = validate_delivery_receipt(delivery, target=target)
    gates.extend(validation["gates"])
    if not validation["ok"]:
        return False, gates, loaded
    return True, gates, loaded


def _source_lifecycle_gate(run_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """#285's remaining gap: wire `CLOSE_PENDING_RECONCILIATION` into the COMPLETE gate.

    `simplicio_loop/github_lifecycle.py::close_source_issue` can report
    `CLOSE_PENDING_RECONCILIATION` when the source issue closed for real but the final
    lifecycle-comment write could not be confirmed (see its docstring). Before this gate, that
    reason code was inert -- returned to a caller but never checked by anything deciding
    completion. If a lifecycle receipt has been persisted for this run
    (`github_lifecycle.persist_lifecycle_receipt`, wired from `runner.py::_sync_github_lifecycle`
    and `scripts/github_lifecycle.py`'s `publish`/`close --run-dir`) and it reports
    `CLOSE_PENDING_RECONCILIATION`, completion is blocked until `reconcile()` clears it. A run
    with no lifecycle receipt at all (no GitHub source, or lifecycle sync never enabled) is not
    penalized -- this gate is additive, never a new hard requirement for sourceless runs.
    """
    receipt = load_lifecycle_receipt(run_dir)
    if receipt is None:
        return True, _gate("source_lifecycle", True, "source_lifecycle_not_configured",
                           "no lifecycle receipt persisted for this run (no GitHub source, or sync disabled)")
    pending = receipt.get("outcome") == "CLOSE_PENDING_RECONCILIATION" or \
        receipt.get("reason_code") == "CLOSE_PENDING_RECONCILIATION"
    if pending:
        return False, _gate("source_lifecycle", False, "source_close_pending_reconciliation",
                            "the source issue close is pending reconciliation "
                            "(source closed but the final comment write is unconfirmed) -- "
                            "run `github_lifecycle.py reconcile` before completion")
    return True, _gate("source_lifecycle", True, "source_lifecycle_clear",
                       "persisted lifecycle receipt reports no pending reconciliation")


def _task_dispatch_gate(run_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """No task in the run's own dispatch batch may be failed, blocked, dead-lettered,
    or simply missing its receipt pair.

    A benchmark run can dead-letter tasks 2..N (e.g. a stale-plan false positive)
    while task 1 alone applies and passes every quality lane it happens to cover --
    `_quality_matrix_gate`'s "implementation" lane only re-proves that whichever
    receipts *exist* are applied, not that every task the run itself scheduled has
    one. This gate reads `dispatch_operator_batch`'s own persisted
    ``operator-batch.json`` (``receipt_contract``/``*_task_indices``) plus the task
    count from ``task-contract.json`` and blocks, naming the exact missing task
    indices, whenever any of them never produced a verified receipt pair. A run
    that never dispatched a batch (no ``operator-batch.json`` yet) has nothing to
    check here and defers to the other gates.
    """
    batch_path = run_dir / "operator-batch.json"
    if not batch_path.is_file():
        return True, _gate("task_dispatch", True, "task_dispatch_not_dispatched",
                           "no operator-batch.json to check yet (run has not dispatched a batch)")
    batch = _load_json(batch_path)
    if batch is None:
        return False, _gate("task_dispatch", False, "task_dispatch_receipt_unreadable",
                            "operator-batch.json is present but unreadable")
    contract = _load_json(run_dir / "task-contract.json") or {}
    task_count = len(contract.get("tasks") or [])
    completed = {int(i) for i in (batch.get("completed_task_indices") or [])}
    failed = {int(i) for i in (batch.get("failed_task_indices") or [])}
    blocked = {int(i) for i in (batch.get("blocked_task_indices") or [])}
    dead_letter = {int(i) for i in (batch.get("dead_letter_task_indices") or [])}
    receipt_contract = batch.get("receipt_contract") or {}
    missing_receipts = {int(i) for i in (receipt_contract.get("missing_task_indices") or [])}
    never_completed = {i for i in range(1, task_count + 1) if i not in completed} if task_count else set()
    problems = sorted(failed | blocked | dead_letter | missing_receipts | never_completed)
    if problems or receipt_contract.get("ready") is False:
        return False, _gate(
            "task_dispatch", False, "task_dispatch_incomplete",
            f"task index(es) {problems} never produced a verified operator+evidence "
            "receipt in this run's dispatch batch",
        )
    return True, _gate("task_dispatch", True, "task_dispatch_complete",
                       "every task in the run's dispatch batch produced a verified receipt pair")


def _quality_matrix_gate(run_dir: Path) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
    """Fail-closed quality gate (#278): implementation/unit/integration/system/
    regression/benchmark evidence plus minimum coverage, all-or-nothing."""
    verdict = evaluate_quality_matrix(str(run_dir))
    gate = _gate("quality_matrix", verdict["ready"], verdict["reason_code"], verdict["reason"])
    return verdict["ready"], gate, verdict


def _commit_binding_gate(run_dir: Path, delivery_receipt: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """#290: two green receipts for two different commits must never satisfy the same gate.

    `_run_artifacts_gate` (delivery/#288 evidence) and `_quality_matrix_gate` (#283) are each
    validated independently against the run directory, but neither previously proved they were
    talking about the *same* commit. A stale or mismatched #283 receipt could sit next to a fresh
    #288/delivery receipt and both read PASS while covering different SHAs. This gate only applies
    once the delivery state has actually reached `merge-ready` or higher (i.e. real external
    convergence is being claimed); lower states (`implemented`/`verified`/local-fixture work) are
    unaffected. Per the "Unknown is not pass" invariant, an absent identity on either side blocks
    rather than defaulting to a pass.
    """
    current_state = (delivery_receipt.get("current_state") or "").strip().lower()
    if delivery_rank(current_state) < delivery_rank("merge-ready"):
        return True, _gate("commit_binding", True, "commit_binding_not_applicable",
                           "commit binding only applies at merge-ready or a higher delivery state")
    payload = delivery_receipt.get("source_payload") or {}
    expected_sha = (
        str((payload.get("merge") or {}).get("commit_sha") or "").strip()
        or str((payload.get("pr") or {}).get("head_sha") or "").strip()
    )
    if not expected_sha:
        return False, _gate("commit_binding", False, "commit_binding_sha_missing",
                            "delivery source payload has no head/commit sha to bind evidence against")
    quality_receipt = _load_json(run_dir / "quality-matrix.json") or {}
    quality_sha = str((quality_receipt.get("work_item") or {}).get("head_sha") or "").strip()
    if not quality_sha:
        return False, _gate("commit_binding", False, "quality_matrix_commit_unbound",
                            "quality-matrix receipt does not declare work_item.head_sha; cannot "
                            "prove the #283 evidence was gathered for this commit")
    if quality_sha != expected_sha:
        return False, _gate("commit_binding", False, "quality_matrix_commit_mismatch",
                            f"quality-matrix work_item.head_sha {quality_sha!r} does not match "
                            f"the delivery receipt sha {expected_sha!r}")
    merge_queue_receipt = _load_json(run_dir / "merge-queue-receipt.json")
    if merge_queue_receipt is not None:
        mq_sha = str(merge_queue_receipt.get("head_sha") or merge_queue_receipt.get("commit_sha") or "").strip()
        if mq_sha and mq_sha != expected_sha:
            return False, _gate("commit_binding", False, "merge_queue_commit_mismatch",
                                f"merge-queue receipt sha {mq_sha!r} does not match the delivery "
                                f"receipt sha {expected_sha!r}")
    return True, _gate("commit_binding", True, "commit_binding_verified",
                       f"quality-matrix and delivery evidence are bound to the same commit {expected_sha!r}")


def completion_receipt_path(run_dir: str) -> Path:
    return Path(run_dir) / "completion-receipt.json"


def persist_completion_receipt(payload: Dict[str, Any], loop_dir: str, run_dir: str = "") -> str:
    loop = Path(loop_dir)
    run = Path(run_dir) if run_dir else None
    challenge = _load_json(loop / "watcher_challenge.json") or {}
    watcher_state = _load_json(loop / "watcher_state.json") or {}
    anchor = _load_json(loop / "anchor.json") or {}
    manifest = _load_json(run / "manifest.json") if run else {}
    delivery = _load_json(run / "delivery-receipt.json") if run else {}
    execution_route = (delivery or {}).get("execution_route") or {}
    if not execution_route and run:
        execution_route = _load_json(run / "execution-route.json") or {}
    if execution_route and not verify_route_hash(execution_route):
        execution_route = {}
    out = {
        "schema": COMPLETION_SCHEMA,
        "ready": bool(payload.get("ready")),
        "verdict": payload.get("verdict", "DELIVERY_PENDING"),
        "reason_code": payload.get("reason_code", "oracle_incomplete"),
        "reason": payload.get("reason", "completion gates not satisfied"),
        "tag": payload.get("tag", "UNVERIFIED"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "loop_dir": str(loop),
        "run_dir": str(run) if run else "",
        "run_id": run.name if run else "",
        "source_binding": {
            "kind": str((manifest or {}).get("source_kind") or "local"),
            "identity": str((manifest or {}).get("issue_ref") or (manifest or {}).get("source")
                            or (manifest or {}).get("task_path") or ""),
            "digest": str((manifest or {}).get("source_snapshot_hash")
                          or (manifest or {}).get("task_contract_hash")
                          or (manifest or {}).get("collection_hash")
                          or (manifest or {}).get("diff_hash") or ""),
        },
        "delivery_target": manifest.get("delivery_target", ""),
        "delivery_state": delivery.get("current_state", ""),
        "execution_route": execution_route,
        "route_receipt_sha": execution_route.get("receipt_sha", ""),
        "challenge": challenge.get("challenge", ""),
        "goal_fp": challenge.get("goal_fp") or anchor.get("goal_fp") or "",
        "watcher_status": watcher_state.get("status", "UNVERIFIED"),
        "watcher_match": bool(watcher_state.get("match", False)),
        "coverage_threshold": payload.get("coverage_threshold"),
        "coverage_measured": payload.get("coverage_measured"),
        "gates": payload.get("gates", []),
    }
    if run:
        out["artifacts"] = {
            "manifest": str(run / "manifest.json"),
            "evidence_receipt": str(run / "evidence-receipt.json"),
            "delivery_receipt": str(run / "delivery-receipt.json"),
            "quality_matrix": str(run / "quality-matrix.json"),
        }
        path = completion_receipt_path(str(run))
    else:
        path = loop / "completion-receipt.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return str(path)


def evaluate_completion(loop_dir: str, run_dir: str = "", response_text: str = "",
                        flow_gap: str = "") -> Dict[str, Any]:
    loop = Path(loop_dir)
    gates: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "ready": False,
        "verdict": "DELIVERY_PENDING",
        "reason_code": "oracle_incomplete",
        "reason": "completion gates not satisfied",
        "tag": "UNVERIFIED",
        "gates": gates,
    }

    scratchpad_path = loop / "scratchpad.md"
    if not scratchpad_path.exists():
        result["reason_code"] = "scratchpad_missing"
        result["reason"] = "scratchpad.md is missing"
        gates.append(_gate("scratchpad", False, "scratchpad_missing", "scratchpad.md is missing"))
        return result
    meta, _body = _parse_frontmatter(scratchpad_path.read_text(encoding="utf-8"))
    if meta is None:
        result["reason_code"] = "scratchpad_corrupt"
        result["reason"] = "scratchpad frontmatter is unreadable"
        gates.append(_gate("scratchpad", False, "scratchpad_corrupt", "scratchpad frontmatter is unreadable"))
        return result
    gates.append(_gate("scratchpad", True, "scratchpad_loaded", "scratchpad frontmatter loaded"))

    promise = (meta.get("completion_promise") or "").strip()
    if not promise or promise == "null":
        result["reason_code"] = "promise_missing"
        result["reason"] = "completion_promise is not configured"
        gates.append(_gate("promise", False, "promise_missing", "completion_promise is not configured"))
        return result

    resp = _read_response(loop, response_text)
    match = PROMISE_RE.search(resp or "")
    if not match or match.group(1).strip() != promise:
        result["reason_code"] = "promise_not_exact"
        result["reason"] = "exact completion promise not present in the active response"
        gates.append(_gate("promise", False, "promise_not_exact", "active response does not contain the exact completion promise"))
        return result
    gates.append(_gate("promise", True, "promise_exact", "active response contains the exact completion promise"))

    anchor_ok, anchor_gate, _anchor = _anchor_gate(loop)
    gates.append(anchor_gate)
    if not anchor_ok:
        result["reason_code"] = anchor_gate["reason_code"]
        result["reason"] = anchor_gate["detail"]
        return result

    watcher_ok, watcher_gate = _watcher_gate(loop)
    gates.append(watcher_gate)
    if not watcher_ok:
        result["reason_code"] = watcher_gate["reason_code"]
        result["reason"] = watcher_gate["detail"]
        return result

    if flow_gap:
        gates.append(_gate("flow_audit", False, "flow_audit_required", flow_gap))
        result["reason_code"] = "flow_audit_required"
        result["reason"] = flow_gap
        return result
    gates.append(_gate("flow_audit", True, "flow_audit_clear", "no flow-audit gap is open"))

    if not run_dir:
        gates.append(_gate("run_artifacts", False, "run_dir_missing", "run directory was not provided"))
        result["reason_code"] = "run_dir_missing"
        result["reason"] = "run directory was not provided"
        return result

    run_ok, artifact_gates, _loaded = _run_artifacts_gate(Path(run_dir))
    gates.extend(artifact_gates)
    if not run_ok:
        last_fail = next((gate for gate in reversed(artifact_gates) if gate["status"] == "fail"), artifact_gates[-1])
        result["reason_code"] = last_fail["reason_code"]
        result["reason"] = last_fail["detail"]
        return result

    dispatch_ok, dispatch_gate = _task_dispatch_gate(Path(run_dir))
    gates.append(dispatch_gate)
    if not dispatch_ok:
        result["reason_code"] = dispatch_gate["reason_code"]
        result["reason"] = dispatch_gate["detail"]
        return result

    quality_ok, quality_gate, quality_verdict = _quality_matrix_gate(Path(run_dir))
    gates.append(quality_gate)
    result["coverage_threshold"] = quality_verdict.get("coverage_threshold")
    result["coverage_measured"] = quality_verdict.get("coverage_measured")
    if not quality_ok:
        result["reason_code"] = quality_gate["reason_code"]
        result["reason"] = quality_gate["detail"]
        return result

    delivery_receipt = _loaded.get("delivery_receipt") if _loaded else None
    binding_ok, binding_gate = _commit_binding_gate(Path(run_dir), delivery_receipt or {})
    gates.append(binding_gate)
    if not binding_ok:
        result["reason_code"] = binding_gate["reason_code"]
        result["reason"] = binding_gate["detail"]
        return result

    lifecycle_ok, lifecycle_gate = _source_lifecycle_gate(Path(run_dir))
    gates.append(lifecycle_gate)
    if not lifecycle_ok:
        result["reason_code"] = lifecycle_gate["reason_code"]
        result["reason"] = lifecycle_gate["detail"]
        return result

    result.update({
        "ready": True,
        "verdict": "COMPLETE",
        "reason_code": "completion_verified",
        "reason": "oracle verified promise, anchor, watcher, flow gate and run artifacts",
        "tag": "MEASURED",
    })
    return result


def evaluate_matrix(loop_dir: str, run_dir: str, response_text: str = "",
                    flow_gap: str = "") -> Dict[str, Any]:
    """Evaluate the same completion oracle for every supported host adapter.

    Adapters are deliberately data-only here: hooks transport events, while this
    function owns the verdict.  A parity failure is therefore a real contract
    failure rather than six adapters each making a best-effort decision.
    """
    rows = []
    for adapter in ADAPTERS:
        result = evaluate_completion(loop_dir, run_dir, response_text=response_text,
                                     flow_gap=flow_gap)
        rows.append({
            "adapter": adapter,
            "ready": bool(result.get("ready")),
            "verdict": result.get("verdict", "DELIVERY_PENDING"),
            "reason_code": result.get("reason_code", "oracle_incomplete"),
            "tag": result.get("tag", "UNVERIFIED"),
        })
    signatures = {(row["ready"], row["verdict"], row["reason_code"], row["tag"])
                  for row in rows}
    signature = list(next(iter(signatures))) if len(signatures) == 1 else None
    return {
        "schema": ORACLE_MATRIX_SCHEMA,
        "adapters": rows,
        "parity": len(signatures) == 1,
        "signature": signature,
    }
