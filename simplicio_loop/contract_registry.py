"""Versioned cross-repository contract registry.

The loop is the coordination boundary for Mapper and Dev CLI.  This
module provides a small, dependency-light validator for the public envelopes
that cross that boundary.  It intentionally does not expose internal index
storage offsets or implementation handles.

The registry is data-driven: ``contracts/registry/v1/registry.json`` is the
source of truth for ownership, schema ids and compatibility policy.  Payload
validation uses ``jsonschema`` when installed and a deterministic structural
fallback otherwise, so the runtime package remains usable without optional
development dependencies.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

REGISTRY_ID = "simplicio.contract-registry/v1"
REGISTRY_VERSION = "1.0.0"
REASON_SCHEMA_UNKNOWN = "CONTRACT_SCHEMA_UNKNOWN"
REASON_SCHEMA_VERSION = "CONTRACT_SCHEMA_VERSION_INCOMPATIBLE"
REASON_GENERATION = "CONTRACT_GENERATION_MISMATCH"
REASON_FENCE = "CONTRACT_FENCE_MISMATCH"
REASON_HASH = "CONTRACT_CONTENT_HASH_MISMATCH"
REASON_IDEMPOTENCY = "CONTRACT_IDEMPOTENCY_KEY_MISSING"
REASON_INTERNAL_FIELD = "CONTRACT_INTERNAL_FIELD_FORBIDDEN"
REASON_INVALID = "CONTRACT_PAYLOAD_INVALID"

COMMON_REQUIRED = (
    "schema",
    "schema_version",
    "contract_id",
    "generation",
    "attempt",
    "fence",
    "idempotency_key",
    "content_hash",
    "producer",
    "created_at",
    "payload",
)

# These names are implementation details of an index's storage layout.  They
# must never become part of the public Mapper/Dev CLI/Loop protocol.
FORBIDDEN_INTERNAL_FIELDS = frozenset(
    {
        "offset",
        "offsets",
        "byte_offset",
        "segment_offset",
        "mmap_offset",
        "internal_offset",
        "posting_offset",
        "storage_offset",
        "vector_offset",
        "page_offset",
    }
)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


class ContractRegistryError(ValueError):
    """Base error for registry and envelope validation failures."""


class ContractValidationError(ContractRegistryError):
    """Raised when an envelope cannot be admitted to the public protocol."""

    def __init__(self, reason_code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details


@dataclass(frozen=True)
class ContractDescriptor:
    """Immutable descriptor published by the registry."""

    contract_id: str
    schema_id: str
    version: str
    owner: str
    producers: Tuple[str, ...]
    consumers: Tuple[str, ...]
    schema_path: str
    compatibility: str = "backward-compatible-additive"


def canonical_json(value: Any) -> bytes:
    """Return the bytes used for all protocol hashes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: Any) -> str:
    """Compute the stable content hash used by an envelope."""
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _parse_version(value: str) -> Tuple[int, int, int]:
    match = _VERSION_RE.match(str(value))
    if not match:
        raise ContractRegistryError("invalid semantic version: %s" % value)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _walk_forbidden(value: Any, path: str = "payload") -> Optional[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_INTERNAL_FIELDS:
                return "%s.%s" % (path, key_text)
            nested = _walk_forbidden(child, "%s.%s" % (path, key_text))
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            nested = _walk_forbidden(child, "%s[%d]" % (path, index))
            if nested:
                return nested
    return None


def _default_registry_path() -> Path:
    source_path = Path(__file__).resolve().parent.parent / "contracts" / "registry" / "v1" / "registry.json"
    if source_path.exists():
        return source_path
    # Wheels cannot address repository-root data files.  The package mirror is
    # byte-identical to the source registry and is included by package-data.
    return Path(__file__).resolve().parent / "_contracts" / "registry" / "v1" / "registry.json"


class ContractRegistry:
    """Load, inspect and validate the canonical cross-repository contracts."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _default_registry_path()
        try:
            self.document: Dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ContractRegistryError("registry not found: %s" % self.path) from exc
        except json.JSONDecodeError as exc:
            raise ContractRegistryError("registry is not valid JSON: %s" % self.path) from exc
        if self.document.get("registry") != REGISTRY_ID:
            raise ContractRegistryError("unexpected registry id")
        self._contracts: Dict[str, ContractDescriptor] = {}
        for registry_key, raw in self.document.get("contracts", {}).items():
            descriptor = ContractDescriptor(
                # The public contract id is the canonical schema id.  The
                # registry key remains a short ergonomic alias for callers.
                contract_id=str(raw["schema_id"]),
                schema_id=str(raw["schema_id"]),
                version=str(raw["version"]),
                owner=str(raw["owner"]),
                producers=tuple(str(value) for value in raw.get("producers", [])),
                consumers=tuple(str(value) for value in raw.get("consumers", [])),
                schema_path=str(raw["schema_path"]),
                compatibility=str(raw.get("compatibility", "backward-compatible-additive")),
            )
            self._contracts[registry_key] = descriptor
            self._contracts[descriptor.schema_id] = descriptor

    def all(self) -> Tuple[ContractDescriptor, ...]:
        unique: Dict[str, ContractDescriptor] = {}
        for descriptor in self._contracts.values():
            unique[descriptor.schema_id] = descriptor
        return tuple(unique.values())

    def get(self, contract_id: str) -> ContractDescriptor:
        try:
            return self._contracts[contract_id]
        except KeyError as exc:
            raise ContractValidationError(REASON_SCHEMA_UNKNOWN, "unknown contract: %s" % contract_id) from exc

    def schema_path(self, contract_id: str) -> Path:
        descriptor = self.get(contract_id)
        return self.path.parent / descriptor.schema_path

    def compatible(self, actual: str, expected: str, direction: str = "backward") -> bool:
        """Check semantic compatibility using the registry's major-version rule.

        ``backward`` means a newer consumer can read an older producer payload;
        ``forward`` means an older consumer can read a newer payload only when
        the producer stayed within the same major and did not remove fields.
        The registry records additive evolution, therefore both directions
        require equal major versions; minor/patch differences are accepted.
        """
        actual_v = _parse_version(actual)
        expected_v = _parse_version(expected)
        if actual_v[0] != expected_v[0]:
            return False
        if direction not in {"backward", "forward"}:
            raise ContractRegistryError("direction must be backward or forward")
        return True

    def make_envelope(
        self,
        contract_id: str,
        payload: Mapping[str, Any],
        *,
        generation: int,
        attempt: int,
        fence: str,
        idempotency_key: str,
        producer: str,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a deterministic public envelope for a contract payload."""
        descriptor = self.get(contract_id)
        envelope = {
            "schema": descriptor.schema_id,
            "schema_version": descriptor.version,
            "contract_id": descriptor.contract_id,
            "generation": int(generation),
            "attempt": int(attempt),
            "fence": str(fence),
            "idempotency_key": str(idempotency_key),
            "content_hash": content_hash(payload),
            "producer": str(producer),
            "created_at": created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "payload": dict(payload),
        }
        self.validate(envelope)
        return envelope

    def validate(
        self,
        envelope: Mapping[str, Any],
        *,
        expected_generation: Optional[int] = None,
        expected_fence: Optional[str] = None,
        expected_schema_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate an envelope and return a normalized copy.

        Errors carry stable ``reason_code`` values so callers can decide to
        retry, re-map, or reject without parsing human text.
        """
        missing = [field for field in COMMON_REQUIRED if field not in envelope]
        if missing:
            raise ContractValidationError(REASON_INVALID, "missing required fields", details=missing)
        contract_id = str(envelope.get("contract_id"))
        descriptor = self.get(contract_id)
        if envelope.get("schema") != descriptor.schema_id:
            raise ContractValidationError(REASON_SCHEMA_UNKNOWN, "schema id does not match contract", details=contract_id)
        actual_version = str(envelope.get("schema_version"))
        expected_version = expected_schema_version or descriptor.version
        if not self.compatible(actual_version, expected_version):
            raise ContractValidationError(REASON_SCHEMA_VERSION, "schema major version is incompatible", details={"actual": actual_version, "expected": expected_version})
        if expected_generation is not None and int(envelope["generation"]) != int(expected_generation):
            raise ContractValidationError(REASON_GENERATION, "generation does not match the pinned generation", details={"actual": envelope["generation"], "expected": expected_generation})
        if expected_fence is not None and str(envelope["fence"]) != str(expected_fence):
            raise ContractValidationError(REASON_FENCE, "fence does not match the active lease", details={"actual": envelope["fence"], "expected": expected_fence})
        if not str(envelope["idempotency_key"]).strip():
            raise ContractValidationError(REASON_IDEMPOTENCY, "idempotency_key must not be empty")
        forbidden = _walk_forbidden(envelope.get("payload"))
        if forbidden:
            raise ContractValidationError(REASON_INTERNAL_FIELD, "internal index field is not public: %s" % forbidden, details=forbidden)
        if str(envelope["content_hash"]) != content_hash(envelope["payload"]):
            raise ContractValidationError(REASON_HASH, "content_hash does not match payload")
        self._validate_payload_shape(contract_id, envelope["payload"])
        return dict(envelope)

    def _validate_payload_shape(self, contract_id: str, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            raise ContractValidationError(REASON_INVALID, "payload must be an object")
        schema_path = self.schema_path(contract_id)
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractRegistryError("schema unavailable for %s" % contract_id) from exc
        required = schema.get("payload_required", [])
        missing = [field for field in required if field not in payload]
        if missing:
            raise ContractValidationError(REASON_INVALID, "payload is missing required fields", details=missing)
        try:
            import jsonschema  # type: ignore
        except ImportError:
            return
        try:
            jsonschema.validate(payload, schema["payload_schema"])
        except Exception as exc:  # jsonschema.ValidationError without hard dependency
            raise ContractValidationError(REASON_INVALID, "payload failed JSON Schema validation", details=str(exc)) from exc


def load_registry(path: Optional[Path] = None) -> ContractRegistry:
    """Convenience factory used by integrations and tests."""
    return ContractRegistry(path)


__all__ = [
    "COMMON_REQUIRED",
    "ContractDescriptor",
    "ContractRegistry",
    "ContractRegistryError",
    "ContractValidationError",
    "FORBIDDEN_INTERNAL_FIELDS",
    "REGISTRY_ID",
    "REGISTRY_VERSION",
    "canonical_json",
    "content_hash",
    "load_registry",
]
