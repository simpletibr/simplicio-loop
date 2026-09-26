"""PluginLoopDriver — host-neutral control facade over the existing Loop core.

This adapter does not execute writes. Runtime (when bound) owns effects and
receipts. The driver only returns continue/replan/pause/stop/refeed decisions.
Standalone mode is explicit and cannot prove an external effect.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.loop-control-decision/v1"
SESSION_SCHEMA = "simplicio.plugin-session/v1"
DECISIONS = ("continue", "replan", "pause", "stop", "refeed")
MODES = ("runtime-bound", "standalone")


class PluginLoopError(RuntimeError):
    """Invalid session, stale watcher, or missing bound receipt."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _digest(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class LoopControlDecision:
    action: str
    reason: str
    mode: str
    iteration: int
    goal_digest: str
    refeed_delta: str = ""
    can_prove_external_effect: bool = False
    completion_ready: bool = False
    schema: str = SCHEMA
    decided_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["action"] not in DECISIONS:
            raise PluginLoopError("unknown control action")
        return payload


class PluginLoopDriver:
    """start/tick/observe/stop/resume/handoff over frozen goal + receipts."""

    def __init__(self, root: str | Path, *, mode: str = "standalone") -> None:
        if mode not in MODES:
            raise PluginLoopError("mode must be runtime-bound or standalone")
        self.root = Path(root).resolve()
        self.mode = mode
        self.goal = ""
        self.goal_digest = ""
        self.iteration = 0
        self.max_iterations = 8
        self.cancelled = False
        self.receipts: list[dict[str, Any]] = []
        self.journal: list[dict[str, Any]] = []
        self.watcher: dict[str, Any] = {"fresh": True, "tampered": False}
        self.state_path = self.root / ".simplicio-loop" / "plugin-runtime" / "session.json"

    def start(self, session: Mapping[str, Any]) -> dict[str, Any]:
        goal = str(session.get("goal") or "").strip()
        if not goal:
            raise PluginLoopError("plugin session requires a frozen goal")
        self.goal = goal
        self.goal_digest = _digest(goal)
        self.max_iterations = int(session.get("max_iterations") or 8)
        self.iteration = 0
        self.cancelled = False
        self.receipts = []
        self.journal = [{"kind": "start", "at": _now(), "goal_digest": self.goal_digest}]
        return self._persist({
            "schema": SESSION_SCHEMA,
            "mode": self.mode,
            "goal": self.goal,
            "goal_digest": self.goal_digest,
            "iteration": self.iteration,
            "status": "started",
            "can_prove_external_effect": self.mode == "runtime-bound",
        })

    def tick(self) -> LoopControlDecision:
        if self.cancelled:
            return self._decide("pause", "cancelled")
        if not self.goal_digest:
            raise PluginLoopError("driver has no started session")
        self.iteration += 1
        self.journal.append({"kind": "tick", "iteration": self.iteration, "at": _now()})
        if self.iteration > self.max_iterations:
            return self._decide("stop", "max_iterations")
        if self._completion_ready():
            return self._decide("stop", "evidence_and_watcher_gated", completion_ready=True)
        if self._latest_receipt_status() == "ambiguous":
            return self._decide("refeed", "receipt_ambiguous_keeps_criteria_pending")
        if self._latest_receipt_status() == "failed":
            return self._decide("replan", "receipt_failed")
        return self._decide("continue", "iterate")

    def observe(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(receipt)
        status = str(payload.get("status") or "").strip().lower()
        if not status:
            payload["status"] = "missing"
            status = "missing"
        if status in {"", "missing", "absent"} and self.mode == "runtime-bound":
            payload["status"] = "ambiguous"
            payload["reason"] = "missing_receipt_is_not_success"
        self.receipts.append(payload)
        self.journal.append({"kind": "observe", "status": payload["status"], "at": _now()})
        self._persist({"iteration": self.iteration, "receipts": self.receipts})
        return {"accepted": True, "status": payload["status"], "count": len(self.receipts)}

    def stop(self) -> LoopControlDecision:
        if self.watcher.get("tampered") or not self.watcher.get("fresh", True):
            return self._decide("refeed", "watcher_stale_or_tampered")
        if not self._completion_ready():
            return self._decide("refeed", "completion_not_evidence_gated")
        return self._decide("stop", "evidence_and_watcher_gated", completion_ready=True)

    def resume(self, snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = dict(snapshot or self._load())
        if data.get("goal_digest") and data["goal_digest"] != self.goal_digest and self.goal_digest:
            raise PluginLoopError("resume goal digest mismatch")
        self.goal = str(data.get("goal") or self.goal)
        self.goal_digest = str(data.get("goal_digest") or _digest(self.goal))
        self.iteration = int(data.get("iteration") or 0)
        self.receipts = list(data.get("receipts") or [])
        self.journal.append({"kind": "resume", "iteration": self.iteration, "at": _now()})
        return {
            "schema": SESSION_SCHEMA,
            "status": "resumed",
            "iteration": self.iteration,
            "goal_digest": self.goal_digest,
        }

    def handoff(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.plugin-handoff/v1",
            "goal_digest": self.goal_digest,
            "iteration": self.iteration,
            "mode": self.mode,
            "applies_effects": False,
            "journal": list(self.journal),
        }

    def cancel(self) -> None:
        self.cancelled = True

    def set_watcher(self, *, fresh: bool = True, tampered: bool = False) -> None:
        self.watcher = {"fresh": fresh, "tampered": tampered}

    def _completion_ready(self) -> bool:
        if self.watcher.get("tampered") or not self.watcher.get("fresh", True):
            return False
        if not self.receipts:
            return False
        latest = self.receipts[-1]
        status = str(latest.get("status") or "").lower()
        evidence = latest.get("evidence_complete")
        if status in {"missing", "absent", "ambiguous", "failed"}:
            return False
        return status == "measured" and evidence is True

    def _latest_receipt_status(self) -> str:
        if not self.receipts:
            return "absent"
        return str(self.receipts[-1].get("status") or "absent").lower()

    def _decide(self, action: str, reason: str, *, completion_ready: bool = False) -> LoopControlDecision:
        decision = LoopControlDecision(
            action=action,
            reason=reason,
            mode=self.mode,
            iteration=self.iteration,
            goal_digest=self.goal_digest,
            refeed_delta="pending-criteria" if action == "refeed" else "",
            can_prove_external_effect=self.mode == "runtime-bound" and action == "stop" and completion_ready,
            completion_ready=completion_ready,
        )
        self._persist({"last_decision": decision.to_dict(), "iteration": self.iteration})
        return decision

    def _persist(self, extra: Mapping[str, Any]) -> dict[str, Any]:
        payload = {
            "schema": SESSION_SCHEMA,
            "mode": self.mode,
            "goal": self.goal,
            "goal_digest": self.goal_digest,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "receipts": self.receipts,
            "journal": self.journal,
            "watcher": self.watcher,
        }
        payload.update(extra)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
