"""Deterministic Stage ABI mutation worker contracts.

This module is deliberately mechanical: it validates an authorized envelope,
delegates file operations to the existing mechanical-edit engine, and emits a
compact, hash-verifiable receipt. Planning and completion authority remain
outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .mechanical_edit import execute_plan

STAGE_MUTATION_SCHEMA = "simplicio.stage-mutation/v1"
MUTATION_RECEIPT_SCHEMA = "simplicio.mutation-receipt/v1"
_RESULT_SCHEMA = "simplicio.stage-mutation-result/v1"
_LLM_ISSUERS = {"llm", "model", "assistant", "language-model"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_ATOMIC_WRITE_LOCK = threading.Lock()


class StageAbiError(ValueError):
    """Fail-closed validation error for a Stage ABI envelope."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normal_relative(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StageAbiError("STAGE_PATH_INVALID", f"{field} must be a non-empty relative path")
    if any(char in value for char in "*?[]"):
        raise StageAbiError("STAGE_GLOB_FORBIDDEN", f"{field} must resolve a single path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise StageAbiError("STAGE_PATH_ESCAPE", f"{field} must stay inside the workspace")
    normalized = candidate.as_posix()
    if normalized in {"", "."}:
        raise StageAbiError("STAGE_PATH_INVALID", f"{field} cannot target the workspace root")
    return normalized


def _target(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise StageAbiError("STAGE_SYMLINK_ESCAPE", f"path escapes workspace: {relative}") from exc
    return candidate


def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise StageAbiError("STAGE_TARGET_NOT_FILE", f"target is not a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".receipt-", suffix=".tmp", delete=False
    ) as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class StageMutationEnvelopeV1:
    """One explicit, authorized mechanical mutation."""

    effect_id: str
    plan_node_id: str
    idempotency_key: str
    workspace_root: str
    allowlist: tuple[str, ...]
    source_hashes: dict[str, str]
    operations: tuple[dict[str, Any], ...]
    hookwall: dict[str, Any]
    policy_revision: str
    context_handle: str = ""
    validation: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StageMutationEnvelopeV1":
        if not isinstance(payload, dict) or payload.get("schema") != STAGE_MUTATION_SCHEMA:
            raise StageAbiError("STAGE_SCHEMA_INVALID", "envelope schema is invalid")
        required = {
            "schema",
            "effect_id",
            "plan_node_id",
            "idempotency_key",
            "workspace_root",
            "allowlist",
            "source_hashes",
            "operations",
            "hookwall",
            "policy_revision",
            "context_handle",
            "validation",
        }
        unknown = sorted(set(payload) - required)
        if unknown:
            raise StageAbiError("STAGE_FIELDS_INVALID", "unknown envelope fields", fields=unknown)
        missing = sorted(field for field in required - {"schema"} if field not in payload)
        if missing:
            raise StageAbiError("STAGE_FIELDS_MISSING", "missing envelope fields", fields=missing)
        string_fields = (
            "effect_id",
            "plan_node_id",
            "idempotency_key",
            "workspace_root",
            "policy_revision",
            "context_handle",
        )
        if any(not isinstance(payload[field], str) for field in string_fields):
            raise StageAbiError("STAGE_FIELDS_INVALID", "envelope identity fields must be strings")
        if not isinstance(payload["allowlist"], list) or not all(
            isinstance(item, str) for item in payload["allowlist"]
        ):
            raise StageAbiError("STAGE_ALLOWLIST_INVALID", "allowlist must be a list of paths")
        allowlist = tuple(_normal_relative(item, field="allowlist") for item in payload["allowlist"])
        if len(set(allowlist)) != len(allowlist) or not allowlist:
            raise StageAbiError("STAGE_ALLOWLIST_INVALID", "allowlist must contain unique paths")
        if not isinstance(payload["source_hashes"], dict):
            raise StageAbiError("STAGE_SOURCE_HASHES_INVALID", "source_hashes must be an object")
        source_hashes: dict[str, str] = {}
        for path, digest in payload["source_hashes"].items():
            normalized = _normal_relative(path, field="source_hashes path")
            if not isinstance(digest, str) or (digest and not _HEX64.fullmatch(digest)):
                raise StageAbiError("STAGE_SOURCE_HASH_INVALID", f"invalid source hash for {normalized}")
            source_hashes[normalized] = digest
        if not isinstance(payload["operations"], list) or not payload["operations"]:
            raise StageAbiError("STAGE_OPERATIONS_INVALID", "operations must be a non-empty list")
        operations: list[dict[str, Any]] = []
        for index, operation in enumerate(payload["operations"]):
            if not isinstance(operation, dict):
                raise StageAbiError("STAGE_OPERATIONS_INVALID", f"operation {index} must be an object")
            copied = dict(operation)
            copied["path"] = _normal_relative(copied.get("path"), field=f"operations[{index}].path")
            operations.append(copied)
        if not isinstance(payload["hookwall"], dict):
            raise StageAbiError("STAGE_HOOKWALL_INVALID", "hookwall must be an object")
        hookwall = dict(payload["hookwall"])
        if hookwall.get("decision") != "allow":
            raise StageAbiError("STAGE_HOOKWALL_DENY", "Hookwall did not authorize the effect")
        issuer = hookwall.get("issuer")
        if not isinstance(issuer, str) or not issuer.strip() or issuer.lower() in _LLM_ISSUERS:
            raise StageAbiError("STAGE_HOOKWALL_ISSUER_INVALID", "Hookwall issuer must be a coordinator")
        if not isinstance(hookwall.get("receipt"), str) or not hookwall["receipt"].strip():
            raise StageAbiError("STAGE_HOOKWALL_RECEIPT_MISSING", "Hookwall receipt is required")
        if not isinstance(payload["validation"], list) or not all(
            isinstance(item, dict) for item in payload["validation"]
        ):
            raise StageAbiError("STAGE_VALIDATION_INVALID", "validation must be a list of objects")
        if not _SAFE_KEY.fullmatch(payload["idempotency_key"]):
            raise StageAbiError("STAGE_IDEMPOTENCY_INVALID", "idempotency_key has an unsafe or empty format")
        return cls(
            effect_id=payload["effect_id"],
            plan_node_id=payload["plan_node_id"],
            idempotency_key=payload["idempotency_key"],
            workspace_root=payload["workspace_root"],
            allowlist=allowlist,
            source_hashes=source_hashes,
            operations=tuple(operations),
            hookwall=hookwall,
            policy_revision=payload["policy_revision"],
            context_handle=payload["context_handle"],
            validation=tuple(dict(item) for item in payload["validation"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STAGE_MUTATION_SCHEMA,
            "effect_id": self.effect_id,
            "plan_node_id": self.plan_node_id,
            "idempotency_key": self.idempotency_key,
            "workspace_root": self.workspace_root,
            "allowlist": list(self.allowlist),
            "source_hashes": dict(sorted(self.source_hashes.items())),
            "operations": [dict(item) for item in self.operations],
            "hookwall": dict(self.hookwall),
            "policy_revision": self.policy_revision,
            "context_handle": self.context_handle,
            "validation": [dict(item) for item in self.validation],
        }

    def digest(self) -> str:
        return _canonical_hash(self.to_dict())


def _targets(envelope: StageMutationEnvelopeV1) -> tuple[str, ...]:
    paths = tuple(operation["path"] for operation in envelope.operations)
    if len(set(paths)) != len(paths):
        raise StageAbiError("STAGE_OPERATIONS_INVALID", "each path may be mutated only once per envelope")
    if not set(paths).issubset(set(envelope.allowlist)):
        outside = sorted(set(paths) - set(envelope.allowlist))
        raise StageAbiError("STAGE_ALLOWLIST_DENY", "operation is outside the allowlist", paths=outside)
    if set(envelope.source_hashes) != set(paths):
        raise StageAbiError("STAGE_SOURCE_HASHES_INVALID", "source hashes must cover the exact effect set")
    return paths


def _validate_binding(envelope: StageMutationEnvelopeV1, root: Path) -> tuple[str, ...]:
    expected_root = root.resolve()
    declared_root = Path(envelope.workspace_root).expanduser().resolve()
    if declared_root != expected_root:
        raise StageAbiError(
            "STAGE_WORKSPACE_MISMATCH",
            "envelope workspace_root does not match execution root",
            declared=str(declared_root),
            actual=str(expected_root),
        )
    paths = _targets(envelope)
    for relative in paths:
        _target(expected_root, relative)
    return paths


def _check_sources(envelope: StageMutationEnvelopeV1, root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    before = {relative: _hash_file(_target(root, relative)) for relative in paths}
    for relative in paths:
        expected = envelope.source_hashes[relative]
        if before[relative] != expected:
            raise StageAbiError(
                "STAGE_SOURCE_DRIFT",
                f"source hash differs for {relative}",
                path=relative,
                expected=expected,
                actual=before[relative],
            )
    return before


def _receipt_path(root: Path, idempotency_key: str) -> Path:
    key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return root / ".simplicio" / "stage-abi" / f"{key_digest}.receipt.json"


def _load_idempotent(path: Path, *, plan_digest: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageAbiError("STAGE_RECEIPT_INVALID", "stored receipt is unreadable") from exc
    if not isinstance(receipt, dict) or receipt.get("schema") != MUTATION_RECEIPT_SCHEMA:
        raise StageAbiError("STAGE_RECEIPT_INVALID", "stored receipt schema is invalid")
    if receipt.get("plan_digest") != plan_digest:
        raise StageAbiError("STAGE_IDEMPOTENCY_CONFLICT", "idempotency key is bound to another plan")
    if receipt.get("status") != "completed":
        raise StageAbiError("STAGE_RECEIPT_INVALID", "stored receipt is not completed")
    return receipt


def _build_receipt(
    envelope: StageMutationEnvelopeV1,
    *,
    root: Path,
    before: dict[str, str],
    after: dict[str, str],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": MUTATION_RECEIPT_SCHEMA,
        "status": "completed" if result.get("status") == "ok" else "rejected",
        "exit_status": 0 if result.get("status") == "ok" else 1,
        "effect_id": envelope.effect_id,
        "plan_node_id": envelope.plan_node_id,
        "idempotency_key": envelope.idempotency_key,
        "plan_digest": envelope.digest(),
        "workspace_root": str(root.resolve()),
        "policy_revision": envelope.policy_revision,
        "hookwall_receipt": envelope.hookwall["receipt"],
        "operation_count": len(envelope.operations),
        "applied": bool(result.get("applied")),
        "noop": bool(result.get("noop")),
        "before_hashes": dict(sorted(before.items())),
        "after_hashes": dict(sorted(after.items())),
        "artifacts": [],
        "evidence_handles": [f"stage-abi:{envelope.idempotency_key}"],
    }


def execute_stage_envelope(
    envelope: StageMutationEnvelopeV1 | dict[str, Any],
    *,
    root: str | Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Run one Hookwall-authorized mechanical envelope with a compact receipt."""
    if isinstance(envelope, dict):
        envelope = StageMutationEnvelopeV1.from_dict(envelope)
    root_path = Path(root).expanduser().resolve()
    paths = _validate_binding(envelope, root_path)
    receipt_path = _receipt_path(root_path, envelope.idempotency_key)
    with _ATOMIC_WRITE_LOCK:
        existing = _load_idempotent(receipt_path, plan_digest=envelope.digest())
        if existing is not None:
            verify_mutation_receipt(existing, root=root_path)
            return {
                "schema": _RESULT_SCHEMA,
                "status": "idempotent",
                "applied": False,
                "idempotent": True,
                "mutation_receipt": existing,
            }
        before = _check_sources(envelope, root_path, paths)
        plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": list(paths),
            "operations": [dict(item) for item in envelope.operations],
            "validation": [dict(item) for item in envelope.validation],
        }
        result = execute_plan(plan, root=root_path, apply=apply)
        after = {relative: _hash_file(_target(root_path, relative)) for relative in paths}
        receipt = _build_receipt(envelope, root=root_path, before=before, after=after, result=result)
        if apply and result.get("status") == "ok":
            _atomic_json(receipt_path, receipt)
        return {
            "schema": _RESULT_SCHEMA,
            "status": "completed" if result.get("status") == "ok" else "rejected",
            "applied": bool(result.get("applied")),
            "idempotent": False,
            "mutation_receipt": receipt,
            "mechanical_result": result,
        }


def verify_mutation_receipt(receipt: dict[str, Any], *, root: str | Path) -> bool:
    """Verify the receipt's post-state hashes against the current workspace."""
    if not isinstance(receipt, dict) or receipt.get("schema") != MUTATION_RECEIPT_SCHEMA:
        raise StageAbiError("STAGE_RECEIPT_INVALID", "receipt schema is invalid")
    if receipt.get("status") != "completed":
        raise StageAbiError("STAGE_RECEIPT_INVALID", "only completed receipts are verifiable")
    root_path = Path(root).expanduser().resolve()
    if Path(str(receipt.get("workspace_root", ""))).expanduser().resolve() != root_path:
        raise StageAbiError("STAGE_WORKSPACE_MISMATCH", "receipt workspace_root does not match execution root")
    after = receipt.get("after_hashes")
    if not isinstance(after, dict) or not after:
        raise StageAbiError("STAGE_RECEIPT_INVALID", "receipt after_hashes are missing")
    for relative, expected in after.items():
        normalized = _normal_relative(relative, field="receipt after_hashes path")
        actual = _hash_file(_target(root_path, normalized))
        if actual != expected:
            raise StageAbiError(
                "STAGE_POSTCONDITION_FAILED",
                f"current hash differs for {normalized}",
                path=normalized,
                expected=expected,
                actual=actual,
            )
    return True
