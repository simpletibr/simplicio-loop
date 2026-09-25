"""Content-addressed validation facts and bounded affected-test selection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from threading import RLock
from typing import Any, Mapping, Sequence


CACHE_KEY_SCHEMA = "simplicio.fast.validation-cache-key/v1"
RESULT_SCHEMA = "simplicio.fast.validation-result/v1"
MAX_AFFECTED_TESTS = 100_000


class ValidationCacheError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _validate_string_sequence(value: object, reason: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or any(not isinstance(item, str) or not item for item in value):
        raise ValidationCacheError(reason)
    return tuple(value)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidationCacheError("cache_key_not_json") from error


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ValidationKey:
    source_merkle: str
    lockfiles_digest: str
    toolchain: str
    command: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    platform: str = "unknown"
    config_digest: str = ""
    fixture_digest: str = ""
    generation: str = ""
    producer_schema: str = "simplicio.fast.validation/v1"
    freshness_class: str = "normal"

    def __post_init__(self) -> None:
        if isinstance(self.command, list):
            object.__setattr__(self, "command", tuple(self.command))
        if isinstance(self.environment, (tuple, list)):
            object.__setattr__(
                self,
                "environment",
                tuple(tuple(item) if isinstance(item, list) else item for item in self.environment),
            )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.source_merkle,
                self.lockfiles_digest,
                self.toolchain,
                self.platform,
                self.producer_schema,
                self.freshness_class,
            )
        ) or not isinstance(self.command, (tuple, list)) or not self.command or any(not isinstance(item, str) or not item for item in self.command):
            raise ValidationCacheError("cache_key_required_missing")
        if any(
            not isinstance(value, str)
            for value in (self.config_digest, self.fixture_digest, self.generation)
        ):
            raise ValidationCacheError("cache_key_optional_field_invalid")
        if not isinstance(self.environment, (tuple, list)) or any(
            not isinstance(item, (tuple, list))
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or not isinstance(item[1], str)
            for item in self.environment
        ):
            raise ValidationCacheError("cache_environment_invalid")
        return {
            "schema": CACHE_KEY_SCHEMA,
            "source_merkle": self.source_merkle,
            "lockfiles_digest": self.lockfiles_digest,
            "toolchain": self.toolchain,
            "command": list(self.command),
            "environment": [list(item) for item in sorted(self.environment)],
            "platform": self.platform,
            "config_digest": self.config_digest,
            "fixture_digest": self.fixture_digest,
            "generation": self.generation,
            "producer_schema": self.producer_schema,
            "freshness_class": self.freshness_class,
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    key_digest: str
    status: str
    result_digest: str
    command: tuple[str, ...]
    fresh: bool
    evidence: tuple[str, ...] = ()
    verified: bool = False
    provenance: tuple[str, ...] = ()
    nondeterministic: bool = False
    generation: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in {"pass", "fail", "partial"}:
            raise ValidationCacheError("result_status_invalid")
        if not isinstance(self.key_digest, str) or not self.key_digest or not isinstance(self.result_digest, str) or not self.result_digest:
            raise ValidationCacheError("result_digest_invalid")
        command = _validate_string_sequence(self.command, "result_command_invalid")
        if not command:
            raise ValidationCacheError("result_command_invalid")
        evidence = _validate_string_sequence(self.evidence, "result_evidence_invalid")
        provenance = _validate_string_sequence(self.provenance, "result_provenance_invalid")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "provenance", provenance)
        if not isinstance(self.fresh, bool) or not isinstance(self.verified, bool) or not isinstance(self.nondeterministic, bool):
            raise ValidationCacheError("result_flags_invalid")
        if not isinstance(self.generation, str):
            raise ValidationCacheError("result_generation_invalid")
        if self.verified and not self.provenance:
            raise ValidationCacheError("result_provenance_required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "key_digest": self.key_digest,
            "status": self.status,
            "result_digest": self.result_digest,
            "command": list(self.command),
            "fresh": self.fresh,
            "evidence": list(self.evidence),
            "verified": self.verified,
            "provenance": list(self.provenance),
            "nondeterministic": self.nondeterministic,
            "generation": self.generation,
        }


class ValidationCache:
    """In-memory derived cache; callers retain authority over execution policy."""

    def __init__(self) -> None:
        self._entries: dict[str, ValidationResult] = {}
        self._leases: dict[str, set[str]] = {}
        self._lock = RLock()

    def save(self, path: Path) -> dict[str, Any]:
        """Persist derived results atomically; execution authority stays external."""
        with self._lock:
            body = {
                "schema": "simplicio.fast.validation-cache/v1",
                "entries": [self._entries[key].to_dict() for key in sorted(self._entries)],
            }
            document = {"body": body, "cache_sha256": _digest(body)}
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_name = temporary.name
                    temporary.write(_canonical(document) + b"\n")
                    temporary.flush()
                    os.fsync(temporary.fileno())
                for attempt in range(8):
                    try:
                        os.replace(temporary_name, path)
                        temporary_name = None
                        break
                    except PermissionError:
                        if attempt == 7:
                            raise
                        time.sleep(0.01 * (2**attempt))
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
            return {"schema": "simplicio.fast.validation-cache-receipt/v1", "status": "saved", "entries": len(body["entries"]), "cache_sha256": document["cache_sha256"]}

    @classmethod
    def load(cls, path: Path) -> "ValidationCache":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationCacheError("cache_document_invalid") from error
        if not isinstance(document, Mapping):
            raise ValidationCacheError("cache_document_invalid")
        body = document.get("body")
        if not isinstance(body, Mapping) or body.get("schema") != "simplicio.fast.validation-cache/v1":
            raise ValidationCacheError("cache_schema_unsupported")
        if document.get("cache_sha256") != _digest(body):
            raise ValidationCacheError("cache_digest_mismatch")
        entries = body.get("entries")
        if not isinstance(entries, list):
            raise ValidationCacheError("cache_entries_invalid")
        cache = cls()
        seen: set[str] = set()
        for raw in entries:
            if not isinstance(raw, Mapping):
                raise ValidationCacheError("cache_entries_invalid")
            try:
                command = raw["command"]
                evidence = raw.get("evidence", [])
                provenance = raw.get("provenance", [])
                if not isinstance(command, list) or not isinstance(evidence, list) or not isinstance(provenance, list):
                    raise ValidationCacheError("cache_entry_invalid")
                entry = ValidationResult(
                    raw["key_digest"], raw["status"], raw["result_digest"],
                    tuple(command), raw["fresh"], tuple(evidence),
                    raw.get("verified", False), tuple(provenance),
                    raw.get("nondeterministic", False), raw.get("generation", ""),
                )
            except (KeyError, TypeError, ValueError, ValidationCacheError) as error:
                raise ValidationCacheError("cache_entry_invalid") from error
            if entry.key_digest in seen:
                raise ValidationCacheError("cache_duplicate_entry")
            seen.add(entry.key_digest)
            cache._entries[entry.key_digest] = entry
        return cache

    def put(
        self,
        key: ValidationKey,
        *,
        status: str,
        result: Any,
        command: Sequence[str] | None = None,
        fresh: bool = True,
        evidence: Sequence[str] = (),
        verified: bool = False,
        provenance: Sequence[str] = (),
    ) -> ValidationResult:
        result_digest = _digest(result)
        key_digest = key.digest
        command_values = (
            tuple(key.command)
            if command is None
            else _validate_string_sequence(command, "result_command_invalid")
        )
        evidence_values = _validate_string_sequence(evidence, "result_evidence_invalid")
        provenance_values = _validate_string_sequence(
            provenance, "result_provenance_invalid"
        )
        with self._lock:
            previous = self._entries.get(key_digest)
            if previous is not None and previous.result_digest != result_digest:
                evidence_values = tuple(
                    sorted(set(evidence_values).union(previous.evidence, {"nondeterministic"}))
                )
                verified = False
                provenance_values = ()
                entry = ValidationResult(
                    key_digest, "partial", result_digest, command_values, False,
                    evidence_values, False, provenance_values, True, key.generation,
                )
                self._entries[key_digest] = entry
                return entry
            if verified and not provenance_values:
                raise ValidationCacheError("result_provenance_required")
            entry = ValidationResult(
                key_digest, status, result_digest, command_values, fresh,
                evidence_values, verified, provenance_values, False, key.generation,
            )
            self._entries[key_digest] = entry
            return entry

    def acquire_lease(self, key: ValidationKey, lease_id: str) -> dict[str, Any]:
        """Pin one cached result so a GC pass cannot remove it."""
        if not lease_id or any(character in lease_id for character in "\\/\0"):
            raise ValidationCacheError("lease_id_invalid")
        key_digest = key.digest
        with self._lock:
            if key_digest not in self._entries:
                raise ValidationCacheError("cache_entry_missing")
            self._leases.setdefault(key_digest, set()).add(lease_id)
            return {
                "schema": "simplicio.fast.validation-cache-lease/v1",
                "status": "leased",
                "key_digest": key_digest,
                "lease_id": lease_id,
            }

    def release_lease(self, key: ValidationKey, lease_id: str) -> dict[str, Any]:
        if not lease_id:
            raise ValidationCacheError("lease_id_invalid")
        key_digest = key.digest
        with self._lock:
            leases = self._leases.get(key_digest, set())
            leases.discard(lease_id)
            if leases:
                self._leases[key_digest] = leases
            else:
                self._leases.pop(key_digest, None)
            return {
                "schema": "simplicio.fast.validation-cache-lease/v1",
                "status": "released",
                "key_digest": key_digest,
                "lease_id": lease_id,
            }

    def gc(
        self,
        *,
        keep_generations: Sequence[str] = (),
        max_entries: int = 256,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Plan or apply bounded removal of unleased generations."""
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValidationCacheError("gc_budget_invalid")
        keep = set(_validate_string_sequence(keep_generations, "gc_generations_invalid"))
        with self._lock:
            candidates = sorted(
                key_digest
                for key_digest, entry in self._entries.items()
                if entry.generation not in keep and not self._leases.get(key_digest)
            )[:max_entries]
            if not dry_run:
                for key_digest in candidates:
                    self._entries.pop(key_digest, None)
            return {
                "schema": "simplicio.fast.validation-cache-gc/v1",
                "status": "planned" if dry_run else "applied",
                "dry_run": dry_run,
                "removed": [] if dry_run else candidates,
                "candidates": candidates,
                "retained_generations": sorted(keep),
                "leased_entries": sorted(
                    key_digest for key_digest, leases in self._leases.items() if leases
                ),
                "truncated": len(candidates) == max_entries,
            }

    def get(
        self,
        key: ValidationKey,
        *,
        require_fresh: bool = False,
        require_verified: bool = False,
        reusable: bool = False,
    ) -> ValidationResult | None:
        key_digest = key.digest
        with self._lock:
            entry = self._entries.get(key_digest)
            if (
                entry is None
                or (require_fresh and not entry.fresh)
                or (require_verified and not entry.verified)
                or (reusable and (not entry.verified or not entry.fresh or entry.nondeterministic))
            ):
                return None
            return entry

    def affected(self, changed_handles: Sequence[str], tests: Mapping[str, Sequence[str]], *, max_tests: int = 1000) -> dict[str, Any]:
        if (
            isinstance(max_tests, bool)
            or not isinstance(max_tests, int)
            or not 0 < max_tests <= MAX_AFFECTED_TESTS
        ):
            raise ValidationCacheError("selection_budget_invalid")
        changed = set(_validate_string_sequence(changed_handles, "changed_handles_invalid"))
        if not isinstance(tests, Mapping):
            raise ValidationCacheError("test_mapping_invalid")
        normalized_tests: dict[str, tuple[str, ...]] = {}
        for handle, values in tests.items():
            if not isinstance(handle, str) or not handle:
                raise ValidationCacheError("test_mapping_invalid")
            normalized_tests[handle] = _validate_string_sequence(
                values, "test_values_invalid"
            )
        selected_by_handle = {
            handle: sorted(set(values))
            for handle, values in normalized_tests.items()
            if handle in changed
        }
        selected = sorted({test for values in selected_by_handle.values() for test in values})
        complete = len(selected) <= max_tests
        return {
            "schema": "simplicio.fast.affected-validation/v1",
            "tests": selected[:max_tests],
            "changed_handles": sorted(changed),
            "reason_paths": [
                {"handle": handle, "tests": values, "reason": "changed_handle"}
                for handle, values in sorted(selected_by_handle.items())
            ],
            "complete": complete,
            "truncation_reasons": [] if complete else ["test_budget"],
        }


__all__ = ["CACHE_KEY_SCHEMA", "RESULT_SCHEMA", "ValidationCache", "ValidationCacheError", "ValidationKey", "ValidationResult"]
