"""Canonical address-first Agent Fabric control plane (issue #765)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Callable, Mapping, Sequence

ADDRESS_SCHEMA = "simplicio.fabric-address/v1"
CAPABILITY_SCHEMA = "simplicio.fabric-capability/v1"
ENVELOPE_SCHEMA = "simplicio.fabric-envelope/v1"
RECEIPT_SCHEMA = "simplicio.fabric-dispatch-receipt/v1"
VERDICT_SCHEMA = "simplicio.fabric-verdict/v1"
ADDENDUM_SCHEMA = "simplicio.fabric-addendum/v1"
LEVELS = ("DECLARED", "BUILT", "PACKAGED", "BOUND", "DEFAULT", "E2E", "MEASURED")


class FabricError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class FabricCapability:
    name: str
    version: str
    level: str
    contract_hash: str

    def __post_init__(self) -> None:
        if not self.name or not self.version or not self.contract_hash or self.level not in LEVELS:
            raise FabricError("capability_invalid", self.name)

    def as_dict(self) -> dict[str, str]:
        return {"schema": CAPABILITY_SCHEMA, "name": self.name, "version": self.version,
                "level": self.level, "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class FabricAddress:
    project: str
    agent_id: str
    capability: FabricCapability
    generation: int
    route: str

    def __post_init__(self) -> None:
        if not self.project or not self.agent_id or not self.route or self.generation < 0:
            raise FabricError("address_invalid", self.agent_id)

    @property
    def address_id(self) -> str:
        return digest({"project": self.project, "agent_id": self.agent_id,
                       "capability": self.capability.as_dict(), "generation": self.generation,
                       "route": self.route})

    def as_dict(self) -> dict[str, Any]:
        return {"schema": ADDRESS_SCHEMA, "address_id": self.address_id,
                "project": self.project, "agent_id": self.agent_id,
                "capability": self.capability.as_dict(), "generation": self.generation,
                "route": self.route, "worker_state": "NOT_MATERIALIZED"}


class AddressRegistry:
    def __init__(self) -> None:
        self._addresses: dict[str, FabricAddress] = {}
        self.workers_materialized = 0

    def register(self, address: FabricAddress) -> str:
        previous = self._addresses.get(address.address_id)
        if previous and previous != address:
            raise FabricError("address_collision", address.address_id)
        self._addresses[address.address_id] = address
        return address.address_id

    def resolve(self, capability: str, *, minimum_level: str = "BOUND",
                project: str | None = None) -> FabricAddress:
        if minimum_level not in LEVELS:
            raise FabricError("capability_level_invalid", minimum_level)
        candidates = [
            item for item in self._addresses.values()
            if item.capability.name == capability
            and LEVELS.index(item.capability.level) >= LEVELS.index(minimum_level)
            and (project is None or item.project == project)
        ]
        if not candidates:
            raise FabricError("capability_not_bound", capability)
        candidates.sort(key=lambda item: (-item.generation, item.address_id))
        return candidates[0]

    def inspect(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.fabric-registry/v1",
            "addresses": [item.as_dict() for item in sorted(
                self._addresses.values(), key=lambda value: value.address_id
            )],
            "workers_materialized": self.workers_materialized,
        }


class HookwallAdapter:
    """Concrete pre/fire/post adapter; FabricController never invokes a worker directly."""

    def __init__(self, workspace: str,
                 pre_hook: Callable[[Mapping[str, Any]], Mapping[str, Any]],
                 post_hook: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]) -> None:
        self.workspace = workspace
        self.pre_hook = pre_hook
        self.post_hook = post_hook

    def __call__(self, fabric_envelope: Mapping[str, Any],
                 fire: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
        from .hookwall_gate import (
            ENVELOPE_SCHEMA as HW_ENVELOPE, RECEIPT_SCHEMA as HW_RECEIPT,
            validate_envelope as seal, validate_pre_decision, verify_post_receipt,
        )
        hw = seal({
            "schema": HW_ENVELOPE, "envelope_id": fabric_envelope["checksum"],
            "run_id": fabric_envelope["run_id"], "plan_id": fabric_envelope["plan_revision"],
            "source_hash": fabric_envelope["commit"], "policy_hash": fabric_envelope["policy_hash"],
            "idempotency_key": fabric_envelope["idempotency_key"],
            "workspace": self.workspace, "fence": fabric_envelope["fence"],
            "effect_set": ["process", "write"],
            "write_set": [".simplicio-loop/fabric/" + fabric_envelope["work_item_id"] + ".json"],
            "command": ["simplicio-dev-cli", "task", "--json"],
        })
        pre = dict(self.pre_hook(hw))
        validate_pre_decision(hw, pre)
        effect = dict(fire())
        mutation = {
            "schema": HW_RECEIPT, "envelope_id": hw["envelope_id"],
            "source_hash": hw["source_hash"], "policy_hash": hw["policy_hash"],
            "idempotency_key": hw["idempotency_key"], "fence": hw["fence"],
            "status": "verified", "effect_digest": digest(effect),
        }
        mutation["receipt_hash"] = digest(mutation)
        post = dict(self.post_hook(hw, mutation))
        evidence = verify_post_receipt(hw, pre, mutation, post)
        return {"status": "VERIFIED", "effect": effect, "hookwall_evidence": evidence}


def build_envelope(*, run_id: str, task_id: str, work_item_id: str, stage: str,
                   attempt: int, fence: str, plan_revision: str,
                   sender: FabricAddress, recipient: FabricAddress,
                   payload_handle: str, payload_hash: str, causal_parent: str,
                   sequence: int, scope: str, repo: str, commit: str, worktree: str,
                   policy_hash: str, ttl_seconds: float, expected_receipt: str,
                   evidence_handles: Sequence[str], reply_handle: str, priority: int,
                   resource_class: str) -> dict[str, Any]:
    if attempt < 1 or sequence < 1 or ttl_seconds <= 0:
        raise FabricError("envelope_invalid", "attempt/sequence/ttl")
    body = {
        "schema": ENVELOPE_SCHEMA, "run_id": run_id, "task_id": task_id,
        "work_item_id": work_item_id, "stage": stage, "attempt": attempt,
        "fence": fence, "plan_revision": plan_revision,
        "sender_address": sender.address_id, "recipient_address": recipient.address_id,
        "capability": recipient.capability.name,
        "capability_version": recipient.capability.version,
        "payload_handle": payload_handle, "payload_hash": payload_hash,
        "causal_parent": causal_parent, "sequence": sequence, "scope": scope,
        "repo": repo, "commit": commit, "worktree": worktree,
        "policy_hash": policy_hash, "deadline_ns": time.time_ns() + int(ttl_seconds * 1e9),
        "expected_receipt": expected_receipt, "evidence_handles": sorted(evidence_handles),
        "reply_handle": reply_handle, "priority": priority, "resource_class": resource_class,
    }
    if not all(body[key] not in ("", None) for key in body if key not in {"evidence_handles"}):
        raise FabricError("envelope_invalid", "required field missing")
    if resource_class in {"write", "build", "release"} and not any(
        str(item).startswith("quality://") for item in evidence_handles
    ):
        raise FabricError("quality_subgraph_missing", work_item_id)
    body["idempotency_key"] = digest({
        key: body[key] for key in ("run_id", "task_id", "work_item_id", "stage",
                                   "attempt", "fence", "plan_revision", "recipient_address",
                                   "payload_hash", "policy_hash")
    })
    body["checksum"] = digest(body)
    return body


def validate_envelope(envelope: Mapping[str, Any], registry: AddressRegistry,
                      *, current_fence: str, now_ns: int | None = None) -> FabricAddress:
    if envelope.get("schema") != ENVELOPE_SCHEMA:
        raise FabricError("envelope_schema_invalid", "")
    unsigned = dict(envelope)
    supplied = unsigned.pop("checksum", "")
    if supplied != digest(unsigned):
        raise FabricError("envelope_checksum_invalid", "")
    if envelope.get("fence") != current_fence:
        raise FabricError("envelope_cross_fence", "")
    if int(envelope.get("deadline_ns", 0)) <= (now_ns or time.time_ns()):
        raise FabricError("envelope_stale", "")
    recipient = registry._addresses.get(str(envelope.get("recipient_address")))
    if recipient is None:
        raise FabricError("recipient_unknown", "")
    if recipient.capability.name != envelope.get("capability"):
        raise FabricError("capability_mismatch", "")
    return recipient


class FabricController:
    """Loop-owned dispatch/recovery state. Physical execution is injected."""

    def __init__(self, registry: AddressRegistry, *, max_attempts: int = 3,
                 max_inflight: int = 20) -> None:
        if max_attempts < 1 or max_inflight < 1:
            raise ValueError("limits must be positive")
        self.registry = registry
        self.max_attempts = max_attempts
        self.max_inflight = max_inflight
        self._receipts: dict[str, dict[str, Any]] = {}
        self._attempts: dict[str, int] = {}
        self._inflight = 0
        self._addenda: list[dict[str, Any]] = []

    def fire(self, envelope: Mapping[str, Any], *, current_fence: str,
             hookwall: Callable[[Mapping[str, Any], Callable[[], Mapping[str, Any]]], Mapping[str, Any]],
             execute: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
        recipient = validate_envelope(envelope, self.registry, current_fence=current_fence)
        key = str(envelope["idempotency_key"])
        if key in self._receipts:
            return dict(self._receipts[key])
        work_item = str(envelope["work_item_id"])
        attempts = self._attempts.get(work_item, 0)
        if attempts >= self.max_attempts:
            raise FabricError("retry_exhausted", work_item)
        if self._inflight >= self.max_inflight:
            raise FabricError("fabric_backpressure", work_item)
        self._attempts[work_item] = attempts + 1
        self._inflight += 1
        materialized = False
        try:
            def worker() -> Mapping[str, Any]:
                nonlocal materialized
                materialized = True
                self.registry.workers_materialized += 1
                return execute(envelope)

            effect = dict(hookwall(envelope, worker))
            if not materialized:
                raise FabricError("hookwall_worker_not_fired", work_item)
            receipt = {
                "schema": RECEIPT_SCHEMA, "envelope_checksum": envelope["checksum"],
                "idempotency_key": key, "work_item_id": work_item,
                "executor_id": recipient.agent_id, "status": effect.get("status"),
                "effect_receipt": effect,
                "completion_authority": "LOOP_ONLY",
            }
            if receipt["status"] != "VERIFIED":
                raise FabricError("effect_unverified", work_item)
            receipt["receipt_digest"] = digest(receipt)
            self._receipts[key] = receipt
            return dict(receipt)
        except BaseException as exc:
            self.append_addendum(
                target_digest=envelope["checksum"], reason_code=getattr(exc, "reason_code", "EXECUTION_FAILED"),
                actor_id="gap-recovery", evidence_handles=("recovery://attempt",),
            )
            raise
        finally:
            self._inflight -= 1

    def append_addendum(self, *, target_digest: str, reason_code: str,
                        actor_id: str, evidence_handles: Sequence[str]) -> dict[str, Any]:
        previous = self._addenda[-1]["addendum_digest"] if self._addenda else "0" * 64
        value = {
            "schema": ADDENDUM_SCHEMA, "sequence": len(self._addenda) + 1,
            "previous_addendum_digest": previous, "target_digest": target_digest,
            "reason_code": reason_code, "actor_id": actor_id,
            "evidence_handles": sorted(evidence_handles),
        }
        value["addendum_digest"] = digest(value)
        self._addenda.append(value)
        return dict(value)

    def replay(self) -> dict[str, Any]:
        previous = "0" * 64
        for index, item in enumerate(self._addenda, 1):
            unsigned = dict(item)
            supplied = unsigned.pop("addendum_digest")
            if item["sequence"] != index or item["previous_addendum_digest"] != previous or digest(unsigned) != supplied:
                raise FabricError("addendum_chain_invalid", str(index))
            previous = supplied
        return {
            "schema": "simplicio.fabric-replay/v1", "attempts": dict(sorted(self._attempts.items())),
            "receipt_digests": sorted(item["receipt_digest"] for item in self._receipts.values()),
            "addenda": list(self._addenda), "completion_authority": "LOOP_ONLY",
        }


__all__ = ["AddressRegistry", "FabricAddress", "FabricCapability", "FabricController",
           "HookwallAdapter",
           "FabricError", "build_envelope", "validate_envelope", "digest"]
