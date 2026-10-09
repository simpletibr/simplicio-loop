"""Escalation ladder: retry execution failures, escalate to coordination, then planning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import model_roles

ESCALATION_LADDER = ("execution", "coordination", "planning")


class EscalationRecord:
    """Record of one escalation step in the ladder."""

    def __init__(self, step, role, family, model, effort, attempt, outcome, error=None, execution_ms=0.0):
        self.step = step
        self.role = role
        self.family = family
        self.model = model
        self.effort = effort
        self.attempt = attempt
        self.outcome = outcome
        self.error = error
        self.execution_ms = execution_ms
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
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

    def __init__(self, repo, issue, family, cost_ceiling_per_issue=None, cost_ceiling_per_day=None):
        self.repo = Path(repo)
        self.issue = issue
        self.family = family
        self.cost_ceiling_per_issue = cost_ceiling_per_issue or 1000
        self.cost_ceiling_per_day = cost_ceiling_per_day or 5000
        self.records = []
        self.current_step = 0
        self.attempts_in_step = 0
        self._cost_per_role = {"execution": 10, "coordination": 50, "planning": 100}
        self._state_file = self._get_state_file()
        self._load_state()

    def _get_state_file(self):
        d = self.repo / ".simplicio-loop" / "escalation-states"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"issue-{self.issue}.json"

    def _load_state(self):
        if not self._state_file.is_file():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            self.current_step = data.get("current_step", 0)
            self.attempts_in_step = data.get("attempts_in_step", 0)
            for rec in data.get("records", []):
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

    def _save_state(self):
        data = {
            "issue": self.issue,
            "family": self.family,
            "current_step": self.current_step,
            "attempts_in_step": self.attempts_in_step,
            "records": [r.to_dict() for r in self.records],
        }
        self._state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _get_cost_used_today(self):
        today = datetime.now(timezone.utc).date()
        cost = 0
        for record in self.records:
            try:
                ts = datetime.fromisoformat(record.timestamp)
                if ts.date() == today:
                    cost += self._cost_per_role.get(record.role, 10)
            except (ValueError, AttributeError):
                pass
        return cost

    def _get_cost_used_for_issue(self):
        cost = 0
        for record in self.records:
            cost += self._cost_per_role.get(record.role, 10)
        return cost

    def can_escalate(self):
        """Check if we can escalate (cost ceilings not exceeded)."""
        cost_today = self._get_cost_used_today()
        cost_issue = self._get_cost_used_for_issue()

        if cost_today >= self.cost_ceiling_per_day:
            return False
        if cost_issue >= self.cost_ceiling_per_issue:
            return False

        return True

    def current_role(self):
        """Get the current role in the ladder."""
        if self.current_step >= len(ESCALATION_LADDER):
            return ESCALATION_LADDER[-1]
        return ESCALATION_LADDER[self.current_step]

    def record_attempt(self, outcome, error=None, execution_ms=0.0):
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

    def next_step(self):
        """Move to the next step in the ladder. Returns True if moved."""
        if not self.can_escalate():
            return False

        if self.current_step >= len(ESCALATION_LADDER) - 1:
            return False

        self.current_step += 1
        self.attempts_in_step = 0
        self._save_state()
        return True

    def has_reached_end(self):
        """Check if we've reached the end of the ladder."""
        return self.current_step >= len(ESCALATION_LADDER) - 1

    def to_dict(self):
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


def load_escalation_state(repo, issue, family, cost_ceiling_per_issue=None, cost_ceiling_per_day=None):
    """Load or create an escalation state for an issue."""
    return EscalationState(repo, issue, family, cost_ceiling_per_issue=cost_ceiling_per_issue, cost_ceiling_per_day=cost_ceiling_per_day)
