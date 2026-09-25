"""PrismExecutionEnvelope/v1 — causal mutation envelope (#379)."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.errors import PlanValidationError, SchemaMismatchError

ENVELOPE_SCHEMA = "simplicio.prism-execution-envelope/v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _require(name: str, value: str, diagnostics: list[str]) -> None:
    if not value:
        diagnostics.append(f"{name}: required")


def _require_digest(name: str, value: str, diagnostics: list[str]) -> None:
    if not _DIGEST.fullmatch(value or ""):
        diagnostics.append(f"{name}: hash_required")


@dataclass(frozen=True)
class PrismExecutionEnvelope:
    goal_id: str
    prism_id: str
    parent_prism_id: str | None
    slot_id: str
    task_id: str
    owner_agent_id: str
    attempt_id: str
    repo_id: str
    base_commit: str
    context_generation: str
    context_graph_digest: str
    task_facts_digest: str
    plan_revision: str
    change_set_hash: str
    verification_plan_hash: str
    lease_id: str
    fence_token: str
    authority_hash: str
    expires_at_ns: int
    causal_parent: str | None
    trace_id: str
    created_at_ns: int
    allowed_effects: tuple[str, ...] = ()
    forbidden_effects: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    extensions: dict[str, Any] = field(default_factory=dict)

    def validate(self, *, now_ns: int | None = None) -> None:
        diagnostics: list[str] = []
        for name, value in (
            ("goal_id", self.goal_id),
            ("prism_id", self.prism_id),
            ("slot_id", self.slot_id),
            ("task_id", self.task_id),
            ("owner_agent_id", self.owner_agent_id),
            ("attempt_id", self.attempt_id),
            ("repo_id", self.repo_id),
            ("base_commit", self.base_commit),
            ("context_generation", self.context_generation),
            ("plan_revision", self.plan_revision),
            ("lease_id", self.lease_id),
            ("fence_token", self.fence_token),
            ("trace_id", self.trace_id),
        ):
            _require(name, value, diagnostics)
        for name, value in (
            ("context_graph_digest", self.context_graph_digest),
            ("task_facts_digest", self.task_facts_digest),
            ("change_set_hash", self.change_set_hash),
            ("verification_plan_hash", self.verification_plan_hash),
            ("authority_hash", self.authority_hash),
        ):
            _require_digest(name, value, diagnostics)
        now = time.time_ns() if now_ns is None else now_ns
        if self.expires_at_ns <= now:
            diagnostics.append("expires_at_ns: expired")
        if self.created_at_ns <= 0:
            diagnostics.append("created_at_ns: required")
        overlap = set(self.allowed_effects).intersection(self.forbidden_effects)
        if overlap:
            diagnostics.append(f"effects: conflict:{','.join(sorted(overlap))}")
        if diagnostics:
            raise PlanValidationError(diagnostics)

    def binds_change_set(self, change_set_hash: str) -> bool:
        return self.change_set_hash == change_set_hash

    def binds_verification_plan(self, verification_plan_hash: str) -> bool:
        return self.verification_plan_hash == verification_plan_hash

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": ENVELOPE_SCHEMA,
            "goal_id": self.goal_id,
            "prism_id": self.prism_id,
            "parent_prism_id": self.parent_prism_id,
            "slot_id": self.slot_id,
            "task_id": self.task_id,
            "owner_agent_id": self.owner_agent_id,
            "attempt_id": self.attempt_id,
            "repo_id": self.repo_id,
            "base_commit": self.base_commit,
            "context_generation": self.context_generation,
            "context_graph_digest": self.context_graph_digest,
            "task_facts_digest": self.task_facts_digest,
            "plan_revision": self.plan_revision,
            "change_set_hash": self.change_set_hash,
            "verification_plan_hash": self.verification_plan_hash,
            "lease_id": self.lease_id,
            "fence_token": self.fence_token,
            "authority_hash": self.authority_hash,
            "expires_at_ns": self.expires_at_ns,
            "causal_parent": self.causal_parent,
            "trace_id": self.trace_id,
            "created_at_ns": self.created_at_ns,
            "allowed_effects": list(self.allowed_effects),
            "forbidden_effects": list(self.forbidden_effects),
            "capabilities": list(self.capabilities),
        }
        payload.update(self.extensions)
        return payload

    def envelope_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PrismExecutionEnvelope:
        if payload.get("schema") != ENVELOPE_SCHEMA:
            raise SchemaMismatchError(
                "simplicio.prism-execution-envelope",
                ENVELOPE_SCHEMA,
                str(payload.get("schema")),
            )
        known = frozenset(
            {
                "schema",
                "goal_id",
                "prism_id",
                "parent_prism_id",
                "slot_id",
                "task_id",
                "owner_agent_id",
                "attempt_id",
                "repo_id",
                "base_commit",
                "context_generation",
                "context_graph_digest",
                "task_facts_digest",
                "plan_revision",
                "change_set_hash",
                "verification_plan_hash",
                "lease_id",
                "fence_token",
                "authority_hash",
                "expires_at_ns",
                "causal_parent",
                "trace_id",
                "created_at_ns",
                "allowed_effects",
                "forbidden_effects",
                "capabilities",
            }
        )
        return cls(
            goal_id=str(payload.get("goal_id", "")),
            prism_id=str(payload.get("prism_id", "")),
            parent_prism_id=(
                str(payload["parent_prism_id"]) if payload.get("parent_prism_id") is not None else None
            ),
            slot_id=str(payload.get("slot_id", "")),
            task_id=str(payload.get("task_id", "")),
            owner_agent_id=str(payload.get("owner_agent_id", "")),
            attempt_id=str(payload.get("attempt_id", "")),
            repo_id=str(payload.get("repo_id", "")),
            base_commit=str(payload.get("base_commit", "")),
            context_generation=str(payload.get("context_generation", "")),
            context_graph_digest=str(payload.get("context_graph_digest", "")),
            task_facts_digest=str(payload.get("task_facts_digest", "")),
            plan_revision=str(payload.get("plan_revision", "")),
            change_set_hash=str(payload.get("change_set_hash", "")),
            verification_plan_hash=str(payload.get("verification_plan_hash", "")),
            lease_id=str(payload.get("lease_id", "")),
            fence_token=str(payload.get("fence_token", "")),
            authority_hash=str(payload.get("authority_hash", "")),
            expires_at_ns=int(payload.get("expires_at_ns", 0)),
            causal_parent=(
                str(payload["causal_parent"]) if payload.get("causal_parent") is not None else None
            ),
            trace_id=str(payload.get("trace_id", "")),
            created_at_ns=int(payload.get("created_at_ns", 0)),
            allowed_effects=tuple(payload.get("allowed_effects", ())),
            forbidden_effects=tuple(payload.get("forbidden_effects", ())),
            capabilities=tuple(payload.get("capabilities", ())),
            extensions={key: value for key, value in payload.items() if key not in known},
        )
