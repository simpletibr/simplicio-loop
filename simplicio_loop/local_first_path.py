"""One bounded local-first task path across Mapper receipt, Fast and Dev CLI."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .fast_integration import FastLoopIntegration
from .fast_task_bridge import FastTaskBinding, FastTaskBridge

SCHEMA = "simplicio.loop.local-first-task-path/v1"


class LocalFirstPathError(RuntimeError):
    """The standalone local path cannot safely continue."""


@dataclass(frozen=True)
class LocalFirstTaskResult:
    task_id: str
    status: str
    binding: FastTaskBinding
    plan_receipt: Mapping[str, Any]
    apply_receipt: Mapping[str, Any] | None = None
    receipt_path: str = ""
    receipt_hash: str = ""
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "task_id": self.task_id, "status": self.status,
                "binding": self.binding.to_dict(), "plan_receipt": dict(self.plan_receipt),
                "apply_receipt": dict(self.apply_receipt or {}),
                "receipt_path": self.receipt_path, "receipt_hash": self.receipt_hash}


class LocalFirstTaskPath:
    """Orchestrate the existing Fast integration and public workspace binding."""

    def __init__(self, root: str, *, bridge: FastTaskBridge | None = None,
                 integration: FastLoopIntegration | None = None) -> None:
        self.root = Path(root).resolve()
        self.bridge = bridge or FastTaskBridge(root)
        self.integration = integration or FastLoopIntegration(root)

    def _persist_receipt(self, result: LocalFirstTaskResult) -> LocalFirstTaskResult:
        payload = result.to_dict()
        payload["receipt_path"] = ""
        payload["receipt_hash"] = ""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        receipt_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        directory = self.root / ".simplicio-loop" / "orchestrator" / "local-first"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{result.binding.attempt_id}-{result.task_id}.json"
        stored = dict(payload)
        stored["receipt_path"] = str(path)
        stored["receipt_hash"] = receipt_hash
        path.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return LocalFirstTaskResult(
            task_id=result.task_id, status=result.status, binding=result.binding,
            plan_receipt=result.plan_receipt, apply_receipt=result.apply_receipt,
            receipt_path=str(path), receipt_hash=receipt_hash,
        )

    def run(self, *, task_id: str, attempt_id: str, worktree_id: str, task: str,
            mapper_receipt: Mapping[str, Any], changeset: Mapping[str, Any] | None = None
            ) -> LocalFirstTaskResult:
        binding = self.bridge.prepare(task_id=task_id, attempt_id=attempt_id,
                                      worktree_id=worktree_id, mapper_receipt=mapper_receipt)
        try:
            plan = self.integration.prepare(task)
            if plan.get("status") != "READY":
                raise LocalFirstPathError(f"Fast plan did not become READY: {plan.get('reason', 'unknown')}")
            if changeset is None:
                return self._persist_receipt(LocalFirstTaskResult(task_id, "PLANNED", binding, plan))
            candidate = self.bridge.validate_changeset(binding, changeset)
            applied = self.integration.apply(candidate, winner=True,
                                              generation=binding.overlay_generation,
                                              context_hash=binding.mapper_context_hash)
            if str(applied.get("status") or "").upper() not in {"APPLIED", "READY", "MEASURED"}:
                raise LocalFirstPathError(f"Fast apply was not accepted: {applied.get('status', 'unknown')}")
            result = LocalFirstTaskResult(task_id, "APPLIED", binding, plan, applied)
            self.bridge.release(binding)
            return self._persist_receipt(result)
        except Exception:
            self.bridge.release(binding)
            raise


__all__ = ["SCHEMA", "LocalFirstPathError", "LocalFirstTaskPath", "LocalFirstTaskResult"]
