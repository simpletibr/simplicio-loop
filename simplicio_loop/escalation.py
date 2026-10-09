"""Escalation ladder: retry execution failures, escalate to coordination, then planning.

Cost is the MEASURED token total of each attempt's simplicio.execution-report/v1. An attempt without MEASURED tokens is
UNVERIFIED: it is never counted as zero tokens, and it is bounded by an attempt count instead. The attempt ceilings are
policy values, not measurements.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import model_roles
from .execution_report import SCHEMA as EXECUTION_REPORT_SCHEMA

ESCALATION_LADDER = ("execution", "coordination", "planning")
# Policy: once any attempt in a scope is UNVERIFIED, the scope may not exceed these attempt counts.
ATTEMPT_CEILING_PER_ISSUE = 6
ATTEMPT_CEILING_PER_DAY = 30


def measured_tokens(report: Optional[dict[str, Any]]) -> Optional[int]:
    """Total tokens of one attempt's execution report, or None (UNVERIFIED) unless every task has MEASURED tokens."""
    if not isinstance(report, dict) or report.get("schema") != EXECUTION_REPORT_SCHEMA:
        return None
    tasks = report.get("tasks") or []
    if not tasks:
        return None
    total = 0
    for task in tasks:
        tokens = task.get("tokens") or {}
        if tokens.get("source") != "cli_measured" or tokens.get("tokens_total") is None:
            return None
        total += int(tokens["tokens_total"])
    return total


class EscalationRecord:
    """Record of one escalation step in the ladder."""

    def __init__(self, step, role, family, model, effort, attempt, outcome, error=None, execution_ms=0.0, tokens=None):
        self.step = step
        self.role = role
        self.family = family
        self.model = model
        self.effort = effort
        self.attempt = attempt
        self.outcome = outcome
        self.error = error
        self.execution_ms = execution_ms
        self.tokens = tokens  # MEASURED total tokens, or None when UNVERIFIED
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
            "tokens": self.tokens,
            "timestamp": self.timestamp,
        }


class EscalationState:
    """State tracker for escalation ladder."""

    def __init__(
        self,
        repo,
        issue,
        family,
        token_ceiling_per_issue=None,
        token_ceiling_per_day=None,
        attempt_ceiling_per_issue=ATTEMPT_CEILING_PER_ISSUE,
        attempt_ceiling_per_day=ATTEMPT_CEILING_PER_DAY,
    ):
        self.repo = Path(repo)
        self.issue = issue
        self.family = family
        self.token_ceiling_per_issue = token_ceiling_per_issue
        self.token_ceiling_per_day = token_ceiling_per_day
        self.attempt_ceiling_per_issue = attempt_ceiling_per_issue
        self.attempt_ceiling_per_day = attempt_ceiling_per_day
        self.records = []
        self.current_step = 0
        self.attempts_in_step = 0
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
                        tokens=rec.get("tokens"),
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

    def _records_in_scope(self, today):
        if not today:
            return list(self.records)
        now = datetime.now(timezone.utc).date()
        in_scope = []
        for record in self.records:
            try:
                if datetime.fromisoformat(record.timestamp).date() == now:
                    in_scope.append(record)
            except (ValueError, AttributeError):
                pass
        return in_scope

    @staticmethod
    def _usage(records):
        """MEASURED tokens, count of UNVERIFIED attempts, and total attempts. UNVERIFIED adds no tokens."""
        return {
            "tokens": sum(r.tokens for r in records if r.tokens is not None),
            "unverified": sum(1 for r in records if r.tokens is None),
            "attempts": len(records),
        }

    def can_escalate(self):
        """False once a token ceiling is reached, or an attempt ceiling is reached while any attempt is UNVERIFIED."""
        for today in (False, True):
            usage = self._usage(self._records_in_scope(today))
            token_ceiling = self.token_ceiling_per_day if today else self.token_ceiling_per_issue
            attempt_ceiling = self.attempt_ceiling_per_day if today else self.attempt_ceiling_per_issue
            if token_ceiling is not None and usage["tokens"] >= token_ceiling:
                return False
            if usage["unverified"] and usage["attempts"] >= attempt_ceiling:
                return False
        return True

    def current_role(self):
        """Get the current role in the ladder."""
        if self.current_step >= len(ESCALATION_LADDER):
            return ESCALATION_LADDER[-1]
        return ESCALATION_LADDER[self.current_step]

    def record_attempt(self, outcome, error=None, execution_ms=0.0, report=None):
        """Record an attempt in the current role. ``report`` is that attempt's execution report, if any."""
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
            tokens=measured_tokens(report),
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
        issue_usage = self._usage(self._records_in_scope(False))
        today_usage = self._usage(self._records_in_scope(True))
        return {
            "issue": self.issue,
            "family": self.family,
            "current_step": self.current_step,
            "current_role": self.current_role(),
            "attempts_in_step": self.attempts_in_step,
            "tokens_used_for_issue": issue_usage["tokens"],
            "tokens_used_today": today_usage["tokens"],
            "unverified_attempts_for_issue": issue_usage["unverified"],
            "unverified_attempts_today": today_usage["unverified"],
            "token_ceiling_per_issue": self.token_ceiling_per_issue,
            "token_ceiling_per_day": self.token_ceiling_per_day,
            "attempt_ceiling_per_issue": self.attempt_ceiling_per_issue,
            "attempt_ceiling_per_day": self.attempt_ceiling_per_day,
            "records": [r.to_dict() for r in self.records],
        }


def load_escalation_state(
    repo,
    issue,
    family,
    token_ceiling_per_issue=None,
    token_ceiling_per_day=None,
    attempt_ceiling_per_issue=ATTEMPT_CEILING_PER_ISSUE,
    attempt_ceiling_per_day=ATTEMPT_CEILING_PER_DAY,
):
    """Load or create an escalation state for an issue."""
    return EscalationState(
        repo,
        issue,
        family,
        token_ceiling_per_issue=token_ceiling_per_issue,
        token_ceiling_per_day=token_ceiling_per_day,
        attempt_ceiling_per_issue=attempt_ceiling_per_issue,
        attempt_ceiling_per_day=attempt_ceiling_per_day,
    )
