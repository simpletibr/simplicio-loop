"""Escalation ladder: retry execution failures, escalate to coordination, then planning.

When a task fails during execution, the ladder retries once in the same role.
If it still fails, it escalates to coordination, then to planning, then stops.

Each escalation step records the role, model, effort used, and tracks attempts
per issue and per day against a cost ceiling.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

from . import model_roles

# Escalation ladder: execution -> coordination -> planning -> stop
ESCALATION_LADDER = ("execution", "coordination", "planning")


class EscalationRecord:
    """Record of one escalation step in the ladder."""

    def __init__(
        self,
        step: int,
        role: str,
        family: str,
        model: str,
        effort: str,
        attempt: int,
        outcome: str,  # ok, failed, timeout, etc.
        error: Optional[str] = None,
        execution_ms: float = 0.0,
    ):
        self.step = step  # 0, 1, 2 for execution, coordination, planning
        self.role = role
        self.family = family
        self.model = model
        self.effort = effort
        self.attempt = attempt  # attempt number within this step
        self.outcome = outcome
        self.error = error
        self.execution_ms = execution_ms
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "role": self.role,
            "family": self.family,
            "model": self.model,
            "effort": self.effort,
            "attempt": self.attempt,
            "outcome": self.outcome,
            "error": self.error,
            "execution_ms": self.execution_ms,
            "timestamp": self.timestamp,
        }


class EscalationState:
    """State tracker for escalation ladder."""

    def __init__(
        self,
        repo: Path,
        issue: int,
        family: str,
        cost_ceiling_per_issue: Optional[int] = None,
        cost_ceiling_per_day: Optional[int] = None,
    ):
        self.repo = Path(repo)
        self.issue = issue
        self.family = family
        self.cost_ceiling_per_issue = cost_ceiling_per_issue or 1000  # arbitrary units
        self.cost_ceiling_per_day = cost_ceiling_per_day or 5000
        self.records: list[EscalationRecord] = []
        self.current_step = 0  # 0 = execution, 1 = coordination, 2 = planning
        self.attempts_in_step = 0
        self._cost_per_role = {"execution": 10, "coordination": 50, "planning": 100}
        self._state_file = self._get_state_file()
        self._load_state()

    def _get_state_file(self) -> Path:
        """Get the escalation state file path."""
        d = self.repo / ".simplicio-loop" / "escalation-states"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"issue-{self.issue}.json"

    def _load_state(self) -> None:
        """Load saved escalation state from disk."""
        if not self._state_file.is_file():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self.current_step = data.get("current_step", 0)
            self.attempts_in_step = data.get("attempts_in_step", 0)
            records_data = data.get("records", [])
            for rec in records_data:
                self.records.append(
                    EscalationRecord(
                        step=rec["step"],
                        role=rec["role"],
                        family=rec["family"],
                        model=rec["model"],
                        effort=rec["effort"],
                        attempt=rec["attempt"],
                        outcome=rec["outcome"],
                        error=rec.get("error"),
                        execution_ms=rec.get("execution_ms", 0.0),
                    )
                )
        except (json.JSONDecodeError, ValueError, KeyError):
            pass

    def _save_state(self) -> None:
        """Save escalation state to disk."""
        data = {
            "issue": self.issue,
            "family": self.family,
            "current_step": self.current_step,
            "attempts_in_step": self.attempts_in_step,
            "records": [r.to_dict() for r in self.records],
        }
        self._state_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _get_cost_used_today(self) -> int:
        """Calculate cost used today across all issues."""
        today = datetime.utcnow().date()
        cost = 0
        for record in self.records:
            try:
                ts = datetime.fromisoformat(record.timestamp)
                if ts.date() == today:
                    cost += self._cost_per_role.get(record.role, 10)
            except (ValueError, AttributeError):
                pass
        return cost

    def _get_cost_used_for_issue(self) -> int:
        """Calculate cost used for this issue."""
        cost = 0
        for record in self.records:
            cost += self._cost_per_role.get(record.role, 10)
        return cost

    def can_escalate(self) -> bool:
        """Check if we can escalate (cost ceilings not exceeded)."""
        cost_today = self._get_cost_used_today()
        cost_issue = self._get_cost_used_for_issue()

        if cost_today >= self.cost_ceiling_per_day:
            return False
        if cost_issue >= self.cost_ceiling_per_issue:
            return False

        return True

    def current_role(self) -> str:
        """Get the current role in the ladder."""
        if self.current_step >= len(ESCALATION_LADDER):
            return ESCALATION_LADDER[-1]
        return ESCALATION_LADDER[self.current_step]

    def record_attempt(
        self,
        outcome: str,
        error: Optional[str] = None,
        execution_ms: float = 0.0,
    ) -> EscalationRecord:
        """Record an attempt in the current role."""
        role = self.current_role()
        try:
            resolved = model_roles.resolve(self.family, role)
            model = resolved["model"]
            effort = resolved["effort"]
        except model_roles.ModelRoleError:
            model = ""
            effort = ""

        record = EscalationRecord(
            step=self.current_step,
            role=role,
            family=self.family,
            model=model,
            effort=effort,
            attempt=self.attempts_in_step + 1,
            outcome=outcome,
            error=error,
            execution_ms=execution_ms,
        )
        self.records.append(record)
        self.attempts_in_step += 1
        self._save_state()
        return record

    def next_step(self) -> bool:
        """Move to the next step in the ladder.

        Returns:
            True if moved to a new step, False if at the end
        """
        if not self.can_escalate():
            return False

        if self.current_step >= len(ESCALATION_LADDER) - 1:
            return False

        self.current_step += 1
        self.attempts_in_step = 0
        self._save_state()
        return True

    def has_reached_end(self) -> bool:
        """Check if we've reached the end of the ladder."""
        return self.current_step >= len(ESCALATION_LADDER) - 1

    def to_dict(self) -> dict[str, Any]:
        """Export the full escalation state."""
        return {
            "issue": self.issue,
            "family": self.family,
            "current_step": self.current_step,
            "current_role": self.current_role(),
            "attempts_in_step": self.attempts_in_step,
            "cost_used_for_issue": self._get_cost_used_for_issue(),
            "cost_used_today": self._get_cost_used_today(),
            "cost_ceiling_per_issue": self.cost_ceiling_per_issue,
            "cost_ceiling_per_day": self.cost_ceiling_per_day,
            "records": [r.to_dict() for r in self.records],
        }


def load_escalation_state(
    repo: Path,
    issue: int,
    family: str,
    cost_ceiling_per_issue: Optional[int] = None,
    cost_ceiling_per_day: Optional[int] = None,
) -> EscalationState:
    """Load or create an escalation state for an issue."""
    return EscalationState(
        repo,
        issue,
        family,
        cost_ceiling_per_issue=cost_ceiling_per_issue,
        cost_ceiling_per_day=cost_ceiling_per_day,
    )
