"""Thin, action-gated bridge for the native tasks pipeline."""
from __future__ import annotations

from pathlib import Path
import contextlib
import hashlib
import json
from typing import Any, Callable, Mapping

from .runner import dispatch_operator_batch
from .drain import _receipt_lock

SCHEMA = "simplicio.tasks-orchestrator/v1"

def _digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def _evidence_complete(rows: Any) -> bool:
    return bool(rows) and all(row.get("pr") and row.get("verification") for row in rows)

def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, sort_keys=True, default=str, indent=2), encoding="utf-8")
    pending.replace(path)

class TasksOrchestrator:
    """Join existing intake, dispatcher and stage/review/delivery coordinator."""

    def __init__(
        self,
        intake: Any,
        contract_factory: Callable[[Mapping[str, Any]], list[Mapping[str, Any]]],
        coordinate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        dispatch: Callable[..., Mapping[str, Any]] = dispatch_operator_batch,
        worktree_queue: Any = None,
        max_workers: int = 1,
        retry_budget: int = 1,
        journal_dir: str | None = None,
    ):
        self.intake = intake
        self.contract_factory = contract_factory
        self.dispatch = dispatch
        self.coordinate = coordinate
        self.max_workers = max(1, int(max_workers))
        self.retry_budget = max(0, int(retry_budget))
        self.journal_dir = journal_dir
        self.worktree_queue = worktree_queue
        self.idempotency_dir = Path(journal_dir).resolve().parent / "idempotency" if journal_dir else None

    def run(self, request: str, *, action_gate: bool = False, cancel: bool = False) -> dict[str, Any]:
        if cancel:
            cancel_all = getattr(self.coordinate, "cancel_all", None)
            cancelled = cancel_all(reason="cancel_requested") if cancel_all else []
            return {
                "schema": SCHEMA, "plan": None,
                "idempotency_key": _digest({"request": request}),
                "state": "cancelled", "reason": "cancel_requested",
                "cancelled": cancelled, "evidence": [],
            }
        plan = self.intake.run(request)
        identity = plan.get("run_identity", {})
        key = _digest(identity or plan.get("digests", {}))
        receipt = {"schema": SCHEMA, "plan": plan, "idempotency_key": key}
        outcome = plan.get("outcome", {})
        if outcome.get("status") != "PLANNED_NOT_EXECUTED":
            receipt.update(state="blocked", reason=outcome.get("reason_code", "intake_not_planned"), evidence=[])
            return receipt
        if not action_gate:
            receipt.update(state="partial", reason="action_gate_required", evidence=[])
            return receipt
        items = self.contract_factory(plan)
        if not items:
            receipt.update(state="blocked", reason="no_validated_loop_contracts", evidence=[])
            return receipt
        idempotency_path = self.idempotency_dir / f"{key}.json" if self.idempotency_dir else None
        requested = min(self.max_workers, len(items))
        lock = _receipt_lock(idempotency_path) if idempotency_path else contextlib.nullcontext()
        with lock:
            takeover = 0
            if idempotency_path and idempotency_path.exists():
                durable = json.loads(idempotency_path.read_text(encoding="utf-8"))
                if durable.get("idempotency_key") != key:
                    receipt.update(state="blocked", reason="idempotency_receipt_mismatch", evidence=[])
                    return receipt
                if durable.get("state") == "completed":
                    return durable
                if durable.get("state") != "dispatching":
                    receipt.update(state="blocked", reason="dispatch_receipt_invalid", evidence=[])
                    return receipt
                takeover = int(durable.get("admission_fence") or 1)
            if idempotency_path:
                admitted = dict(receipt)
                admitted.update(
                    state="dispatching",
                    reason="durable_takeover" if takeover else "durable_admission",
                    admission_fence=takeover + 1,
                    evidence=[],
                )
                _write_receipt(idempotency_path, admitted)
            admission_fence = takeover + 1
            fenced_items = [dict(item, admission_fence=admission_fence) for item in items]
            try:
                dispatched = self.dispatch(fenced_items, max_workers=requested, retry_budget=self.retry_budget, journal_dir=self.journal_dir, worktree_queue=self.worktree_queue)
                coordinated = self.coordinate(dispatched)
            except Exception as exc:
                if idempotency_path:
                    interrupted = dict(receipt)
                    interrupted.update(
                        state="dispatching", reason="dispatch_interrupted",
                        admission_fence=admission_fence,
                        error=f"{type(exc).__name__}: {exc}", evidence=[],
                    )
                    _write_receipt(idempotency_path, interrupted)
                raise
            evidence = coordinated.get("evidence", [])
            passed = bool(coordinated.get("passed")) and _evidence_complete(evidence)
            receipt.update(state="completed" if passed else "partial", reason="verified" if passed else "evidence_incomplete", dispatch=dispatched, evidence=evidence, review=coordinated, admission_fence=takeover + 1)
            if idempotency_path:
                _write_receipt(idempotency_path, receipt)
            return receipt
