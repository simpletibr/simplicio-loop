"""Pure, versioned virtual custodian addresses for Simplicio Fast."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Literal, Mapping


ADDRESS_SCHEMA = "simplicio.fast.custodian-address/v1"
CATALOG_SCHEMA = "simplicio.fast.custodian-catalog/v1"
RESOLUTION_SCHEMA = "simplicio.fast.custodian-resolution/v1"
VIRTUAL_POINTER_KIND = "virtual-pointer"

CustodianRole = Literal[
    "IndexGenerationSteward",
    "CacheIntegritySentinel",
    "KnowledgeFederationSteward",
    "PythonRustParityAuditor",
]

_ROLE_NAMES: tuple[CustodianRole, ...] = (
    "IndexGenerationSteward",
    "CacheIntegritySentinel",
    "KnowledgeFederationSteward",
    "PythonRustParityAuditor",
)
_Metadata = tuple[str, ...]


def _validate_metadata(name: str, value: object) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a non-empty tuple")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class CustodianAddressV1:
    """An immutable virtual pointer; it names a role but does not dispatch it."""

    role: CustodianRole
    endpoint: str
    owner: str
    capabilities: _Metadata
    inputs: _Metadata
    outputs: _Metadata
    invariants: _Metadata
    schema: ClassVar[str] = ADDRESS_SCHEMA
    pointer_kind: Literal["virtual-pointer"] = VIRTUAL_POINTER_KIND
    virtual: Literal[True] = True

    def __post_init__(self) -> None:
        if self.role not in _ROLE_NAMES:
            raise ValueError(f"unsupported custodian role: {self.role!r}")
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise ValueError("endpoint must be a non-empty string")
        expected_endpoint = f"virtual://simplicio-fast/{self.role}"
        if self.endpoint != expected_endpoint:
            raise ValueError("endpoint must be the stable virtual role endpoint")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValueError("owner must be a non-empty string")
        if self.pointer_kind != VIRTUAL_POINTER_KIND:
            raise ValueError("pointer_kind must be virtual-pointer")
        if self.virtual is not True:
            raise ValueError("virtual must be true")
        for name in ("capabilities", "inputs", "outputs", "invariants"):
            _validate_metadata(name, getattr(self, name))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe projection with stable field names and values."""
        return {
            "schema": self.schema,
            "pointer_kind": self.pointer_kind,
            "virtual": self.virtual,
            "role": self.role,
            "endpoint": self.endpoint,
            "owner": self.owner,
            "capabilities": list(self.capabilities),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "invariants": list(self.invariants),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


_ROLE_METADATA: tuple[
    tuple[CustodianRole, str, _Metadata, _Metadata, _Metadata, _Metadata], ...
] = (
    (
        "IndexGenerationSteward",
        "simplicio-fast/index",
        ("index-generation", "index-validation"),
        ("source-snapshot", "generation-contract"),
        ("generation-manifest", "index-receipt"),
        ("deterministic", "snapshot-bound", "no-dispatch"),
    ),
    (
        "CacheIntegritySentinel",
        "simplicio-fast/cache",
        ("cache-validation", "integrity-check"),
        ("cache-entry", "source-digest"),
        ("cache-verdict", "integrity-receipt"),
        ("digest-bound", "fail-closed", "no-mutation"),
    ),
    (
        "KnowledgeFederationSteward",
        "simplicio-fast/knowledge",
        ("knowledge-federation", "provenance-check"),
        ("knowledge-snapshot", "provenance-receipt"),
        ("federation-manifest", "provenance-receipt"),
        ("source-scoped", "provenance-preserving", "no-dispatch"),
    ),
    (
        "PythonRustParityAuditor",
        "simplicio-fast/parity",
        ("parity-audit", "contract-comparison"),
        ("python-contract", "rust-contract"),
        ("parity-verdict", "comparison-receipt"),
        ("read-only", "deterministic", "no-execution"),
    ),
)


def _build_catalog() -> tuple[CustodianAddressV1, ...]:
    return tuple(
        CustodianAddressV1(
            role=role,
            endpoint=f"virtual://simplicio-fast/{role}",
            owner=owner,
            capabilities=capabilities,
            inputs=inputs,
            outputs=outputs,
            invariants=invariants,
        )
        for role, owner, capabilities, inputs, outputs, invariants in _ROLE_METADATA
    )


CUSTODIAN_CATALOG: tuple[CustodianAddressV1, ...] = _build_catalog()
CUSTODIANS: Mapping[str, CustodianAddressV1] = MappingProxyType(
    {address.role: address for address in CUSTODIAN_CATALOG}
)
CUSTODIAN_ROLES: tuple[CustodianRole, ...] = _ROLE_NAMES


def custodian_catalog() -> tuple[CustodianAddressV1, ...]:
    """Return the deterministic catalog in its stable role order."""
    return CUSTODIAN_CATALOG


def resolve_custodian(role: object) -> dict[str, object]:
    """Resolve one virtual role without dispatching a worker or effect."""
    if not isinstance(role, str) or not role.strip():
        return {
            "schema": RESOLUTION_SCHEMA,
            "status": "rejected",
            "role": None,
            "address": None,
            "reason_code": "invalid_role",
            "dispatch": {"allowed": False, "reason_code": "virtual_pointer_only"},
        }
    address = CUSTODIANS.get(role)
    if address is None:
        return {
            "schema": RESOLUTION_SCHEMA,
            "status": "unavailable",
            "role": role,
            "address": None,
            "reason_code": "unknown_role",
            "dispatch": {"allowed": False, "reason_code": "virtual_pointer_only"},
        }
    return {
        "schema": RESOLUTION_SCHEMA,
        "status": "available",
        "role": address.role,
        "address": address.to_dict(),
        "reason_code": "catalog_match",
        "dispatch": {"allowed": False, "reason_code": "virtual_pointer_only"},
    }


def catalog_json() -> str:
    """Serialize the catalog deterministically as JSON-safe data."""
    return json.dumps(
        {
            "schema": CATALOG_SCHEMA,
            "custodians": [address.to_dict() for address in CUSTODIAN_CATALOG],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "RESOLUTION_SCHEMA",
    "ADDRESS_SCHEMA",
    "CATALOG_SCHEMA",
    "CUSTODIAN_CATALOG",
    "CUSTODIAN_ROLES",
    "CUSTODIANS",
    "CustodianAddressV1",
    "CustodianRole",
    "VIRTUAL_POINTER_KIND",
    "catalog_json",
    "custodian_catalog",
    "resolve_custodian",
]
