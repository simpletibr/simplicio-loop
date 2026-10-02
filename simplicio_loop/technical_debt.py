"""Durable, non-blocking technical-debt notices for simplicio-loop.

Technical debt is an observable capability degradation, not proof of task completion.
This module deliberately keeps the safety boundary explicit: callers must opt into
blocking=False (or use one of the allow-listed degradation codes). Unknown
failures are never silently downgraded.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from . import dashboard_events

SCHEMA = "simplicio.technical-debt/v1"
STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED")
SEVERITIES = ("low", "medium", "high")

NON_BLOCKING_REASON_CODES = frozenset({
    "fanout_disabled",
    "fanout_adapter_unavailable",
    "fanout_serial_fallback",
    "not_git_checkout",
    "missing_plan_targets",
    "overlapping_task_impacts",
    "worktree_adapter_unavailable",
    "worktree_preflight_failed",
    "optional_capability_unavailable",
    "telemetry_degraded",
    "reporting_degraded",
    "quarantined_item",
})

HARD_BLOCKER_REASON_CODES = frozenset({
    "hard_constraint_violation",
    "budget_exhausted",
    "source_drift",
    "mutation_authority_invalid",
    "planning_not_ready",
    "stale_fence",
    "invalid_receipt",
    "receipt_invalid",
    "privacy_violation",
    "unauthorized",
    "safety_violation",
    "mandatory_quality_failed",
    "network_paused",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(*, reason_code: str, stage: str, source: str,
                 work_item_id: str = "", scope: str = "") -> str:
    payload = "|".join((reason_code.strip(), stage.strip(), source.strip(),
                        work_item_id.strip(), scope.strip()))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def is_hard_blocker(reason_code: str) -> bool:
    return str(reason_code or "").strip() in HARD_BLOCKER_REASON_CODES


def is_non_blocking_reason(reason_code: str) -> bool:
    return str(reason_code or "").strip() in NON_BLOCKING_REASON_CODES


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read_index(root: Path) -> Dict[str, Dict[str, Any]]:
    path = root / "technical-debt.json"
    raw: Any = None
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = None
    if isinstance(raw, Mapping):
        return {str(key): dict(value) for key, value in raw.items()
                if isinstance(value, Mapping)}
    # The JSONL ledger is the replay authority if the compact index is missing
    # or corrupt (for example after an interrupted atomic replace).
    ledger = root / "technical-debt.jsonl"
    recovered: Dict[str, Dict[str, Any]] = {}
    if ledger.is_file():
        try:
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(item, Mapping) and item.get("fingerprint"):
                    recovered[str(item["fingerprint"])] = dict(item)
        except OSError:
            pass
    return recovered


def _append_observation(root: Path, notice: Mapping[str, Any]) -> None:
    path = root / "technical-debt.jsonl"
    root.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(notice), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def build_notice(*, run_id: str, reason_code: str, stage: str, source: str,
                 message: str, next_action: str, work_item_id: str = "",
                 severity: str = "medium", scope: str = "run",
                 receipt: str = "", blocking: bool = False,
                 observed_at: Optional[str] = None) -> Dict[str, Any]:
    """Build one validated non-blocking notice."""
    code = str(reason_code or "").strip()
    if not code:
        raise ValueError("technical-debt reason_code is required")
    if is_hard_blocker(code):
        raise ValueError("hard-blocker reason cannot be recorded as technical debt: " + code)
    if blocking:
        raise ValueError("technical-debt notices must have blocking=False")
    if severity not in SEVERITIES:
        raise ValueError("severity must be one of " + ", ".join(SEVERITIES))
    fp = fingerprint(reason_code=code, stage=stage, source=source,
                     work_item_id=work_item_id, scope=scope)
    timestamp = str(observed_at or _now())
    return {
        "schema": SCHEMA,
        "debt_id": "debt-" + fp[:16],
        "fingerprint": fp,
        "run_id": str(run_id or ""),
        "work_item_id": str(work_item_id or ""),
        "scope": str(scope or "run"),
        "stage": str(stage or ""),
        "source": str(source or ""),
        "reason_code": code,
        "severity": severity,
        "message": str(message or ""),
        "next_action": str(next_action or ""),
        "blocking": False,
        "status": "OPEN",
        "receipt": str(receipt or ""),
        "first_seen": timestamp,
        "last_seen": timestamp,
        "occurrences": 1,
    }


def record_notice(run_dir: str | Path, *, run_id: str, reason_code: str, stage: str,
                  source: str, message: str, next_action: str,
                  work_item_id: str = "", severity: str = "medium",
                  scope: str = "run", receipt: str = "") -> Dict[str, Any]:
    """Persist and deduplicate one observation, updating state/progress if present."""
    root = Path(run_dir)
    notice = build_notice(
        run_id=run_id, reason_code=reason_code, stage=stage, source=source,
        message=message, next_action=next_action, work_item_id=work_item_id,
        severity=severity, scope=scope, receipt=receipt,
    )
    index = _read_index(root)
    previous = index.get(notice["fingerprint"])
    if previous:
        notice = dict(previous)
        notice["last_seen"] = _now()
        notice["occurrences"] = int(previous.get("occurrences") or 1) + 1
        notice["status"] = previous.get("status") if previous.get("status") in STATUSES else "OPEN"
        notice["message"] = str(message or previous.get("message") or "")
        notice["next_action"] = str(next_action or previous.get("next_action") or "")
    index[notice["fingerprint"]] = notice
    _append_observation(root, notice)
    _atomic_json(root / "technical-debt.json", index)

    state_path = root / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            state = {}
        debts = [dict(item) for item in state.get("technical_debts") or []
                 if isinstance(item, Mapping) and item.get("fingerprint") != notice["fingerprint"]]
        debts.append(notice)
        state["technical_debts"] = debts
        if state.get("phase") != "blocked":
            state["degraded"] = True
        _atomic_json(state_path, state)
        event = {
            "schema": "simplicio.progress/v1",
            "kind": "technical_debt",
            "phase": state.get("phase", "executing"),
            "run_id": str(run_id or state.get("run_id") or ""),
            "task_id": str(work_item_id or ""),
            "status": "DEBT",
            "reason_code": notice["reason_code"],
            "technical_debt": notice,
            "receipt": str(receipt or ""),
            "ts": _now(),
        }
        # #1398: the run's events.jsonl is the dashboard-event/v1 stream (fail-open).
        dashboard_events.emit_runner_event(root, state, event)
    return notice


def read_notices(run_dir: str | Path, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
    index = _read_index(Path(run_dir))
    notices = list(index.values())
    if status:
        notices = [item for item in notices if item.get("status") == status]
    return sorted(notices, key=lambda item: (str(item.get("first_seen") or ""), str(item.get("debt_id") or "")))


def summarize_notices(notices: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = [dict(item) for item in notices if isinstance(item, Mapping)]
    open_rows = [item for item in rows if item.get("status") in {"OPEN", "ACKNOWLEDGED"}]
    return {
        "count": len(rows),
        "open_count": len(open_rows),
        "blocking_count": sum(1 for item in rows if item.get("blocking") is True),
        "by_severity": {
            severity: sum(1 for item in open_rows if item.get("severity") == severity)
            for severity in SEVERITIES
        },
        "notices": rows,
    }


__all__ = [
    "HARD_BLOCKER_REASON_CODES", "NON_BLOCKING_REASON_CODES", "SCHEMA", "SEVERITIES",
    "STATUSES", "build_notice", "fingerprint", "is_hard_blocker",
    "is_non_blocking_reason", "read_notices", "record_notice", "summarize_notices",
]
