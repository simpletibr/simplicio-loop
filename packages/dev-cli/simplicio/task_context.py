"""Validated root, scope, and identity binding for mutation-capable tasks."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

TASK_CONTEXT_SCHEMA = "simplicio.task-context/v1"


class TaskContextError(ValueError):
    """Stable fail-closed error for a task's authorization boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskContextError("TASK_CONTEXT_REQUIRED", f"{field} is required")
    return value.strip()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class TaskContext:
    """Immutable root/target/context identity carried by one task attempt."""

    repo_root: str
    scope_root: str
    target: str
    context_snapshot_id: str
    context_pack_hash: str
    attempt_id: str
    context_hash: str

    @classmethod
    def from_values(
        cls,
        *,
        repo_root: str | os.PathLike[str] | None,
        scope_root: str | os.PathLike[str] | None,
        target: str | None,
        context_snapshot_id: str = "",
        context_pack_hash: str = "",
        attempt_id: str = "",
        require_identity: bool = False,
    ) -> TaskContext:
        repo_value = os.fspath(repo_root) if isinstance(repo_root, os.PathLike) else repo_root
        repo = Path(_required_text(repo_value, "repo_root")).resolve()
        scope_input = os.fspath(scope_root) if isinstance(scope_root, os.PathLike) else scope_root
        scope_value = _required_text(scope_input, "scope_root")
        scope_path = Path(scope_value)
        scope = (repo / scope_path).resolve() if not scope_path.is_absolute() else scope_path.resolve()
        if not _inside(scope, repo):
            raise TaskContextError("ROOT_SCOPE_MISMATCH", "scope_root must be inside repo_root")
        target_value = _required_text(target, "target")
        target_path = PurePosixPath(target_value.replace("\\", "/"))
        if (
            target_path.is_absolute()
            or PureWindowsPath(target_value).is_absolute()
            or PureWindowsPath(target_value).drive
            or ".." in target_path.parts
        ):
            raise TaskContextError("TARGET_OUTSIDE_SCOPE", "target must be a relative path inside scope_root")
        resolved_target = (scope / Path(*target_path.parts)).resolve()
        if not _inside(resolved_target, scope) or not _inside(resolved_target, repo):
            raise TaskContextError("TARGET_OUTSIDE_SCOPE", "target resolves outside scope_root")
        snapshot_id = str(context_snapshot_id or "").strip()
        pack_hash = str(context_pack_hash or "").strip()
        attempt = str(attempt_id or "").strip()
        if require_identity:
            if not snapshot_id or not pack_hash:
                raise TaskContextError(
                    "MAPPER_CONTEXT_IDENTITY_REQUIRED",
                    "context snapshot and pack identities are required",
                )
            if not attempt:
                raise TaskContextError("ATTEMPT_ID_REQUIRED", "attempt_id is required for mutation")
        identity = {
            "repo_root": str(repo),
            "scope_root": str(scope),
            "target": "/".join(target_path.parts),
            "context_snapshot_id": snapshot_id,
            "context_pack_hash": pack_hash,
            "attempt_id": attempt,
        }
        context_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            repo_root=str(repo),
            scope_root=str(scope),
            target=identity["target"],
            context_snapshot_id=snapshot_id,
            context_pack_hash=pack_hash,
            attempt_id=attempt,
            context_hash=context_hash,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, require_identity: bool = True) -> TaskContext:
        if not isinstance(payload, dict) or payload.get("schema") != TASK_CONTEXT_SCHEMA:
            raise TaskContextError("TASK_CONTEXT_SCHEMA_INVALID", "task context schema is invalid")
        allowed = {
            "schema",
            "repo_root",
            "scope_root",
            "target",
            "context_snapshot_id",
            "context_pack_hash",
            "attempt_id",
            "context_hash",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise TaskContextError("TASK_CONTEXT_FIELDS_INVALID", ", ".join(unknown))
        supplied_hash = _required_text(payload.get("context_hash"), "context_hash")
        context = cls.from_values(
            repo_root=payload.get("repo_root"),
            scope_root=payload.get("scope_root"),
            target=payload.get("target"),
            context_snapshot_id=payload.get("context_snapshot_id", ""),
            context_pack_hash=payload.get("context_pack_hash", ""),
            attempt_id=payload.get("attempt_id", ""),
            require_identity=require_identity,
        )
        if supplied_hash != context.context_hash:
            raise TaskContextError(
                "CONTEXT_HASH_MISMATCH",
                "context_hash does not match canonical task context",
            )
        return context

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": TASK_CONTEXT_SCHEMA,
            "repo_root": self.repo_root,
            "scope_root": self.scope_root,
            "target": self.target,
            "context_snapshot_id": self.context_snapshot_id,
            "context_pack_hash": self.context_pack_hash,
            "attempt_id": self.attempt_id,
            "context_hash": self.context_hash,
        }

    def receipt(
        self,
        *,
        route: str,
        effective_mode: str,
        authorization_id: str | None = None,
        before_digest: str | None = None,
        after_digest: str | None = None,
        verification_status: str = "unverified",
        lease_id: str | None = None,
        fencing_token: str | None = None,
        context_handle: str | None = None,
        plan: Any = None,
        changeset: Any = None,
        files: list[Any] | None = None,
        verification: dict[str, Any] | None = None,
        retry: dict[str, Any] | None = None,
        duration_ms: int | float | None = None,
        final_status: str | None = None,
    ) -> dict[str, Any]:
        """Return one stable receipt shape for every mutation outcome."""
        available = {
            "attempt_id": self.attempt_id or None,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "context_handle": context_handle,
            "authorization_id": authorization_id,
        }
        verification_payload = dict(verification or {})
        verification_payload.setdefault("commands", [])
        verification_payload.setdefault("results", [])
        verification_payload.setdefault("status", verification_status)
        retry_payload = dict(retry or {})
        retry_payload.setdefault("attempt", 1)
        retry_payload.setdefault("max_attempts", 1)
        retry_payload.setdefault("retryable", False)
        return {
            "schema": "simplicio.mutation-authorization-receipt/v1",
            "receipt_version": 1,
            "route": route,
            "effective_mode": effective_mode,
            "context_hash": self.context_hash,
            "authorization_id": authorization_id,
            "before_digest": before_digest,
            "after_digest": after_digest,
            "verification_status": verification_status,
            "available": available,
            "available_tuple": [key for key, value in available.items() if value is not None],
            "attempt_id": self.attempt_id or None,
            "lease_id": lease_id,
            "fencing_token": fencing_token,
            "context_handle": context_handle,
            "plan": plan,
            "changeset": changeset,
            "files": list(files or []),
            "verification": verification_payload,
            "retry": retry_payload,
            "duration_ms": duration_ms,
            "final_status": final_status or ("applied" if verification_status == "verified" else "blocked"),
            "task_context": self.to_dict(),
        }


__all__ = ["TASK_CONTEXT_SCHEMA", "TaskContext", "TaskContextError"]
