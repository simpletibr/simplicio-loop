"""Plugin v1 partial edit/test reconciliation with fail-closed UX.

Dev CLI inspects its own artifacts and proposes reconciliation evidence.
Runtime decides authority and persists the canonical receipt. This module
never resets, stashes, or checks out user work and never retries an
ambiguous effect.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .observability import emit_data
from .token_primitives import sha256_text

EVIDENCE_SCHEMA = "simplicio.plugin.dev-reconciliation-evidence/v1"
CRASH_MARKER_SCHEMA = "simplicio.plugin.dev-crash-marker/v1"
OpState = Literal["not_applied", "applied", "partial", "ambiguous"]
Action = Literal["inspect", "resume", "rollback", "no_retry"]

FORBIDDEN_GIT = ("git reset", "git stash", "git checkout", "git restore")


class PluginReconcileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class OperationEvidence:
    index: int
    path: str
    state: OpState
    before_sha256: str | None
    expected_sha256: str | None
    actual_sha256: str | None
    reason_code: str


def inspect_partial_attempt(
    *,
    root: str | Path,
    attempt_id: str,
    lease_id: str,
    plan: dict[str, Any],
    previous_receipt: dict[str, Any] | None = None,
    journal: Sequence[dict[str, Any]] | None = None,
    tests: dict[str, Any] | None = None,
    crash_before: bool = False,
) -> dict[str, Any]:
    """Classify each planned operation and recommend a non-destructive next action."""
    root_path = Path(root)
    operations = plan.get("operations") if isinstance(plan.get("operations"), list) else []
    journal_rows = list(journal or [])
    evidence = [
        _classify_operation(root_path, index, operation, journal_rows, previous_receipt)
        for index, operation in enumerate(operations)
        if isinstance(operation, dict)
    ]
    if crash_before and evidence:
        evidence = [
            OperationEvidence(
                item.index,
                item.path,
                "not_applied",
                item.before_sha256,
                item.expected_sha256,
                item.actual_sha256,
                "CRASH_BEFORE_EDIT",
            )
            for item in evidence
        ]
    user_changed = [item for item in evidence if item.state == "ambiguous"]
    applied = [item for item in evidence if item.state == "applied"]
    remaining = [operations[item.index] for item in evidence if item.state in {"not_applied", "partial"}]
    action, reason = _recommend(evidence, tests)
    rollback = _rollback_plan(evidence)
    if action == "inspect" and reason == "APPLIED" and rollback:
        action, reason = "rollback", "APPLIED_REVERSIBLE"
    validation_delta = _validation_delta(tests)
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "attempt_id": attempt_id,
        "lease_id": lease_id,
        "recommended_action": action,
        "reason_code": reason,
        "operations": [_operation_dict(item) for item in evidence],
        "remaining_operations": remaining,
        "residual_write_set": sorted({item.path for item in evidence if item.state != "applied"}),
        "user_changes_detected": bool(user_changed),
        "applied_indexes": [item.index for item in applied],
        "rollback_plan": rollback,
        "validation_delta": validation_delta,
        "git_mutations": [],
        "forbidden_git": list(FORBIDDEN_GIT),
        "crash_marker": _crash_marker_path(root_path, attempt_id).as_posix(),
        "resume_safe": action == "resume",
        "rollback_safe": action == "rollback",
        "next_action": _human_next(action, reason, remaining, validation_delta),
    }
    return payload


def write_crash_marker(root: str | Path, attempt_id: str, payload: dict[str, Any]) -> Path:
    path = _crash_marker_path(Path(root), attempt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "schema": CRASH_MARKER_SCHEMA,
        "attempt_id": attempt_id,
        "payload": payload,
    }
    path.write_text(json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def clear_crash_marker(root: str | Path, attempt_id: str) -> None:
    path = _crash_marker_path(Path(root), attempt_id)
    if path.is_file():
        path.unlink()


def resume_dry_run(evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("recommended_action") != "resume":
        raise PluginReconcileError(
            evidence.get("reason_code") or "RESUME_UNSAFE",
            "ambiguous or user-modified work cannot be resumed",
        )
    remaining = evidence.get("remaining_operations") or []
    return {
        "schema": "simplicio.plugin.dev-resume-dry-run/v1",
        "status": "ok",
        "idempotent": True,
        "operations": remaining,
        "repeats_applied": False,
        "git_mutations": [],
    }


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-py plugin-reconcile")
    parser.add_argument("mode", choices=["inspect", "reconcile", "resume"])
    parser.add_argument("--root", default=".")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--receipt")
    parser.add_argument("--journal")
    parser.add_argument("--tests")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8")) if args.receipt else None
    journal = json.loads(Path(args.journal).read_text(encoding="utf-8")) if args.journal else None
    tests = json.loads(Path(args.tests).read_text(encoding="utf-8")) if args.tests else None
    evidence = inspect_partial_attempt(
        root=args.root,
        attempt_id=args.attempt_id,
        lease_id=args.lease_id,
        plan=plan,
        previous_receipt=receipt,
        journal=journal,
        tests=tests,
    )
    if args.mode == "resume":
        payload = resume_dry_run(evidence)
    else:
        payload = evidence
    if args.json:
        emit_data(payload)
    else:
        emit_data(_human(payload))
    return 0 if payload.get("status", "ok") != "error" else 1


def _classify_operation(
    root: Path,
    index: int,
    operation: dict[str, Any],
    journal: list[dict[str, Any]],
    previous_receipt: dict[str, Any] | None,
) -> OperationEvidence:
    path = str(operation.get("path") or "")
    actual = _file_digest(root / path) if path else None
    before = _lookup_hash(previous_receipt, path, "before_sha256") or _journal_hash(
        journal, index, "before_sha256"
    )
    expected = _lookup_hash(previous_receipt, path, "after_sha256") or _journal_hash(
        journal, index, "after_sha256"
    )
    journal_state = _journal_state(journal, index)
    if journal_state == "applied" and expected and actual == expected:
        return OperationEvidence(index, path, "applied", before, expected, actual, "APPLIED")
    if journal_state == "not_applied" and (before is None or actual == before):
        return OperationEvidence(index, path, "not_applied", before, expected, actual, "NOT_APPLIED")
    if expected and actual == expected:
        return OperationEvidence(index, path, "applied", before, expected, actual, "APPLIED")
    if before is not None and actual == before:
        return OperationEvidence(index, path, "not_applied", before, expected, actual, "NOT_APPLIED")
    if journal_state == "partial":
        return OperationEvidence(index, path, "partial", before, expected, actual, "PARTIAL_APPLY")
    if before is not None and expected is not None and actual not in {before, expected}:
        return OperationEvidence(index, path, "ambiguous", before, expected, actual, "USER_MUTATION_DETECTED")
    if actual is None and before is not None:
        return OperationEvidence(index, path, "partial", before, expected, actual, "PARTIAL_APPLY")
    return OperationEvidence(index, path, "ambiguous", before, expected, actual, "EFFECT_UNKNOWN")


def _recommend(evidence: Sequence[OperationEvidence], tests: dict[str, Any] | None) -> tuple[Action, str]:
    if any(item.state == "ambiguous" for item in evidence):
        return "no_retry", "USER_MUTATION_DETECTED"
    if tests and tests.get("status") in {"timeout", "killed", "started"}:
        reason = {
            "timeout": "TEST_TIMEOUT",
            "killed": "TEST_KILLED",
            "started": "TEST_STARTED",
        }[str(tests["status"])]
        if any(item.state in {"not_applied", "partial"} for item in evidence):
            return "inspect", reason
        return "inspect", reason
    if tests and tests.get("status") == "stale":
        return "inspect", "TEST_STALE"
    if any(item.state in {"not_applied", "partial"} for item in evidence) and all(
        item.state != "ambiguous" for item in evidence
    ):
        if any(item.state == "applied" for item in evidence):
            return "resume", "PARTIAL_APPLY"
        return "resume", "NOT_APPLIED"
    if evidence and all(item.state == "applied" for item in evidence):
        return "inspect", "APPLIED"
    return "inspect", "EFFECT_UNKNOWN"


def _rollback_plan(evidence: Sequence[OperationEvidence]) -> dict[str, Any] | None:
    if any(item.state == "ambiguous" for item in evidence):
        return None
    reversible = [item for item in evidence if item.state == "applied" and item.before_sha256]
    if not reversible:
        return None
    return {
        "safe": True,
        "operations": [
            {
                "op": "restore_bytes",
                "path": item.path,
                "sha256": item.before_sha256,
            }
            for item in reversible
        ],
        "git_mutations": [],
    }


def _validation_delta(tests: dict[str, Any] | None) -> dict[str, Any]:
    if not tests:
        return {"unrun": [], "stale": [], "failed": []}
    status = str(tests.get("status") or "")
    commands = list(tests.get("commands") or [])
    if status in {"started", "timeout", "killed"}:
        return {"unrun": commands, "stale": [], "failed": []}
    if status == "stale":
        return {"unrun": [], "stale": commands, "failed": []}
    if status == "failed":
        return {"unrun": [], "stale": [], "failed": commands}
    return {"unrun": [], "stale": [], "failed": []}


def _human_next(
    action: Action,
    reason: str,
    remaining: list[dict[str, Any]],
    validation_delta: dict[str, Any],
) -> str:
    if action == "no_retry":
        return f"inspect residual files; do not retry ({reason})"
    if action == "resume":
        return f"resume {len(remaining)} remaining operation(s) without repeating applied edits"
    if action == "rollback":
        return "rollback applied operations using stored before hashes; do not git reset"
    stale = validation_delta.get("stale") or validation_delta.get("unrun") or []
    if stale:
        return f"re-run {len(stale)} stale or unrun validation command(s)"
    return f"inspect attempt ({reason})"


def _human(payload: dict[str, Any]) -> str:
    lines = [
        f"plugin-reconcile: {payload.get('recommended_action')} ({payload.get('reason_code')})",
        f"next: {payload.get('next_action')}",
        f"residual: {', '.join(payload.get('residual_write_set') or []) or '(none)'}",
    ]
    return "\n".join(lines) + "\n"


def _operation_dict(item: OperationEvidence) -> dict[str, Any]:
    return {
        "index": item.index,
        "path": item.path,
        "state": item.state,
        "before_sha256": item.before_sha256,
        "expected_sha256": item.expected_sha256,
        "actual_sha256": item.actual_sha256,
        "reason_code": item.reason_code,
    }


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_text(path.read_bytes())


def _lookup_hash(receipt: dict[str, Any] | None, path: str, key: str) -> str | None:
    if not receipt:
        return None
    for row in receipt.get("files") or []:
        if isinstance(row, dict) and row.get("path") == path and isinstance(row.get(key), str):
            return row[key]
    return None


def _journal_hash(journal: Sequence[dict[str, Any]], index: int, key: str) -> str | None:
    for row in journal:
        if row.get("index") == index and isinstance(row.get(key), str):
            return row[key]
    return None


def _journal_state(journal: Sequence[dict[str, Any]], index: int) -> str | None:
    for row in journal:
        if row.get("index") == index and isinstance(row.get("state"), str):
            return row["state"]
    return None


def _crash_marker_path(root: Path, attempt_id: str) -> Path:
    return root / ".simplicio" / "plugin-reconcile" / f"{attempt_id}.crash.json"


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
