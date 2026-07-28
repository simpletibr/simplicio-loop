"""Context-bound mechanical execution contracts.

The Loop decides intent and planning.  Dev CLI accepts only closed, hash-bound
operations and deterministic verification commands; this module never invokes
a provider or model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.errors import PlanValidationError, SchemaMismatchError

CHANGE_SET_SCHEMA = "simplicio.change-set/v1"
BOUND_VERIFICATION_PLAN_SCHEMA = "simplicio.verification-plan/v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MODES = frozenset({"dry-run", "write"})
_OPERATIONS = frozenset({"create", "replace", "patch", "delete"})
_LEVELS = frozenset({"parse", "format", "targeted", "impact", "module", "full"})
_OPEN_INSTRUCTION_KEYS = frozenset({"instruction", "prompt", "goal", "description"})


def _require_digest(name: str, value: str, diagnostics: list[str]) -> None:
    if not _DIGEST.fullmatch(value):
        diagnostics.append(f"{name}: hash_required")


def _extensions(payload: dict[str, Any], known: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in known}


@dataclass(frozen=True)
class ContextHashes:
    context_packet: str
    fast_generation: str
    plan_dag: str

    def validate(self) -> list[str]:
        diagnostics: list[str] = []
        _require_digest("context_hashes.context_packet", self.context_packet, diagnostics)
        _require_digest("context_hashes.fast_generation", self.fast_generation, diagnostics)
        _require_digest("context_hashes.plan_dag", self.plan_dag, diagnostics)
        return diagnostics

    def to_dict(self) -> dict[str, str]:
        return {
            "context_packet": self.context_packet,
            "fast_generation": self.fast_generation,
            "plan_dag": self.plan_dag,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ContextHashes:
        return cls(
            context_packet=str(payload.get("context_packet", "")),
            fast_generation=str(payload.get("fast_generation", "")),
            plan_dag=str(payload.get("plan_dag", "")),
        )


@dataclass(frozen=True)
class ChangeOperation:
    operation_id: str
    kind: str
    target: str
    before_hash: str | None = None
    content_handle: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        diagnostics: list[str] = []
        if not self.operation_id:
            diagnostics.append("operation_id: required")
        if self.kind not in _OPERATIONS:
            diagnostics.append(f"{self.operation_id or 'operation'}: unsupported_operation")
        if not self.target or self.target.startswith("/") or ".." in self.target.split("/"):
            diagnostics.append(f"{self.operation_id or 'operation'}: unsafe_target")
        if self.kind in {"replace", "patch", "delete"}:
            _require_digest(
                f"{self.operation_id or 'operation'}.before_hash",
                self.before_hash or "",
                diagnostics,
            )
        if self.kind in {"create", "replace", "patch"} and not self.content_handle:
            diagnostics.append(f"{self.operation_id or 'operation'}: content_handle_required")
        if _OPEN_INSTRUCTION_KEYS.intersection(self.extensions):
            diagnostics.append(f"{self.operation_id or 'operation'}: open_instruction_rejected")
        return diagnostics

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "target": self.target,
            "before_hash": self.before_hash,
            "content_handle": self.content_handle,
        }
        payload.update(self.extensions)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChangeOperation:
        known = frozenset(
            {"operation_id", "kind", "target", "before_hash", "content_handle"}
        )
        return cls(
            operation_id=str(payload.get("operation_id", "")),
            kind=str(payload.get("kind", "")),
            target=str(payload.get("target", "")),
            before_hash=(
                str(payload["before_hash"]) if payload.get("before_hash") is not None else None
            ),
            content_handle=(
                str(payload["content_handle"])
                if payload.get("content_handle") is not None
                else None
            ),
            extensions=_extensions(payload, known),
        )


@dataclass(frozen=True)
class ChangeSet:
    change_set_id: str
    idempotency_key: str
    generation: int
    mode: str
    context_hashes: ContextHashes
    preconditions: list[str]
    operations: list[ChangeOperation]
    write_set: list[str]
    extensions: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        diagnostics = self.context_hashes.validate()
        if not self.change_set_id:
            diagnostics.append("change_set_id: required")
        if not self.idempotency_key:
            diagnostics.append("idempotency_key: required")
        if self.generation < 1:
            diagnostics.append("generation: positive_value_required")
        if self.mode not in _MODES:
            diagnostics.append("mode: unsupported_mode")
        if not self.operations:
            diagnostics.append("operations: mechanical_operation_required")
        if not self.preconditions:
            diagnostics.append("preconditions: required")
        if len(self.write_set) != len(set(self.write_set)):
            diagnostics.append("write_set: duplicate_target")
        operation_targets = {operation.target for operation in self.operations}
        if operation_targets != set(self.write_set):
            diagnostics.append("write_set: operation_target_mismatch")
        for operation in self.operations:
            diagnostics.extend(operation.validate())
        if _OPEN_INSTRUCTION_KEYS.intersection(self.extensions):
            diagnostics.append("changeset: open_instruction_rejected")
        if diagnostics:
            raise PlanValidationError(diagnostics)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": CHANGE_SET_SCHEMA,
            "change_set_id": self.change_set_id,
            "idempotency_key": self.idempotency_key,
            "generation": self.generation,
            "mode": self.mode,
            "context_hashes": self.context_hashes.to_dict(),
            "preconditions": self.preconditions,
            "operations": [operation.to_dict() for operation in self.operations],
            "write_set": self.write_set,
        }
        payload.update(self.extensions)
        return payload

    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChangeSet:
        if payload.get("schema") != CHANGE_SET_SCHEMA:
            raise SchemaMismatchError(
                "simplicio.change-set", CHANGE_SET_SCHEMA, str(payload.get("schema"))
            )
        known = frozenset(
            {
                "schema",
                "change_set_id",
                "idempotency_key",
                "generation",
                "mode",
                "context_hashes",
                "preconditions",
                "operations",
                "write_set",
            }
        )
        contract = cls(
            change_set_id=str(payload.get("change_set_id", "")),
            idempotency_key=str(payload.get("idempotency_key", "")),
            generation=int(payload.get("generation", 0)),
            mode=str(payload.get("mode", "")),
            context_hashes=ContextHashes.from_dict(dict(payload.get("context_hashes", {}))),
            preconditions=list(payload.get("preconditions", [])),
            operations=[
                ChangeOperation.from_dict(dict(operation))
                for operation in payload.get("operations", [])
            ],
            write_set=list(payload.get("write_set", [])),
            extensions=_extensions(payload, known),
        )
        contract.validate()
        return contract


@dataclass(frozen=True)
class VerificationCommand:
    command_id: str
    level: str
    argv: list[str]
    timeout_s: float
    expected_signals: list[str]

    def validate(self) -> list[str]:
        diagnostics: list[str] = []
        if self.level not in _LEVELS:
            diagnostics.append(f"{self.command_id}: unsupported_level")
        if not self.argv or any(not isinstance(part, str) or not part for part in self.argv):
            diagnostics.append(f"{self.command_id}: argv_required")
        if self.timeout_s <= 0:
            diagnostics.append(f"{self.command_id}: timeout_required")
        if not self.expected_signals:
            diagnostics.append(f"{self.command_id}: expected_signal_required")
        return diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "level": self.level,
            "argv": self.argv,
            "timeout_s": self.timeout_s,
            "expected_signals": self.expected_signals,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VerificationCommand:
        return cls(
            command_id=str(payload.get("command_id", "")),
            level=str(payload.get("level", "")),
            argv=list(payload.get("argv", [])),
            timeout_s=float(payload.get("timeout_s", 0)),
            expected_signals=list(payload.get("expected_signals", [])),
        )


@dataclass(frozen=True)
class BoundVerificationPlan:
    verification_plan_id: str
    change_set_hash: str
    context_hashes: ContextHashes
    commands: list[VerificationCommand]
    extensions: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        diagnostics = self.context_hashes.validate()
        _require_digest("change_set_hash", self.change_set_hash, diagnostics)
        if not self.verification_plan_id:
            diagnostics.append("verification_plan_id: required")
        if not self.commands:
            diagnostics.append("commands: required")
        for command in self.commands:
            diagnostics.extend(command.validate())
        if diagnostics:
            raise PlanValidationError(diagnostics)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": BOUND_VERIFICATION_PLAN_SCHEMA,
            "verification_plan_id": self.verification_plan_id,
            "change_set_hash": self.change_set_hash,
            "context_hashes": self.context_hashes.to_dict(),
            "commands": [command.to_dict() for command in self.commands],
        }
        payload.update(self.extensions)
        return payload

    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BoundVerificationPlan:
        if payload.get("schema") != BOUND_VERIFICATION_PLAN_SCHEMA:
            raise SchemaMismatchError(
                "simplicio.verification-plan",
                BOUND_VERIFICATION_PLAN_SCHEMA,
                str(payload.get("schema")),
            )
        known = frozenset(
            {"schema", "verification_plan_id", "change_set_hash", "context_hashes", "commands"}
        )
        contract = cls(
            verification_plan_id=str(payload.get("verification_plan_id", "")),
            change_set_hash=str(payload.get("change_set_hash", "")),
            context_hashes=ContextHashes.from_dict(dict(payload.get("context_hashes", {}))),
            commands=[
                VerificationCommand.from_dict(dict(command))
                for command in payload.get("commands", [])
            ],
            extensions=_extensions(payload, known),
        )
        contract.validate()
        return contract
