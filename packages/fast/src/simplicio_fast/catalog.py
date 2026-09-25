"""Verified semantic handles for the Python catalog reference implementation.

The catalog keeps the full Mapper SHA-256 as identity and derives a short alias
only inside the repository/generation scope. Its on-disk representation is a
bounded binary record stream; JSON is reserved for CLI receipts and projections.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA = "simplicio.fast.address-catalog/v1"
MAGIC = b"SFACAT01"
MAX_CATALOG_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 1_000_000
STATES = {"active", "superseded", "tombstoned", "held"}
NAMESPACES = {
    "file",
    "symbol",
    "relation",
    "span",
    "test",
    "plan",
    "precedent",
    "receipt",
    "skill",
}
_SHA256 = __import__("re").compile(r"^[0-9a-f]{64}$")


class CatalogResolutionError(ValueError):
    """A handle could not be resolved without violating a catalog guard."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    namespace: str
    canonical_id: str
    handle: str
    repository: str
    generation: str
    segment_id: str
    payload: bytes
    payload_sha256: str
    source_sha256: str
    state: str

    def record(self, *, include_payload: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "namespace": self.namespace,
            "canonical_id": self.canonical_id,
            "handle": self.handle,
            "repository": self.repository,
            "generation": self.generation,
            "segment_id": self.segment_id,
            "payload_length": len(self.payload),
            "payload_sha256": self.payload_sha256,
            "source_sha256": self.source_sha256,
            "state": self.state,
        }
        if include_payload:
            result["payload"] = self.payload
        return result


class AddressCatalog:
    """In-memory catalog with a compact binary persistence boundary."""

    def __init__(self, repository: str | Path, generation: str) -> None:
        self.repository = str(Path(repository).resolve())
        if not generation:
            raise ValueError("generation must not be empty")
        self.generation = generation
        self._by_handle: dict[str, CatalogEntry] = {}
        self._by_identity: dict[tuple[str, str], CatalogEntry] = {}
        self._collisions = 0

    @staticmethod
    def _validate_sha(value: str, field: str) -> None:
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")

    def _make_handle(self, namespace: str, canonical_id: str) -> str:
        material = "|".join(
            (SCHEMA, self.repository, self.generation, namespace, canonical_id)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]

    def register(
        self,
        namespace: str,
        canonical_id: str,
        payload: bytes,
        *,
        source_sha256: str,
        segment_id: str = "default",
        state: str = "active",
    ) -> CatalogEntry:
        if namespace not in NAMESPACES:
            raise ValueError(f"unsupported catalog namespace: {namespace}")
        self._validate_sha(canonical_id, "canonical_id")
        self._validate_sha(source_sha256, "source_sha256")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not segment_id:
            raise ValueError("segment_id must not be empty")
        if state not in STATES:
            raise ValueError(f"unsupported catalog state: {state}")
        identity = (namespace, canonical_id)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        existing = self._by_identity.get(identity)
        if existing is not None:
            if (
                existing.payload_sha256 != payload_sha256
                or existing.source_sha256 != source_sha256
            ):
                raise CatalogResolutionError(
                    "canonical_id_reuse",
                    "canonical Mapper ID cannot silently point at a new payload",
                )
            return existing
        handle = self._make_handle(namespace, canonical_id)
        occupant = self._by_handle.get(handle)
        if occupant is not None and occupant.canonical_id != canonical_id:
            self._collisions += 1
            raise CatalogResolutionError(
                "handle_collision", f"handle collision for {handle}"
            )
        entry = CatalogEntry(
            namespace=namespace,
            canonical_id=canonical_id,
            handle=handle,
            repository=self.repository,
            generation=self.generation,
            segment_id=segment_id,
            payload=payload,
            payload_sha256=payload_sha256,
            source_sha256=source_sha256,
            state=state,
        )
        self._by_handle[handle] = entry
        self._by_identity[identity] = entry
        return entry

    def resolve(
        self,
        handle: str,
        *,
        repository: str | Path | None = None,
        generation: str | None = None,
        namespace: str | None = None,
        payload_sha256: str | None = None,
    ) -> CatalogEntry:
        entry = self._by_handle.get(handle)
        if entry is None:
            raise CatalogResolutionError(
                "handle_not_found", f"unknown catalog handle: {handle}"
            )
        if (
            repository is not None
            and str(Path(repository).resolve()) != entry.repository
        ):
            raise CatalogResolutionError(
                "cross_repo_handle", "handle belongs to another repository"
            )
        if generation is not None and generation != entry.generation:
            raise CatalogResolutionError(
                "stale_generation", "handle belongs to another generation"
            )
        if namespace is not None and namespace != entry.namespace:
            raise CatalogResolutionError(
                "namespace_mismatch", "handle namespace does not match"
            )
        if entry.state != "active":
            raise CatalogResolutionError(
                entry.state, f"handle is not active: {entry.state}"
            )
        if payload_sha256 is not None and payload_sha256 != entry.payload_sha256:
            raise CatalogResolutionError(
                "payload_digest_mismatch", "payload digest does not match"
            )
        if hashlib.sha256(entry.payload).hexdigest() != entry.payload_sha256:
            raise CatalogResolutionError(
                "payload_corrupt", "catalog payload digest is invalid"
            )
        return entry

    def resolve_many(
        self, handles: Iterable[str], **guards: object
    ) -> list[CatalogEntry]:
        return [self.resolve(handle, **guards) for handle in handles]

    def resolve_many_bounded(
        self,
        handles: Iterable[str],
        *,
        max_entries: int = 256,
        max_bytes: int = 1 * 1024 * 1024,
        **guards: object,
    ) -> dict[str, object]:
        """Resolve verified handles without exceeding materialization budgets."""
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("max_entries and max_bytes must be positive")
        references: list[dict[str, object]] = []
        materialized: list[dict[str, object]] = []
        bytes_materialized = 0
        truncated = False
        for handle in handles:
            if len(references) >= max_entries:
                truncated = True
                break
            entry = self.resolve(handle, **guards)
            if bytes_materialized + len(entry.payload) > max_bytes:
                truncated = True
                break
            references.append(
                {
                    "handle": entry.handle,
                    "namespace": entry.namespace,
                    "canonical_id": entry.canonical_id,
                    "generation": entry.generation,
                    "payload_length": len(entry.payload),
                    "payload_sha256": entry.payload_sha256,
                }
            )
            materialized.append({"handle": entry.handle, "payload": entry.payload})
            bytes_materialized += len(entry.payload)
        return {
            "schema": "simplicio.fast.address-resolution/v1",
            "repository": self.repository,
            "generation": self.generation,
            "references": references,
            "materialized": materialized,
            "entries_materialized": len(materialized),
            "bytes_materialized": bytes_materialized,
            "truncated": truncated,
            "reason_code": "resolution_bounded" if truncated else "resolution_complete",
        }

    def tombstone(self, handle: str, *, state: str = "tombstoned") -> CatalogEntry:
        if state not in {"superseded", "tombstoned", "held"}:
            raise ValueError("tombstone state must be superseded, tombstoned or held")
        entry = self._by_handle.get(handle)
        if entry is None:
            raise CatalogResolutionError(
                "handle_not_found", f"unknown catalog handle: {handle}"
            )
        replacement = CatalogEntry(
            namespace=entry.namespace,
            canonical_id=entry.canonical_id,
            handle=entry.handle,
            repository=entry.repository,
            generation=entry.generation,
            segment_id=entry.segment_id,
            payload=entry.payload,
            payload_sha256=entry.payload_sha256,
            source_sha256=entry.source_sha256,
            state=state,
        )
        self._by_handle[handle] = replacement
        self._by_identity[(entry.namespace, entry.canonical_id)] = replacement
        return replacement

    def stat(self) -> dict[str, object]:
        by_state = {state: 0 for state in STATES}
        by_namespace = {namespace: 0 for namespace in NAMESPACES}
        for entry in self._by_handle.values():
            by_state[entry.state] += 1
            by_namespace[entry.namespace] += 1
        return {
            "schema": SCHEMA,
            "repository": self.repository,
            "generation": self.generation,
            "entries": len(self._by_handle),
            "handles": len(self._by_handle),
            "collisions": self._collisions,
            "by_state": by_state,
            "by_namespace": by_namespace,
        }

    def verify(self) -> dict[str, object]:
        invalid: list[str] = []
        for entry in self._by_handle.values():
            if (
                entry.repository != self.repository
                or entry.generation != self.generation
            ):
                invalid.append(entry.handle)
                continue
            if hashlib.sha256(entry.payload).hexdigest() != entry.payload_sha256:
                invalid.append(entry.handle)
        return {
            **self.stat(),
            "status": "valid" if not invalid else "invalid",
            "invalid_handles": invalid,
        }

    def to_bytes(self) -> bytes:
        repository = self.repository.encode("utf-8")
        generation = self.generation.encode("utf-8")
        if len(repository) > 65535 or len(generation) > 65535:
            raise ValueError("catalog metadata is too long")
        output = bytearray(MAGIC)
        output.extend(
            struct.pack(">HHI", len(repository), len(generation), len(self._by_handle))
        )
        output.extend(repository)
        output.extend(generation)
        for entry in sorted(self._by_handle.values(), key=lambda item: item.handle):
            fields = (
                entry.namespace.encode("utf-8"),
                entry.canonical_id.encode("ascii"),
                entry.handle.encode("ascii"),
                entry.segment_id.encode("utf-8"),
                entry.payload_sha256.encode("ascii"),
                entry.source_sha256.encode("ascii"),
                entry.state.encode("ascii"),
                entry.payload,
            )
            if (
                any(len(field) > 65535 for field in fields[:-1])
                or len(entry.payload) > 0xFFFFFFFF
            ):
                raise ValueError("catalog record is too large")
            output.extend(
                struct.pack(
                    ">7H I", *(len(field) for field in fields[:-1]), len(entry.payload)
                )
            )
            for field in fields[:-1]:
                output.extend(field)
            output.extend(entry.payload)
        return bytes(output)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        repository: str | Path | None = None,
        generation: str | None = None,
    ) -> "AddressCatalog":
        if len(data) > MAX_CATALOG_BYTES or len(data) < len(MAGIC) + 8:
            raise ValueError("catalog size is outside supported bounds")
        cursor = 0

        def take(length: int) -> bytes:
            nonlocal cursor
            if length < 0 or cursor + length > len(data):
                raise ValueError("truncated catalog record")
            value = data[cursor : cursor + length]
            cursor += length
            return value

        if take(len(MAGIC)) != MAGIC:
            raise ValueError("invalid catalog magic")
        repository_length, generation_length, count = struct.unpack(">HHI", take(8))
        if count > MAX_RECORDS:
            raise ValueError("catalog record count exceeds limit")
        stored_repository = take(repository_length).decode("utf-8")
        stored_generation = take(generation_length).decode("utf-8")
        catalog = cls(repository or stored_repository, generation or stored_generation)
        if (
            catalog.repository != str(Path(stored_repository).resolve())
            or catalog.generation != stored_generation
        ):
            raise CatalogResolutionError(
                "catalog_scope_mismatch", "catalog scope does not match requested scope"
            )
        for _ in range(count):
            lengths = struct.unpack(">7H I", take(18))
            (
                namespace,
                canonical_id,
                handle,
                segment_id,
                payload_sha256,
                source_sha256,
                state,
            ) = (
                take(lengths[index]).decode("utf-8" if index in {0, 3} else "ascii")
                for index in range(7)
            )
            payload = take(lengths[7])
            expected_handle = catalog._make_handle(namespace, canonical_id)
            if handle != expected_handle:
                raise CatalogResolutionError(
                    "handle_digest_mismatch", f"invalid handle for {canonical_id}"
                )
            entry = catalog.register(
                namespace,
                canonical_id,
                payload,
                source_sha256=source_sha256,
                segment_id=segment_id,
                state=state,
            )
            if entry.handle != handle or entry.payload_sha256 != payload_sha256:
                raise CatalogResolutionError(
                    "catalog_digest_mismatch", "catalog record digest mismatch"
                )
        if cursor != len(data):
            raise ValueError("trailing bytes after catalog records")
        return catalog

    def save(self, path: str | Path) -> dict[str, object]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(self.to_bytes())
        os.replace(temporary, target)
        return {
            **self.verify(),
            "path": str(target.resolve()),
            "bytes": target.stat().st_size,
        }

    @classmethod
    def load(cls, path: str | Path, **scope: object) -> "AddressCatalog":
        return cls.from_bytes(Path(path).read_bytes(), **scope)
