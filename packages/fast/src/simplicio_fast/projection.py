"""Deterministic, read-only projection envelopes for Semantic Compute.

Projection payloads are derived views.  Producers remain authoritative and
the envelope carries enough provenance for a consumer to reject stale or
cross-repository data without exposing mmap implementation details.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Mapping, Sequence


SCHEMA = "simplicio.fast.projection/v1"
STORE_SCHEMA = "simplicio.fast.projection-store/v1"
ENVELOPE_MANIFEST_SCHEMA = "simplicio.fast.projection-envelope/v1"
TYPE_MANIFEST_SCHEMA = "simplicio.fast.projection-type-manifest/v1"
CAPABILITIES_SCHEMA = "simplicio.fast.projection-capabilities/v1"
PROJECTION_TYPES = frozenset({"code", "knowledge", "operations"})
_FORBIDDEN_KEYS = frozenset({"offset", "mmap_offset", "address", "pointer"})
_MAX_ENCODED_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 32
_MAX_ITEMS = 100_000
_MAX_TEXT = 4096


class ProjectionError(ValueError):
    """Raised when a projection envelope is malformed or untrusted."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical(value: Any) -> bytes:
    _validate_json_object_keys(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ProjectionError("payload_not_json") from error
    if len(encoded) > _MAX_ENCODED_BYTES:
        raise ProjectionError("projection_size_limit")
    return encoded


def _validate_json_object_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ProjectionError("payload_not_json")
        for child in value.values():
            _validate_json_object_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_json_object_keys(child)


def _reject_private_fields(value: Any, *, depth: int = 0, items: list[int] | None = None) -> None:
    if depth > _MAX_DEPTH:
        raise ProjectionError("projection_depth_limit")
    if items is None:
        items = [0]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ProjectionError("payload_not_json")
        items[0] += len(value)
        if _FORBIDDEN_KEYS.intersection(value):
            raise ProjectionError("projection_exposes_offset")
        for child in value.values():
            _reject_private_fields(child, depth=depth + 1, items=items)
    elif isinstance(value, (list, tuple)):
        items[0] += len(value)
        if items[0] > _MAX_ITEMS:
            raise ProjectionError("projection_item_limit")
        for child in value:
            _reject_private_fields(child, depth=depth + 1, items=items)
    elif isinstance(value, str) and len(value) > _MAX_TEXT:
        raise ProjectionError("projection_text_limit")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectionEnvelope:
    """A typed, content-addressed read model with opaque stable provenance."""

    projection_type: str
    producer: str
    producer_schema: str
    generation: str
    stable_handle: str
    payload: Mapping[str, Any]
    payload_sha256: str
    schema_version: str = "1.0"
    projection_type_version: str = "1.0"
    producer_version: str = "unknown"
    repository_scope: str = "*"
    tenant_scope: str = "*"
    domain_scope: str = "*"
    source_generation: str = ""
    projection_generation: str = ""
    config_fingerprint: str = ""
    toolchain_fingerprint: str = ""
    parser_fingerprint: str = ""
    stable_handles: tuple[str, ...] = ()
    capabilities_required: tuple[str, ...] = ()
    budgets: Mapping[str, int] | None = None
    truncation_reasons: tuple[str, ...] = ()
    parent_generation: str | None = None
    base_generation: str | None = None
    delta_generation: str | None = None
    tombstones: tuple[str, ...] = ()
    completeness: str = "complete"
    fidelity: str = "exact"
    observed_sequence: str = ""
    conformance_digest: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.projection_type, "projection_type"),
            (self.producer, "producer"),
            (self.producer_schema, "producer_schema"),
            (self.generation, "generation"),
            (self.stable_handle, "stable_handle"),
            (self.schema_version, "schema_version"),
            (self.projection_type_version, "projection_type_version"),
            (self.producer_version, "producer_version"),
            (self.repository_scope, "repository_scope"),
            (self.tenant_scope, "tenant_scope"),
            (self.domain_scope, "domain_scope"),
            (self.source_generation, "source_generation"),
            (self.projection_generation, "projection_generation"),
            (self.completeness, "completeness"),
            (self.fidelity, "fidelity"),
        ):
            _validate_text(value, name)
        if self.projection_type not in PROJECTION_TYPES:
            raise ProjectionError("projection_type_unsupported")
        if not isinstance(self.payload, Mapping):
            raise ProjectionError("payload_invalid")
        _reject_private_fields(self.payload)
        _validate_sha256_digest(self.payload_sha256, "payload_sha256")
        if self.payload_sha256 != _digest(self.payload):
            raise ProjectionError("payload_digest_mismatch")
        stable_handles = _validate_sequence(self.stable_handles, "stable_handles")
        if not stable_handles or self.stable_handle not in stable_handles:
            raise ProjectionError("stable_handles_invalid")
        for value, name in (
            (self.config_fingerprint, "config_fingerprint"),
            (self.toolchain_fingerprint, "toolchain_fingerprint"),
            (self.parser_fingerprint, "parser_fingerprint"),
            (self.observed_sequence, "observed_sequence"),
            (self.conformance_digest, "conformance_digest"),
        ):
            _validate_optional_text(value, name)
        for value, name in (
            (self.parent_generation, "parent_generation"),
            (self.base_generation, "base_generation"),
            (self.delta_generation, "delta_generation"),
        ):
            if value is not None:
                _validate_optional_text(value, name)
        capabilities_required = _validate_sequence(self.capabilities_required, "capabilities_required")
        truncation_reasons = _validate_sequence(self.truncation_reasons, "truncation_reasons")
        tombstones = _validate_sequence(self.tombstones, "tombstones")
        if self.budgets is not None and (
            not isinstance(self.budgets, Mapping)
            or any(
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in self.budgets.items()
            )
        ):
            raise ProjectionError("budgets_invalid")
        object.__setattr__(self, "payload", deepcopy(self.payload))
        object.__setattr__(self, "stable_handles", stable_handles)
        object.__setattr__(self, "capabilities_required", capabilities_required)
        object.__setattr__(self, "truncation_reasons", truncation_reasons)
        object.__setattr__(self, "tombstones", tombstones)
        if self.budgets is not None:
            object.__setattr__(self, "budgets", dict(self.budgets))

    @classmethod
    def create(
        cls,
        projection_type: str,
        *,
        producer: str,
        producer_schema: str,
        generation: str,
        stable_handle: str,
        payload: Mapping[str, Any],
        schema_version: str = "1.0",
        projection_type_version: str = "1.0",
        producer_version: str = "unknown",
        repository_scope: str = "*",
        tenant_scope: str = "*",
        domain_scope: str = "*",
        source_generation: str | None = None,
        projection_generation: str | None = None,
        config_fingerprint: str = "",
        toolchain_fingerprint: str = "",
        parser_fingerprint: str = "",
        stable_handles: Sequence[str] | None = None,
        capabilities_required: Sequence[str] = (),
        budgets: Mapping[str, int] | None = None,
        truncation_reasons: Sequence[str] = (),
        parent_generation: str | None = None,
        base_generation: str | None = None,
        delta_generation: str | None = None,
        tombstones: Sequence[str] = (),
        completeness: str = "complete",
        fidelity: str = "exact",
        observed_sequence: str = "",
        conformance_digest: str = "",
    ) -> "ProjectionEnvelope":
        _validate_text(projection_type, "projection_type")
        if projection_type not in PROJECTION_TYPES:
            raise ProjectionError("projection_type_unsupported")
        for value, name in (
            (schema_version, "schema_version"),
            (projection_type_version, "projection_type_version"),
            (producer, "producer"),
            (producer_schema, "producer_schema"),
            (generation, "generation"),
            (stable_handle, "stable_handle"),
        ):
            _validate_text(value, name)
        if not isinstance(payload, Mapping):
            raise ProjectionError("payload_invalid")
        normalized = dict(payload)
        _reject_private_fields(normalized)
        for value, name in (
            (producer_version, "producer_version"),
            (repository_scope, "repository_scope"),
            (tenant_scope, "tenant_scope"),
            (domain_scope, "domain_scope"),
            (completeness, "completeness"),
            (fidelity, "fidelity"),
        ):
            _validate_text(value, name)
        for value, name in (
            (
                source_generation if source_generation is not None else generation,
                "source_generation",
            ),
            (
                projection_generation
                if projection_generation is not None
                else generation,
                "projection_generation",
            ),
            (config_fingerprint, "config_fingerprint"),
            (toolchain_fingerprint, "toolchain_fingerprint"),
            (parser_fingerprint, "parser_fingerprint"),
            (observed_sequence, "observed_sequence"),
            (conformance_digest, "conformance_digest"),
        ):
            _validate_optional_text(value, name)
        for value, name in (
            (parent_generation, "parent_generation"),
            (base_generation, "base_generation"),
            (delta_generation, "delta_generation"),
        ):
            if value is not None:
                _validate_optional_text(value, name)
        resolved_stable_handles = (
            tuple(stable_handles) if stable_handles is not None else (stable_handle,)
        )
        _validate_sequence(resolved_stable_handles, "stable_handles")
        if budgets is not None and (
            not isinstance(budgets, Mapping)
            or any(
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in budgets.items()
            )
        ):
            raise ProjectionError("budgets_invalid")
        for value, name in ((capabilities_required, "capabilities_required"), (truncation_reasons, "truncation_reasons"), (tombstones, "tombstones")):
            _validate_sequence(value, name)
        return cls(
            projection_type=projection_type,
            producer=producer,
            producer_schema=producer_schema,
            generation=generation,
            stable_handle=stable_handle,
            payload=normalized,
            payload_sha256=_digest(normalized),
            schema_version=schema_version,
            projection_type_version=projection_type_version,
            producer_version=producer_version,
            repository_scope=repository_scope,
            tenant_scope=tenant_scope,
            domain_scope=domain_scope,
            source_generation=(
                source_generation if source_generation is not None else generation
            ),
            projection_generation=(
                projection_generation
                if projection_generation is not None
                else generation
            ),
            config_fingerprint=config_fingerprint,
            toolchain_fingerprint=toolchain_fingerprint,
            parser_fingerprint=parser_fingerprint,
            stable_handles=resolved_stable_handles,
            capabilities_required=tuple(capabilities_required),
            budgets=dict(budgets) if budgets is not None else None,
            truncation_reasons=tuple(truncation_reasons),
            parent_generation=parent_generation,
            base_generation=base_generation,
            delta_generation=delta_generation,
            tombstones=tuple(tombstones),
            completeness=completeness,
            fidelity=fidelity,
            observed_sequence=observed_sequence,
            conformance_digest=conformance_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "projection_type": self.projection_type,
            "producer": self.producer,
            "producer_schema": self.producer_schema,
            "generation": self.generation,
            "stable_handle": self.stable_handle,
            "payload": dict(self.payload),
            "payload_sha256": self.payload_sha256,
            "schema_version": self.schema_version,
            "projection_type_version": self.projection_type_version,
            "producer_version": self.producer_version,
            "repository_scope": self.repository_scope,
            "tenant_scope": self.tenant_scope,
            "domain_scope": self.domain_scope,
            "source_generation": self.source_generation,
            "projection_generation": self.projection_generation,
            "config_fingerprint": self.config_fingerprint,
            "toolchain_fingerprint": self.toolchain_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "stable_handles": list(self.stable_handles),
            "capabilities_required": list(self.capabilities_required),
            "budgets": dict(self.budgets) if self.budgets is not None else None,
            "truncation_reasons": list(self.truncation_reasons),
            "parent_generation": self.parent_generation,
            "base_generation": self.base_generation,
            "delta_generation": self.delta_generation,
            "tombstones": list(self.tombstones),
            "completeness": self.completeness,
            "fidelity": self.fidelity,
            "observed_sequence": self.observed_sequence,
            "conformance_digest": self.conformance_digest,
        }

    def encode(self) -> bytes:
        return _canonical(self.to_dict()) + b"\n"

    @classmethod
    def decode(cls, raw: bytes) -> "ProjectionEnvelope":
        if not isinstance(raw, (bytes, bytearray)):
            raise ProjectionError("projection_invalid_json")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectionError("projection_invalid_json") from error
        if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
            raise ProjectionError("projection_schema_unsupported")
        payload = value.get("payload")
        expected = value.get("payload_sha256")
        if not isinstance(expected, str):
            raise ProjectionError("payload_digest_missing")
        result = cls.create(
            value.get("projection_type", ""),
            producer=value.get("producer", ""),
            producer_schema=value.get("producer_schema", ""),
            generation=value.get("generation", ""),
            stable_handle=value.get("stable_handle", ""),
            payload=payload if isinstance(payload, Mapping) else {},
            schema_version=value.get("schema_version", "1.0"),
            projection_type_version=value.get("projection_type_version", "1.0"),
            producer_version=value.get("producer_version", "unknown"),
            repository_scope=value.get("repository_scope", "*"),
            tenant_scope=value.get("tenant_scope", "*"),
            domain_scope=value.get("domain_scope", "*"),
            source_generation=value.get("source_generation"),
            projection_generation=value.get("projection_generation"),
            config_fingerprint=value.get("config_fingerprint", ""),
            toolchain_fingerprint=value.get("toolchain_fingerprint", ""),
            parser_fingerprint=value.get("parser_fingerprint", ""),
            stable_handles=value.get("stable_handles", ()),
            capabilities_required=value.get("capabilities_required", ()),
            budgets=value.get("budgets"),
            truncation_reasons=value.get("truncation_reasons", ()),
            parent_generation=value.get("parent_generation"),
            base_generation=value.get("base_generation"),
            delta_generation=value.get("delta_generation"),
            tombstones=value.get("tombstones", ()),
            completeness=value.get("completeness", "complete"),
            fidelity=value.get("fidelity", "exact"),
            observed_sequence=value.get("observed_sequence", ""),
            conformance_digest=value.get("conformance_digest", ""),
        )
        if payload is not None and not isinstance(payload, Mapping):
            raise ProjectionError("payload_invalid")
        if result.payload_sha256 != expected:
            raise ProjectionError("payload_digest_mismatch")
        return result


def contract_manifest() -> dict[str, Any]:
    """Return the machine-readable, dependency-free v1 contract registry."""
    return {
        "schema": ENVELOPE_MANIFEST_SCHEMA,
        "envelope": {
            "schema": SCHEMA,
            "major": 1,
            "minor": 0,
            "required": [
                "schema",
                "projection_type",
                "producer",
                "producer_schema",
                "generation",
                "stable_handle",
                "payload",
                "payload_sha256",
                "schema_version",
                "projection_type_version",
                "producer_version",
                "repository_scope",
                "tenant_scope",
                "domain_scope",
                "source_generation",
                "projection_generation",
                "stable_handles",
                "capabilities_required",
                "completeness",
                "fidelity",
            ],
        },
        "type_manifest": {
            "schema": TYPE_MANIFEST_SCHEMA,
            "types": sorted(PROJECTION_TYPES),
            "versions": {name: "1.0" for name in sorted(PROJECTION_TYPES)},
        },
        "capabilities": {
            "schema": CAPABILITIES_SCHEMA,
            "required": ["projection.decode.v1", "projection.digest.sha256"],
        },
        "limits": {
            "max_encoded_bytes": _MAX_ENCODED_BYTES,
            "max_depth": _MAX_DEPTH,
            "max_items": _MAX_ITEMS,
            "max_text": _MAX_TEXT,
        },
        "reason_codes": sorted({
            "projection_schema_unsupported", "projection_type_unsupported",
            "payload_digest_missing", "payload_digest_mismatch", "projection_size_limit",
            "projection_depth_limit", "projection_item_limit", "projection_exposes_offset",
            "projection_scope_mismatch", "projection_capability_missing",
        }),
        "compatibility": {
            "unknown_major": "reject",
            "unknown_optional_minor": "preserve_or_reject_by_manifest",
            "missing_required_capability": "reject",
            "digest_mismatch": "reject",
            "scope_mismatch": "reject",
        },
    }


class ProjectionStore:
    """In-memory derived projection index with explicit incremental receipts.

    The store is intentionally not a source database: callers supply complete
    envelopes from an authoritative producer, and the store only keeps the
    latest read model for one repository scope.
    """

    def __init__(self, repository: str) -> None:
        _validate_text(repository, "repository")
        self.repository = repository
        self._records: dict[str, ProjectionEnvelope] = {}
        self._generation: str | None = None
        self._lock = RLock()

    @property
    def generation(self) -> str | None:
        with self._lock:
            return self._generation

    def publish(self, envelope: ProjectionEnvelope) -> None:
        if not isinstance(envelope, ProjectionEnvelope):
            raise ProjectionError("projection_envelope_invalid")
        with self._lock:
            declared_repository = envelope.payload.get("repository")
            if declared_repository is not None and declared_repository != self.repository:
                raise ProjectionError("projection_repository_mismatch")
            if self._generation is not None and envelope.generation != self._generation:
                raise ProjectionError("projection_generation_stale")
            previous = self._records.get(envelope.stable_handle)
            if previous is not None and previous.payload_sha256 != envelope.payload_sha256:
                raise ProjectionError("projection_handle_conflict")
            self._generation = envelope.generation
            self._records[envelope.stable_handle] = envelope

    def apply_delta(
        self,
        generation: str,
        *,
        base_generation: str | None = None,
        changed: tuple[ProjectionEnvelope, ...] = (),
        deleted_handles: tuple[str, ...] = (),
        closure_handles: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        _validate_text(generation, "generation")
        if base_generation is not None:
            _validate_text(base_generation, "base_generation")
        _validate_projection_sequence(changed, "changed")
        _validate_sequence(deleted_handles, "deleted_handles")
        _validate_sequence(closure_handles, "closure_handles")
        with self._lock:
            generation_swap = (
                self._generation is not None and generation != self._generation
            )
            if generation_swap and base_generation != self._generation:
                raise ProjectionError("projection_generation_stale")
            if (
                not generation_swap
                and base_generation is not None
                and base_generation != self._generation
            ):
                raise ProjectionError("projection_generation_stale")
            changed_handles = sorted({item.stable_handle for item in changed})
            deleted = sorted(set(deleted_handles))
            if set(changed_handles).intersection(deleted):
                raise ProjectionError("projection_delta_conflict")
            next_records = dict(self._records)
            for item in changed:
                if item.generation != generation:
                    raise ProjectionError("projection_generation_stale")
                declared_repository = item.payload.get("repository")
                if declared_repository is not None and declared_repository != self.repository:
                    raise ProjectionError("projection_repository_mismatch")
                previous = next_records.get(item.stable_handle)
                if (
                    not generation_swap
                    and previous is not None
                    and previous.payload_sha256 != item.payload_sha256
                ):
                    raise ProjectionError("projection_handle_conflict")
                next_records[item.stable_handle] = item
            for handle in deleted:
                next_records.pop(handle, None)
            self._records = next_records
            self._generation = generation
            closure = sorted(set(closure_handles).union(changed_handles, deleted))
            return {
                "schema": "simplicio.fast.projection-delta/v1",
                "repository": self.repository,
                "generation": generation,
                "base_generation": base_generation,
                "changed_handles": changed_handles,
                "deleted_handles": deleted,
                "closure_handles": closure,
                "projection_digest": _digest(self.snapshot()),
            }

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._records[key].to_dict() for key in sorted(self._records)
            ]

    def save(self, path: Path) -> dict[str, Any]:
        """Atomically persist this derived store without becoming an authority."""
        with self._lock:
            body = {
                "schema": STORE_SCHEMA,
                "repository": self.repository,
                "generation": self._generation,
                "records": self.snapshot(),
            }
            document = {"body": body, "store_sha256": _digest(body)}
            encoded = _canonical(document) + b"\n"
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
                ) as handle:
                    temporary = handle.name
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                temporary = None
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
            return {
                "schema": "simplicio.fast.projection-store-receipt/v1",
                "status": "saved",
                "repository": self.repository,
                "generation": self._generation,
                "path": str(path),
                "store_sha256": document["store_sha256"],
                "records": len(self._records),
            }

    @classmethod
    def load(cls, path: Path, repository: str) -> "ProjectionStore":
        """Load and verify a derived store for exactly one repository scope."""
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectionError("projection_store_invalid") from error
        if not isinstance(document, Mapping):
            raise ProjectionError("projection_store_invalid")
        body = document.get("body")
        if not isinstance(body, Mapping) or body.get("schema") != STORE_SCHEMA:
            raise ProjectionError("projection_store_schema_unsupported")
        if body.get("repository") != repository:
            raise ProjectionError("projection_repository_mismatch")
        if document.get("store_sha256") != _digest(body):
            raise ProjectionError("projection_store_digest_mismatch")
        records = body.get("records")
        if not isinstance(records, list):
            raise ProjectionError("projection_store_invalid")
        store = cls(repository)
        for record in records:
            if not isinstance(record, Mapping):
                raise ProjectionError("projection_store_invalid")
            store.publish(ProjectionEnvelope.decode(_canonical(record)))
        if body.get("generation") != store.generation:
            raise ProjectionError("projection_generation_mismatch")
        return store


def _validate_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError(f"{field}_invalid")


def _validate_optional_text(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ProjectionError(f"{field}_invalid")


def _validate_sha256_digest(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != len("sha256:") + 64
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ProjectionError(f"{field}_invalid")


def _validate_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProjectionError(f"{field}_invalid")
    if len(value) > _MAX_ITEMS or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProjectionError(f"{field}_invalid")
    return tuple(value)


def _validate_projection_sequence(value: object, field: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProjectionError(f"{field}_invalid")
    if len(value) > _MAX_ITEMS or any(
        not isinstance(item, ProjectionEnvelope) for item in value
    ):
        raise ProjectionError(f"{field}_invalid")


__all__ = [
    "PROJECTION_TYPES",
    "CAPABILITIES_SCHEMA",
    "ENVELOPE_MANIFEST_SCHEMA",
    "ProjectionEnvelope",
    "ProjectionError",
    "ProjectionStore",
    "SCHEMA",
    "STORE_SCHEMA",
    "TYPE_MANIFEST_SCHEMA",
    "contract_manifest",
]
