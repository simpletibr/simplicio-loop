"""Plugin v1 Dev CLI adapter: consume EffectLease and emit correlated receipts.

Dev CLI plans, edits, and tests inside a Runtime-issued lease. It does not
authorize leases, own PR lifecycle, or declare convergence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mechanical_edit import execute_plan
from .observability import emit_data
from .token_primitives import sha256_text

LEASE_SCHEMA = "simplicio.plugin.effect-lease/v1"
INTENT_SCHEMA = "simplicio.plugin.task-intent/v1"
ROUTE_SCHEMA = "simplicio.plugin.route-decision/v1"
EFFECT_INTENT_SCHEMA = "simplicio.plugin.effect-intent/v1"
TOOL_RECEIPT_SCHEMA = "simplicio.plugin.tool-receipt/v1"
DEV_RECEIPT_SCHEMA = "simplicio.plugin.dev-execution-receipt/v1"

CancelCheck = Callable[[], bool]
Clock = Callable[[], float]
SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|authorization)=\S+")


class PluginLeaseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class EffectLease:
    lease_id: str
    effect_id: str
    ttl_ms: int
    fence: str
    repo: str
    worktree: str
    branch: str
    write_set: tuple[str, ...]
    issued_at: float | None
    digest: str | None
    session_id: str
    task_id: str
    attempt_id: str
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def redact_secrets(text: str) -> str:
    return SECRET_PATTERN.sub(r"\1=<redacted>", text)


def parse_effect_lease(payload: Any) -> EffectLease:
    if not isinstance(payload, dict) or payload.get("schema") != LEASE_SCHEMA:
        raise PluginLeaseError("LEASE_SCHEMA_INVALID", f"lease schema must be {LEASE_SCHEMA}")
    lease_id = _required_str(payload, "lease_id")
    effect_id = _required_str(payload, "effect_id")
    ttl_ms = payload.get("ttl_ms")
    if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or ttl_ms < 1:
        raise PluginLeaseError("LEASE_TTL_INVALID", "ttl_ms must be a positive integer")
    fence = payload.get("fence")
    if fence is not None and (not isinstance(fence, str) or not fence.strip()):
        raise PluginLeaseError("LEASE_FENCE_INVALID", "fence must be a non-empty string when present")
    write_set = payload.get("write_set", [])
    if write_set is None:
        write_set = []
    if not isinstance(write_set, list) or not all(isinstance(item, str) and item for item in write_set):
        raise PluginLeaseError("LEASE_WRITE_SET_INVALID", "write_set must be a list of relative paths")
    issued_at = payload.get("issued_at")
    if issued_at is not None and (isinstance(issued_at, bool) or not isinstance(issued_at, (int, float))):
        raise PluginLeaseError("LEASE_ISSUED_AT_INVALID", "issued_at must be a unix timestamp")
    digest = payload.get("digest")
    if digest is not None and (not isinstance(digest, str) or len(digest) < 16):
        raise PluginLeaseError("LEASE_TAMPERED", "lease digest is missing or too short")
    return EffectLease(
        lease_id=lease_id,
        effect_id=effect_id,
        ttl_ms=ttl_ms,
        fence=str(fence or ""),
        repo=str(payload.get("repo") or ""),
        worktree=str(payload.get("worktree") or ""),
        branch=str(payload.get("branch") or ""),
        write_set=tuple(write_set),
        issued_at=None if issued_at is None else float(issued_at),
        digest=digest,
        session_id=str(payload.get("session_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        attempt_id=str(payload.get("attempt_id") or ""),
        raw=dict(payload),
    )


def validate_lease(
    lease: EffectLease,
    *,
    repo: str,
    worktree: str,
    branch: str,
    now: float | None = None,
    expected_fence: str | None = None,
) -> None:
    clock = time.time() if now is None else now
    if lease.issued_at is not None and (clock - lease.issued_at) * 1000 >= lease.ttl_ms:
        raise PluginLeaseError("LEASE_STALE", "lease ttl has elapsed")
    if lease.digest:
        material = {key: value for key, value in lease.raw.items() if key != "digest"}
        if canonical_digest(material) != lease.digest:
            raise PluginLeaseError("LEASE_TAMPERED", "lease digest does not match canonical payload")
    if expected_fence is not None and lease.fence != expected_fence:
        raise PluginLeaseError("LEASE_TAMPERED", "lease fence does not match the current fence")
    if lease.repo and lease.repo not in {".", repo} and Path(lease.repo).resolve() != Path(repo).resolve():
        raise PluginLeaseError("LEASE_REPO_MISMATCH", "lease repo does not match the work root")
    if (
        lease.worktree
        and lease.worktree not in {".", worktree}
        and Path(lease.worktree).resolve() != Path(worktree).resolve()
    ):
        raise PluginLeaseError("LEASE_WORKTREE_MISMATCH", "lease worktree does not match")
    if lease.branch and lease.branch != branch:
        raise PluginLeaseError("LEASE_BRANCH_MISMATCH", f"lease branch {lease.branch!r} != {branch!r}")


def compile_scoped_plan(
    *,
    goal: str,
    operations: list[dict[str, Any]],
    write_set: tuple[str, ...],
) -> dict[str, Any]:
    if not operations:
        raise PluginLeaseError("PLAN_EMPTY", "leased execution requires at least one operation")
    scoped: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise PluginLeaseError("PLAN_INVALID", "operation must be an object")
        path = operation.get("path")
        dest = operation.get("dest")
        for candidate in (path, dest):
            if isinstance(candidate, str) and write_set and candidate not in write_set:
                raise PluginLeaseError(
                    "WRITE_OUTSIDE_SCOPE",
                    f"{candidate} is outside the leased write-set; obtain a new lease",
                )
        scoped.append(dict(operation))
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": list(write_set or _paths_from_operations(scoped)),
        "operations": scoped,
        "goal": goal,
    }


def execute_leased_work(
    *,
    intent: dict[str, Any],
    route: dict[str, Any],
    lease: dict[str, Any] | EffectLease,
    root: str | Path,
    branch: str,
    operations: list[dict[str, Any]],
    validation: list[dict[str, Any]] | None = None,
    apply: bool = False,
    cancel_check: CancelCheck | None = None,
    now: float | None = None,
    expected_fence: str | None = None,
    run_validation: Callable[[list[dict[str, Any]], Path], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute a scoped plan/edit/test under a validated EffectLease."""
    try:
        parsed = lease if isinstance(lease, EffectLease) else parse_effect_lease(lease)
        _validate_intent(intent)
        _validate_route(route, parsed)
        root_path = Path(root)
        validate_lease(
            parsed,
            repo=str(root_path),
            worktree=str(root_path),
            branch=branch,
            now=now,
            expected_fence=expected_fence,
        )
    except PluginLeaseError as exc:
        fallback = lease if isinstance(lease, EffectLease) else _unsafe_lease(lease)
        return _receipt(
            fallback,
            intent if isinstance(intent, dict) else {},
            route if isinstance(route, dict) else {},
            status="blocked",
            reason_code=exc.code,
            residuals=[str(exc)],
        )
    if cancel_check and cancel_check():
        return _receipt(parsed, intent, route, status="cancelled", reason_code="CANCELLED")
    try:
        plan = compile_scoped_plan(
            goal=str(intent.get("goal") or intent.get("task_id") or ""),
            operations=operations,
            write_set=parsed.write_set,
        )
    except PluginLeaseError as exc:
        return _receipt(parsed, intent, route, status="blocked", reason_code=exc.code, residuals=[str(exc)])
    if validation:
        plan["validation"] = validation
    before = _file_digests(root_path, plan["touched_files"])
    edit_result = execute_plan(plan, root=root_path, apply=apply, allow_native=False)
    if cancel_check and cancel_check():
        return _receipt(
            parsed,
            intent,
            route,
            status="cancelled",
            reason_code="CANCELLED",
            plan=plan,
            edit=edit_result,
            before=before,
        )
    after = _file_digests(root_path, plan["touched_files"])
    files = _changed_files(before, after)
    test_result = _run_tests(validation or [], root_path, run_validation=run_validation)
    status, reason = _classify(edit_result, test_result, files)
    return _receipt(
        parsed,
        intent,
        route,
        status=status,
        reason_code=reason,
        plan=plan,
        edit=edit_result,
        tests=test_result,
        before=before,
        after=after,
        files=files,
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-py plugin-effect-bridge")
    parser.add_argument("--root", default=".")
    parser.add_argument("--branch", default="")
    parser.add_argument("--intent", required=True, help="TaskIntent/RouteDecision envelope JSON path")
    parser.add_argument("--lease", required=True, help="EffectLease JSON path")
    parser.add_argument("--plan", required=True, help="operations JSON path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    envelope = json.loads(Path(args.intent).read_text(encoding="utf-8"))
    lease = json.loads(Path(args.lease).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    receipt = execute_leased_work(
        intent=envelope.get("intent", envelope),
        route=envelope.get("route", envelope.get("route_decision", {})),
        lease=lease,
        root=args.root,
        branch=args.branch,
        operations=plan.get("operations", []),
        validation=plan.get("validation"),
        apply=args.apply,
    )
    emit_data(receipt)
    return 0 if receipt["status"] == "ok" else 1


def _unsafe_lease(payload: Any) -> EffectLease:
    data = payload if isinstance(payload, dict) else {}
    return EffectLease(
        lease_id=str(data.get("lease_id") or "unknown"),
        effect_id=str(data.get("effect_id") or "unknown"),
        ttl_ms=1,
        fence=str(data.get("fence") or ""),
        repo=str(data.get("repo") or ""),
        worktree=str(data.get("worktree") or ""),
        branch=str(data.get("branch") or ""),
        write_set=tuple(data.get("write_set") or ()),
        issued_at=None,
        digest=None,
        session_id=str(data.get("session_id") or ""),
        task_id=str(data.get("task_id") or ""),
        attempt_id=str(data.get("attempt_id") or ""),
        raw=data if isinstance(data, dict) else {},
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginLeaseError("LEASE_FIELDS_INVALID", f"{key} is required")
    return value.strip()


def _validate_intent(intent: dict[str, Any]) -> None:
    if not isinstance(intent, dict) or intent.get("schema") != INTENT_SCHEMA:
        raise PluginLeaseError("INTENT_SCHEMA_INVALID", f"intent schema must be {INTENT_SCHEMA}")
    if not intent.get("task_id"):
        raise PluginLeaseError("INTENT_FIELDS_INVALID", "task_id is required")


def _validate_route(route: dict[str, Any], lease: EffectLease) -> None:
    if not isinstance(route, dict) or route.get("schema") != ROUTE_SCHEMA:
        raise PluginLeaseError("ROUTE_SCHEMA_INVALID", f"route schema must be {ROUTE_SCHEMA}")
    if route.get("route") not in {"map", "edit", "validate", "abstain"}:
        raise PluginLeaseError("ROUTE_INVALID", "route must be a Plugin v1 route")
    if lease.task_id and route.get("task_id") and route["task_id"] != lease.task_id:
        raise PluginLeaseError("ROUTE_TASK_MISMATCH", "route task_id does not match lease")


def _paths_from_operations(operations: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for operation in operations:
        for key in ("path", "dest"):
            value = operation.get(key)
            if isinstance(value, str) and value not in paths:
                paths.append(value)
    return paths


def _file_digests(root: Path, paths: list[str]) -> dict[str, str | None]:
    rows: dict[str, str | None] = {}
    for rel in paths:
        path = root / rel
        rows[rel] = sha256_text(path.read_bytes()) if path.is_file() else None
    return rows


def _changed_files(before: dict[str, str | None], after: dict[str, str | None]) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        rows.append(
            {
                "path": path,
                "before_sha256": before.get(path),
                "after_sha256": after.get(path),
            }
        )
    return rows


def _run_tests(
    validation: list[dict[str, Any]],
    root: Path,
    *,
    run_validation: Callable[[list[dict[str, Any]], Path], list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    if not validation:
        return {"status": "skipped", "results": []}
    runner = run_validation or _default_validation
    try:
        results = runner(validation, root)
    except TimeoutError:
        return {"status": "timeout", "results": []}
    except InterruptedError:
        return {"status": "cancelled", "results": []}
    redacted = []
    for row in results:
        item = dict(row)
        if "log_summary" in item:
            item["log_summary"] = redact_secrets(str(item["log_summary"]))
        redacted.append(item)
    failed = [row for row in redacted if not row.get("passed") and not row.get("advisory")]
    return {"status": "failed" if failed else "passed", "results": redacted}


def _default_validation(validation: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    from .mechanical_edit import _run_validation

    return _run_validation(validation, root)


def _classify(
    edit_result: dict[str, Any],
    test_result: dict[str, Any],
    files: list[dict[str, Any]],
) -> tuple[str, str]:
    edit_status = edit_result.get("status")
    if edit_status == "effect_unknown":
        return "ambiguous", "EDIT_AMBIGUOUS"
    if edit_status == "refused":
        return "failed", "EDIT_FAILED"
    test_status = test_result.get("status")
    if test_status == "timeout":
        return "partial", "TEST_TIMEOUT"
    if test_status == "cancelled":
        return "cancelled", "TEST_CANCELLED"
    if test_status == "failed":
        return "failed", "TEST_FAILED"
    if edit_result.get("applied") is False and files:
        return "partial", "EDIT_PARTIAL"
    return "ok", "OK"


def _receipt(
    lease: EffectLease,
    intent: dict[str, Any],
    route: dict[str, Any],
    *,
    status: str,
    reason_code: str,
    plan: dict[str, Any] | None = None,
    edit: dict[str, Any] | None = None,
    tests: dict[str, Any] | None = None,
    before: dict[str, str | None] | None = None,
    after: dict[str, str | None] | None = None,
    files: list[dict[str, Any]] | None = None,
    residuals: list[str] | None = None,
) -> dict[str, Any]:
    correlation = {
        "session_id": lease.session_id or intent.get("session_id") or "",
        "task_id": lease.task_id or intent.get("task_id") or "",
        "attempt_id": lease.attempt_id,
        "lease_id": lease.lease_id,
        "effect_id": lease.effect_id,
        "fence": lease.fence,
    }
    tool_receipt = {
        "schema": TOOL_RECEIPT_SCHEMA,
        "tool": "dev-cli.mechanical-edit",
        "status": "ok" if status == "ok" else ("blocked" if status == "blocked" else "error"),
        "digest": canonical_digest(
            {
                "correlation": correlation,
                "status": status,
                "files": files or [],
            }
        ),
        "reason_code": reason_code,
        "lease_id": lease.lease_id,
        "effect_id": lease.effect_id,
    }
    receipt = {
        "schema": DEV_RECEIPT_SCHEMA,
        "status": status,
        "reason_code": reason_code,
        "convergence_declared": False,
        "correlation": correlation,
        "plan": plan,
        "edit": edit,
        "tests": tests or {"status": "skipped", "results": []},
        "files": files or [],
        "before_digests": before or {},
        "after_digests": after or {},
        "residuals": residuals or [],
        "tool_receipt": tool_receipt,
        "route": route.get("route"),
    }
    receipt["digest"] = canonical_digest({key: value for key, value in receipt.items() if key != "digest"})
    return receipt


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
