"""Fail-closed boundary for Mapper-owned context snapshots.

``simplicio.context-snapshot/v1`` belongs to ``simplicio-mapper``.  This
module deliberately contains no schema copy: it verifies the installed
Mapper conformance-kit manifest, then delegates validation to Mapper's public
``context_contract`` API.  The resulting adapter keeps the validated payload
as canonical bytes and exposes only derived, immutable planner views.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
import os
import re
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from simplicio.plan_compiler.errors import PlanCompilerError
from simplicio.utils.fs import write_text_atomic

MAPPER_CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
MAPPER_CONTEXT_PACK_SCHEMA = "simplicio.context-pack/v1"
MAPPER_EXECUTION_CONTEXT_SCHEMA = "simplicio.execution-context/v1"
DEV_CLI_CONTEXT_HANDLE_SCHEMA = "simplicio.dev-cli.context-handle/v1"
DEV_CLI_FALLBACK_CONTEXT_SCHEMA = "simplicio.dev-cli.context-fallback/v1"
CONTEXT_BINDING_CACHE_SCHEMA = "simplicio.context-binding-cache/v1"
CONTEXT_BINDING_LOG_SCHEMA = "simplicio.context-binding-log/v1"
CONTEXT_BINDING_LOG_MAGIC = b"CBL1"
CONTEXT_BINDING_LOG_VERSION = 1
CONTEXT_CACHE_RECOVERY_SCHEMA = "simplicio.context-binding-cache-recovery/v1"
CONTEXT_BINDING_LOG_MAX_RECORD = 4 * 1024 * 1024
MAPPER_CONTRACT_OWNER = "wesleysimplicio/simplicio-mapper"
MAPPER_CONTRACT_MANIFEST_SHA256 = "db8cf791fe6442585f03b3fac220c0987ca5e4271a4955df02b1df77018c52b0"
MAPPER_CONTRACT_COMMIT = "05ea96390762d4bba309abcbf4783d0637a4e53f"
_MANIFEST_PATH = "contracts/context-snapshot/v1/contract-manifest.json"
_LEGACY_SHADOW_FIELDS = frozenset({"snapshot_id", "revision", "base_sha", "captured_at", "root", "extra"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEYS = frozenset({"secret", "password", "access_token", "api_key", "private_key"})
_MAPPER_GRAPH_DELTA_SCHEMA = "simplicio.graph-delta/v1"


class MapperContextError(PlanCompilerError):
    """A stable, machine-readable rejection at the Mapper context boundary."""

    def __init__(self, code: str, message: str, *, reasons: tuple[Mapping[str, str], ...] = ()) -> None:
        self.code = code
        self.reasons = reasons
        super().__init__(f"{code}: {message}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read_manifest() -> Mapping[str, Any]:
    """Load the exact contract-kit resource from the installed Mapper wheel."""
    try:
        raw = importlib.resources.files("simplicio_mapper").joinpath(_MANIFEST_PATH).read_bytes()
    except (ImportError, ModuleNotFoundError, FileNotFoundError, OSError, AttributeError) as exc:
        raise MapperContextError(
            "MAPPER_MANIFEST_UNAVAILABLE", "installed Mapper contract kit is unavailable"
        ) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != MAPPER_CONTRACT_MANIFEST_SHA256:
        raise MapperContextError(
            "MAPPER_MANIFEST_DIGEST_MISMATCH",
            "installed Mapper manifest does not match the pinned contract digest",
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MapperContextError(
            "MAPPER_MANIFEST_INVALID", "Mapper manifest is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("owner") != MAPPER_CONTRACT_OWNER:
        raise MapperContextError("MAPPER_MANIFEST_INVALID", "Mapper manifest has an unexpected owner")
    schema_ids = manifest.get("schema_ids")
    compatibility = manifest.get("compatibility")
    if (
        not isinstance(schema_ids, list)
        or MAPPER_CONTEXT_SNAPSHOT_SCHEMA not in schema_ids
        or not isinstance(compatibility, dict)
        or compatibility.get("current") != "v1"
        or compatibility.get("future") != "fail-closed"
    ):
        raise MapperContextError(
            "MAPPER_MANIFEST_INVALID", "Mapper manifest does not describe the canonical v1 contract"
        )
    return MappingProxyType(manifest)


def _mapper_api() -> tuple[Any, Any]:
    try:
        module = importlib.import_module("simplicio_mapper.context_contract")
        return module.validate_context_payload, module.canonical_json
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        raise MapperContextError(
            "MAPPER_API_UNAVAILABLE", "installed Mapper validator API is unavailable"
        ) from exc


def _is_legacy_shadow(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("schema") == MAPPER_CONTEXT_SNAPSHOT_SCHEMA
        and _LEGACY_SHADOW_FIELDS.issubset(payload)
        and "graph" not in payload
        and "root_hash" not in payload
    )


@dataclass(frozen=True)
class MapperContextView:
    """Read-only planner view derived from one canonical Mapper snapshot."""

    snapshot_id: str
    revision: str
    root_hash: str
    graph_hash: str
    freshness: Mapping[str, Any]
    fidelity: Mapping[str, Any]
    source_handles: tuple[Mapping[str, Any], ...]
    source_set: tuple[str, ...]
    needs_broader_context: bool


@dataclass(frozen=True)
class MapperContextAdapter:
    """Validated immutable canonical payload plus a small typed planning view."""

    payload_bytes: bytes
    payload: Mapping[str, Any]
    view: MapperContextView
    manifest: Mapping[str, Any]

    @property
    def source_digest(self) -> str:
        """Digest of the exact canonical snapshot bytes accepted from Mapper."""

        return hashlib.sha256(self.payload_bytes).hexdigest()


@dataclass(frozen=True)
class MapperContextPackAdapter:
    """Validated immutable projection tied to one canonical snapshot."""

    payload_bytes: bytes
    payload: Mapping[str, Any]
    pack_hash: str
    projection_digest: str
    files: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ContextHandle:
    """Content-addressed identity shared by planning and effect boundaries."""

    snapshot_id: str
    revision: str
    source_digest: str
    pack_hash: str
    mapper_version: str
    source_root_identity: str
    projection_digest: str
    generation: str = ""
    repository: str = ""
    commit: str = ""
    overlay: str = ""
    context_schema: str = MAPPER_CONTEXT_SNAPSHOT_SCHEMA
    # Fast V3 additive provenance.  These fields are optional so older Mapper
    # snapshots keep their exact wire shape while newer Python/Rust engines
    # can share one engine-neutral binding.
    base_generation: str = ""
    overlay_generation: str = ""
    engine: str = ""
    capability_digest: str = ""
    source_hashes: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": DEV_CLI_CONTEXT_HANDLE_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "pack_hash": self.pack_hash,
            "mapper_version": self.mapper_version,
            "source_root_identity": self.source_root_identity,
            "projection_digest": self.projection_digest,
            "generation": self.generation,
            "repository": self.repository,
            "commit": self.commit,
            "overlay": self.overlay,
            "context_schema": self.context_schema,
        }
        if self.base_generation:
            payload["base_generation"] = self.base_generation
        if self.overlay_generation:
            payload["overlay_generation"] = self.overlay_generation
        if self.engine:
            payload["engine"] = self.engine
        if self.capability_digest:
            payload["capability_digest"] = self.capability_digest
        if self.source_hashes:
            payload["source_hashes"] = {key: value for key, value in self.source_hashes}
        return payload

    def validate_engine_binding(self) -> None:
        """Reject engine-specific or stale provenance before plan compilation."""
        if self.engine and self.engine not in {"python", "rust"}:
            raise MapperContextError("ENGINE_UNSUPPORTED", f"unsupported context engine: {self.engine}")
        if self.engine == "rust" and not self.capability_digest:
            raise MapperContextError(
                "ENGINE_CAPABILITIES_MISSING", "Rust context is missing capability digest"
            )
        if self.base_generation and self.generation and self.base_generation != self.generation:
            raise MapperContextError(
                "GENERATION_MISMATCH", "base generation does not match context generation"
            )
        for path, digest in self.source_hashes:
            if not path or not _SHA256_RE.fullmatch(str(digest).removeprefix("sha256:")):
                raise MapperContextError("SOURCE_HASH_INVALID", f"invalid source hash for {path}")
        if any("offset" in key.casefold() or "mmap" in key.casefold() for key in self.to_dict()):
            raise MapperContextError("ENGINE_INTERNAL_LEAK", "context handle exposes storage internals")

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()

    @property
    def value(self) -> str:
        return f"sha256:{self.digest}"


@dataclass(frozen=True)
class ContextBinding:
    """One validated snapshot/projection pair and its common handle."""

    snapshot: MapperContextAdapter
    pack: MapperContextPackAdapter
    context_handle: ContextHandle


class ContextBindingCache:
    """Cross-process metadata cache for validated context bindings.

    The cache intentionally stores only hashes and identity fields.  It never
    stores snapshot/pack content and it is never used to bypass Mapper
    validation.  A caller must bind and verify the current payload first;
    this cache then records whether that exact digest was seen before.  The
    handle is the key and the complete identity is checked again on lookup,
    so a reused snapshot id or a malformed cache file cannot mix roots,
    revisions, or projections.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / ".simplicio-loop" / "context-bindings.json"
        self.log_path = self.root / ".simplicio-loop" / "context-bindings.hbp"
        self.index_path = self.root / ".simplicio-loop" / "context-bindings.hbp.idx"
        self.legacy_log_path = self.root / ".simplicio-loop" / "context-bindings.hbp.jsonl"
        self.lock_path = self.root / ".simplicio-loop" / "context-bindings.hbp.lock"
        self._read_cache_signature: tuple[int, int, int, int] | None = None
        self._read_cache: dict[str, Any] | None = None
        self._migrate_legacy_once()

    @staticmethod
    def _identity(handle: ContextHandle) -> dict[str, str]:
        return {
            "snapshot_id": str(getattr(handle, "snapshot_id", "")),
            "revision": str(getattr(handle, "revision", "")),
            "source_digest": str(getattr(handle, "source_digest", "")),
            "pack_hash": str(getattr(handle, "pack_hash", "")),
            "mapper_version": str(getattr(handle, "mapper_version", "")),
            "source_root_identity": str(getattr(handle, "source_root_identity", "")),
            "projection_digest": str(getattr(handle, "projection_digest", "")),
            "generation": str(getattr(handle, "generation", "")),
            "repository": str(getattr(handle, "repository", "")),
            "commit": str(getattr(handle, "commit", "")),
            "overlay": str(getattr(handle, "overlay", "")),
            "context_schema": str(getattr(handle, "context_schema", "")),
            "base_generation": str(getattr(handle, "base_generation", "")),
            "overlay_generation": str(getattr(handle, "overlay_generation", "")),
            "engine": str(getattr(handle, "engine", "")),
            "capability_digest": str(getattr(handle, "capability_digest", "")),
            "source_hashes_digest": hashlib.sha256(
                _canonical_json_bytes(dict(getattr(handle, "source_hashes", ())))
            ).hexdigest(),
        }

    def lookup(self, handle: ContextHandle) -> dict[str, Any]:
        key = handle.value
        store = self._read()
        if store.get("chain_status") != "valid":
            return self._receipt(
                key,
                handle,
                hit=False,
                reason="corrupt_chain",
                revision=store.get("revision"),
            )
        entry = store.get("entries", {}).get(key)
        identity = self._identity(handle)
        if not isinstance(entry, dict):
            return self._receipt(key, handle, hit=False, reason="missing", revision=store.get("revision"))
        if entry.get("identity") != identity:
            return self._receipt(
                key, handle, hit=False, reason="identity_mismatch", revision=store.get("revision")
            )
        return self._receipt(key, handle, hit=True, reason="exact_digest", revision=store.get("revision"))

    def put(
        self,
        binding: ContextBinding,
        *,
        expected_revision: str | None = None,
        fence: str | None = None,
    ) -> dict[str, Any]:
        handle = binding.context_handle
        revision = self._append_event(
            "put",
            handle.value,
            identity=self._identity(handle),
            expected_revision=expected_revision,
            fence=fence,
        )
        return self._receipt(handle.value, handle, hit=False, reason="stored", stored=True, revision=revision)

    def refresh(
        self,
        binding: ContextBinding,
        *,
        expected_revision: str | None = None,
        fence: str | None = None,
    ) -> dict[str, Any]:
        """Invalidate prior revisions for this snapshot, then record this one."""

        handle = binding.context_handle
        entries = self._read().setdefault("entries", {})
        invalidated = 0
        for entry in entries.values():
            identity = entry.get("identity") if isinstance(entry, dict) else None
            if isinstance(identity, dict) and identity.get("snapshot_id") == handle.snapshot_id:
                invalidated += 1
        revision = self._append_event(
            "invalidate",
            criteria={"snapshot_id": handle.snapshot_id},
            expected_revision=expected_revision,
            fence=fence,
        )
        revision = self._append_event(
            "put",
            handle.value,
            identity=self._identity(handle),
            expected_revision=revision,
            fence=fence,
        )
        receipt = self._receipt(
            handle.value,
            handle,
            hit=False,
            reason="explicit_refresh",
            stored=True,
            revision=revision,
        )
        receipt["invalidated"] = invalidated
        return receipt

    def invalidate(
        self,
        *,
        snapshot_id: str | None = None,
        source_root_identity: str | None = None,
        key: str | None = None,
        expected_revision: str | None = None,
        fence: str | None = None,
    ) -> dict[str, Any]:
        entries = self._read().setdefault("entries", {})
        removed = sum(
            1
            for candidate, entry in entries.items()
            if self._matches(
                candidate,
                entry,
                key=key,
                snapshot_id=snapshot_id,
                source_root_identity=source_root_identity,
            )
        )
        revision = self._append_event(
            "invalidate",
            criteria={
                name: value
                for name, value in (
                    ("key", key),
                    ("snapshot_id", snapshot_id),
                    ("source_root_identity", source_root_identity),
                )
                if value is not None
            },
            expected_revision=expected_revision,
            fence=fence,
        )
        return {
            "schema": CONTEXT_BINDING_CACHE_SCHEMA,
            "removed": removed,
            "storage": "hbp-log",
            "revision": revision,
        }

    def _receipt(
        self,
        key: str,
        handle: ContextHandle,
        *,
        hit: bool,
        reason: str,
        stored: bool = False,
        revision: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": CONTEXT_BINDING_CACHE_SCHEMA,
            "key": key,
            "hit": hit,
            "reason": reason,
            "stored": stored,
            "revision": revision,
            "identity": self._identity(handle),
        }

    def _read(self) -> dict[str, Any]:
        if self.log_path.is_file():
            signature = self._log_signature()
            if signature == self._read_cache_signature and self._read_cache is not None:
                return self._read_cache
            indexed = self._read_index(signature)
            if indexed is not None:
                self._read_cache_signature = signature
                self._read_cache = indexed
                return indexed
            state = self._read_log()
            if state.get("chain_status") == "valid" and signature is not None:
                self._write_index(signature, state)
            self._read_cache_signature = signature
            self._read_cache = state
            return state
        if not self.path.is_file():
            return {
                "schema": CONTEXT_BINDING_CACHE_SCHEMA,
                "entries": {},
                "revision": "",
                "fence": "",
                "chain_status": "valid",
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {
                "schema": CONTEXT_BINDING_CACHE_SCHEMA,
                "entries": {},
                "revision": "",
                "fence": "",
                "chain_status": "corrupt",
            }
        if not isinstance(payload, dict) or payload.get("schema") != CONTEXT_BINDING_CACHE_SCHEMA:
            return {
                "schema": CONTEXT_BINDING_CACHE_SCHEMA,
                "entries": {},
                "revision": "",
                "fence": "",
                "chain_status": "corrupt",
            }
        entries = payload.get("entries")
        return {
            "schema": CONTEXT_BINDING_CACHE_SCHEMA,
            "entries": entries if isinstance(entries, dict) else {},
            "revision": "",
            "fence": "",
            "chain_status": "valid",
        }

    def _log_signature(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.log_path.stat()
        except OSError:
            return None
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _read_index(self, signature: tuple[int, int, int, int] | None) -> dict[str, Any] | None:
        """Load a validated-log snapshot without replaying every HBP event.

        The index is disposable metadata. It is accepted only when its exact
        device/inode/size/mtime signature matches the log; otherwise the HBP
        chain is replayed and a fresh index is derived. The log remains the
        integrity authority and the index never stores context contents.
        """
        if signature is None or not self.index_path.is_file():
            return None
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or tuple(payload.get("log_signature", ())) != signature:
            return None
        entries = payload.get("entries")
        if not isinstance(entries, dict) or not isinstance(payload.get("revision"), str):
            return None
        return {
            "schema": CONTEXT_BINDING_CACHE_SCHEMA,
            "entries": entries,
            "revision": payload["revision"],
            "fence": str(payload.get("fence") or ""),
            "chain_status": "valid",
        }

    def _write_index(self, signature: tuple[int, int, int, int], state: dict[str, Any]) -> None:
        """Atomically persist disposable lookup metadata after chain validation."""
        payload = {
            "schema": "simplicio.context-binding-cache-index/v1",
            "log_signature": list(signature),
            "revision": str(state.get("revision") or ""),
            "fence": str(state.get("fence") or ""),
            "entries": state.get("entries", {}),
        }
        try:
            write_text_atomic(
                self.index_path,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        except OSError:
            # An indexer/AV tool must never turn a valid cache write into a
            # failed execution; the next lookup simply replays the HBP log.
            return

    def _invalidate_read_cache(self) -> None:
        self._read_cache_signature = None
        self._read_cache = None

    def _write(self, payload: dict[str, Any]) -> None:
        for key, entry in payload.get("entries", {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("identity"), dict):
                self._append_event("put", str(key), identity=entry["identity"])

    def doctor(self) -> dict[str, Any]:
        """Report durable cache health without exposing context contents."""
        state = self._read()
        log_bytes = self.log_path.stat().st_size if self.log_path.is_file() else 0
        return {
            "schema": "simplicio.context-binding-cache-doctor/v1",
            "storage": "hbp-log" if self.log_path.is_file() else "legacy-json",
            "entries": len(state.get("entries", {})),
            "bytes": log_bytes,
            "chain_status": state.get("chain_status", "valid"),
            "revision": state.get("revision", ""),
            "fence": state.get("fence", ""),
            "lock_present": self.lock_path.exists(),
            "index_present": self.index_path.is_file(),
        }

    def _remove_stale_writer_lock(self) -> bool:
        try:
            owner = self.lock_path.read_text(encoding="ascii").strip()
            pid = int(owner)
        except (OSError, UnicodeError, ValueError):
            return False
        if pid <= 0 or pid == os.getpid():
            return False
        if os.name == "nt":
            win_dll = getattr(ctypes, "WinDLL", None)
            get_last_error = getattr(ctypes, "get_last_error", None)
            if win_dll is None or get_last_error is None:
                return False
            kernel32 = win_dll("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                running = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                if not running or exit_code.value == 259:
                    return False
                return True
            if get_last_error() != 87:
                return False
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except OSError:
                return False
            else:
                return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        return True

    def _acquire_writer_lock(self, *, recover_stale: bool = False) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 10
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                pass
            except PermissionError:
                pass
            if time.monotonic() >= deadline:
                if recover_stale and self._remove_stale_writer_lock():
                    deadline = time.monotonic() + 10
                    continue
                raise MapperContextError(
                    "CONTEXT_CACHE_LOCK_TIMEOUT", "context cache writer lock is busy"
                ) from None
            time.sleep(0.01)

    def compact(self) -> dict[str, Any]:
        """Rewrite the live metadata entries into a shorter hash-chain log."""
        if not self.log_path.is_file():
            return self.doctor()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_writer_lock(recover_stale=True)

        temporary = self.log_path.with_name(f"{self.log_path.name}.{os.getpid()}.tmp")
        try:
            state = self._read_log()
            previous = ""
            with temporary.open("wb") as handle:
                handle.write(CONTEXT_BINDING_LOG_MAGIC)
                handle.write(struct.pack("<HH", CONTEXT_BINDING_LOG_VERSION, 0))
                for key, entry in sorted(state.get("entries", {}).items()):
                    event: dict[str, Any] = {
                        "schema": CONTEXT_BINDING_LOG_SCHEMA,
                        "kind": "put",
                        "previous_digest": previous,
                        "key": key,
                        "identity": entry["identity"],
                    }
                    if state.get("fence"):
                        event["fence"] = state["fence"]
                    event["digest"] = (
                        "sha256:"
                        + hashlib.sha256(
                            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                    )
                    encoded = self._encode_event(event)
                    handle.write(struct.pack("<I", len(encoded)))
                    handle.write(encoded)
                    previous = str(event["digest"])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.log_path)
            return self.doctor()
        finally:
            temporary.unlink(missing_ok=True)
            self.lock_path.unlink(missing_ok=True)

    def recover(self) -> dict[str, Any]:
        """Safely compact a cache after a torn or corrupted append.

        Only the valid prefix returned by the authenticated log replay is
        retained.  The result is an explicit receipt so callers can audit
        whether bytes were discarded instead of treating recovery as a hit.
        """

        before = self._read_log() if self.log_path.is_file() else self.doctor()
        before_bytes = self.log_path.stat().st_size if self.log_path.is_file() else 0
        if before.get("chain_status") == "valid":
            return {
                "schema": CONTEXT_CACHE_RECOVERY_SCHEMA,
                "recovered": False,
                "chain_status": "valid",
                "bytes_before": before_bytes,
                "bytes_after": before_bytes,
                "discarded_bytes": 0,
                "revision": before.get("revision", ""),
            }
        after = self.compact()
        after_bytes = int(after.get("bytes", 0) or 0)
        return {
            "schema": CONTEXT_CACHE_RECOVERY_SCHEMA,
            "recovered": True,
            "chain_status": after.get("chain_status", "corrupt"),
            "bytes_before": before_bytes,
            "bytes_after": after_bytes,
            "discarded_bytes": max(0, before_bytes - after_bytes),
            "revision": after.get("revision", ""),
        }

    @staticmethod
    def _matches(
        candidate: str,
        entry: Any,
        *,
        key: str | None,
        snapshot_id: str | None,
        source_root_identity: str | None,
    ) -> bool:
        identity = entry.get("identity") if isinstance(entry, dict) else None
        return (
            (key is None or candidate == key)
            and (
                snapshot_id is None
                or (isinstance(identity, dict) and identity.get("snapshot_id") == snapshot_id)
            )
            and (
                source_root_identity is None
                or (
                    isinstance(identity, dict)
                    and identity.get("source_root_identity") == source_root_identity
                )
            )
        )

    def _read_log(self) -> dict[str, Any]:
        entries: dict[str, dict[str, Any]] = {}
        previous = ""
        fence = ""
        chain_status = "valid"
        try:
            raw = self.log_path.read_bytes()
        except OSError:
            return {
                "schema": CONTEXT_BINDING_CACHE_SCHEMA,
                "entries": {},
                "revision": "",
                "fence": "",
                "chain_status": "corrupt",
            }
        if len(raw) < 8 or raw[:4] != CONTEXT_BINDING_LOG_MAGIC:
            chain_status = "corrupt"
            events: tuple[dict[str, Any], ...] = ()
        else:
            version, reserved = struct.unpack("<HH", raw[4:8])
            if version != CONTEXT_BINDING_LOG_VERSION or reserved != 0:
                chain_status = "corrupt"
                events = ()
            else:
                decoded: list[dict[str, Any]] = []
                cursor = 8
                while cursor < len(raw):
                    if cursor + 4 > len(raw):
                        chain_status = "corrupt"
                        break
                    length = struct.unpack("<I", raw[cursor : cursor + 4])[0]
                    cursor += 4
                    if length > CONTEXT_BINDING_LOG_MAX_RECORD or cursor + length > len(raw):
                        chain_status = "corrupt"
                        break
                    try:
                        decoded.append(self._decode_event(raw[cursor : cursor + length]))
                    except (UnicodeError, ValueError, struct.error):
                        chain_status = "corrupt"
                        break
                    cursor += length
                events = tuple(decoded)
        for event in events:
            try:
                if event.get("schema") != CONTEXT_BINDING_LOG_SCHEMA:
                    chain_status = "corrupt"
                    break
                if event.get("previous_digest", "") != previous:
                    chain_status = "corrupt"
                    break
                unsigned = dict(event)
                digest = unsigned.pop("digest", None)
                expected = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                )
                if digest != expected:
                    chain_status = "corrupt"
                    break
                kind = event.get("kind")
                if (
                    kind == "put"
                    and isinstance(event.get("key"), str)
                    and isinstance(event.get("identity"), dict)
                ):
                    entries[event["key"]] = {"identity": event["identity"]}
                elif kind == "invalidate":
                    criteria = event.get("criteria", {})
                    entries = {
                        candidate: value
                        for candidate, value in entries.items()
                        if not self._matches(
                            candidate,
                            value,
                            key=criteria.get("key"),
                            snapshot_id=criteria.get("snapshot_id"),
                            source_root_identity=criteria.get("source_root_identity"),
                        )
                    }
                else:
                    chain_status = "corrupt"
                    break
                previous = str(digest)
                fence = str(event.get("fence") or fence)
            except (TypeError, ValueError):
                chain_status = "corrupt"
                break
        return {
            "schema": CONTEXT_BINDING_CACHE_SCHEMA,
            "entries": entries,
            "revision": previous,
            "fence": fence,
            "chain_status": chain_status,
        }

    def _append_event(
        self,
        kind: str,
        key: str | None = None,
        *,
        identity: dict[str, str] | None = None,
        criteria: dict[str, str] | None = None,
        expected_revision: str | None = None,
        fence: str | None = None,
        lock_held: bool = False,
    ) -> str:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not lock_held:
            self._acquire_writer_lock()

        try:
            previous = ""
            if self.log_path.is_file():
                current = self._read_log()
                if current.get("chain_status") != "valid":
                    raise MapperContextError(
                        "CONTEXT_CACHE_CORRUPT",
                        "context cache hash chain is corrupt; compact it before writing",
                    )
                previous = str(current.get("revision", ""))
            if expected_revision is not None and expected_revision != previous:
                raise MapperContextError(
                    "CONTEXT_CACHE_CAS_CONFLICT",
                    "context cache revision changed before the write",
                )
            current_fence = ""
            if self.log_path.is_file():
                current_fence = str(current.get("fence") or "")
            if fence is not None and current_fence:
                try:
                    stale = int(fence) < int(current_fence)
                except ValueError:
                    stale = fence != current_fence
                if stale:
                    raise MapperContextError(
                        "CONTEXT_CACHE_FENCE_STALE", "writer fence is older than the cache fence"
                    )
            event: dict[str, Any] = {
                "schema": CONTEXT_BINDING_LOG_SCHEMA,
                "kind": kind,
                "previous_digest": previous,
            }
            if key is not None:
                event["key"] = key
            if identity is not None:
                event["identity"] = identity
            if criteria is not None:
                event["criteria"] = criteria
            if fence is not None:
                event["fence"] = fence
            event["digest"] = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
            )
            encoded = self._encode_event(event)
            is_new = not self.log_path.exists()
            with self.log_path.open("ab") as handle:
                if is_new:
                    handle.write(CONTEXT_BINDING_LOG_MAGIC)
                    handle.write(struct.pack("<HH", CONTEXT_BINDING_LOG_VERSION, 0))
                handle.write(struct.pack("<I", len(encoded)))
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._invalidate_read_cache()
            return str(event["digest"])
        finally:
            if not lock_held:
                self.lock_path.unlink(missing_ok=True)

    @staticmethod
    def _pack_string(value: str) -> bytes:
        encoded = value.encode("utf-8")
        if len(encoded) > CONTEXT_BINDING_LOG_MAX_RECORD:
            raise ValueError("context binding log field is too large")
        return struct.pack("<I", len(encoded)) + encoded

    @staticmethod
    def _unpack_string(raw: bytes, cursor: int) -> tuple[str, int]:
        if cursor + 4 > len(raw):
            raise ValueError("truncated context binding log field")
        length = struct.unpack("<I", raw[cursor : cursor + 4])[0]
        cursor += 4
        end = cursor + length
        if end > len(raw):
            raise ValueError("truncated context binding log value")
        return raw[cursor:end].decode("utf-8"), end

    @classmethod
    def _pack_optional(cls, value: object) -> bytes:
        if value is None:
            return b"\x00"
        return b"\x01" + cls._pack_string(str(value))

    @classmethod
    def _unpack_optional(cls, raw: bytes, cursor: int) -> tuple[str | None, int]:
        if cursor >= len(raw):
            raise ValueError("truncated context binding optional field")
        marker = raw[cursor]
        cursor += 1
        if marker == 0:
            return None, cursor
        if marker != 1:
            raise ValueError("invalid context binding optional field")
        return cls._unpack_string(raw, cursor)

    @classmethod
    def _pack_map(cls, values: Mapping[str, Any] | None) -> bytes:
        if values is None:
            return struct.pack("<H", 0)
        encoded = bytearray(struct.pack("<H", len(values)))
        for key, value in sorted(values.items()):
            encoded.extend(cls._pack_string(str(key)))
            encoded.extend(cls._pack_string(str(value)))
        return bytes(encoded)

    @classmethod
    def _unpack_map(cls, raw: bytes, cursor: int) -> tuple[dict[str, str], int]:
        if cursor + 2 > len(raw):
            raise ValueError("truncated context binding map")
        count = struct.unpack("<H", raw[cursor : cursor + 2])[0]
        cursor += 2
        values: dict[str, str] = {}
        for _ in range(count):
            key, cursor = cls._unpack_string(raw, cursor)
            value, cursor = cls._unpack_string(raw, cursor)
            values[key] = value
        return values, cursor

    @classmethod
    def _encode_event(cls, event: Mapping[str, Any]) -> bytes:
        kind = event.get("kind")
        if kind not in {"put", "invalidate"}:
            raise ValueError("unknown context binding event")
        output = bytearray(b"\x01" if kind == "put" else b"\x02")
        output.extend(cls._pack_string(str(event.get("previous_digest", ""))))
        output.extend(cls._pack_string(str(event.get("digest", ""))))
        output.extend(cls._pack_optional(event.get("key")))
        output.extend(cls._pack_optional(event.get("fence")))
        output.extend(cls._pack_map(event.get("identity")))
        output.extend(cls._pack_map(event.get("criteria")))
        if len(output) > CONTEXT_BINDING_LOG_MAX_RECORD:
            raise ValueError("context binding event is too large")
        return bytes(output)

    @classmethod
    def _decode_event(cls, raw: bytes) -> dict[str, Any]:
        if not raw:
            raise ValueError("empty context binding event")
        kind_code = raw[0]
        kind = {1: "put", 2: "invalidate"}.get(kind_code)
        if kind is None:
            raise ValueError("unknown context binding event")
        cursor = 1
        previous, cursor = cls._unpack_string(raw, cursor)
        digest, cursor = cls._unpack_string(raw, cursor)
        key, cursor = cls._unpack_optional(raw, cursor)
        fence, cursor = cls._unpack_optional(raw, cursor)
        identity, cursor = cls._unpack_map(raw, cursor)
        criteria, cursor = cls._unpack_map(raw, cursor)
        if cursor != len(raw):
            raise ValueError("trailing context binding event bytes")
        event: dict[str, Any] = {
            "schema": CONTEXT_BINDING_LOG_SCHEMA,
            "kind": kind,
            "previous_digest": previous,
            "digest": digest,
        }
        if key is not None:
            event["key"] = key
        if fence is not None:
            event["fence"] = fence
        if identity:
            event["identity"] = identity
        if criteria:
            event["criteria"] = criteria
        return event

    def _migrate_legacy_once(self) -> None:
        self._acquire_writer_lock(recover_stale=True)
        try:
            if self.log_path.is_file():
                return
            if self.legacy_log_path.is_file():
                for line in self.legacy_log_path.read_text(encoding="utf-8").splitlines():
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("legacy context binding event is not an object")
                    self._append_event(
                        str(event.get("kind", "")),
                        event.get("key"),
                        identity=event.get("identity"),
                        criteria=event.get("criteria"),
                        fence=event.get("fence"),
                        lock_held=True,
                    )
                migrated_path = self.legacy_log_path.with_suffix(self.legacy_log_path.suffix + ".migrated")
                self.legacy_log_path.rename(migrated_path)
                return
            if not self.path.is_file():
                return
            legacy = self._read()
            if legacy.get("chain_status") == "corrupt":
                raise MapperContextError(
                    "CONTEXT_CACHE_CORRUPT",
                    "legacy context cache is corrupt; it was preserved for recovery",
                )
            for key, entry in legacy.get("entries", {}).items():
                if isinstance(entry, dict) and isinstance(entry.get("identity"), dict):
                    self._append_event("put", str(key), identity=entry["identity"], lock_held=True)
            self.path.unlink(missing_ok=True)
        except MapperContextError:
            raise
        except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MapperContextError(
                "CONTEXT_CACHE_MIGRATION_FAILED", "legacy context cache migration failed"
            ) from exc
        finally:
            self.lock_path.unlink(missing_ok=True)


def _source_handles(graph: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    handles: list[Mapping[str, Any]] = []
    for node in graph.get("nodes", ()):  # validation already guaranteed the shapes.
        if isinstance(node, Mapping) and isinstance(node.get("source"), Mapping):
            handles.append(MappingProxyType(dict(node["source"])))
    for edge in graph.get("edges", ()):
        if isinstance(edge, Mapping) and isinstance(edge.get("source_handle"), Mapping):
            handles.append(MappingProxyType(dict(edge["source_handle"])))
    return tuple(handles)


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MapperContextError(
            "CONTEXT_PACK_NOT_CANONICAL", "ContextPack cannot be represented as canonical JSON"
        ) from exc


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _required_mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise MapperContextError("CONTEXT_PACK_INVALID", f"ContextPack.{field} must be an object")
    return value


def load_mapper_context_pack(
    payload: Any,
    *,
    snapshot: MapperContextAdapter,
    execution_context: Any | None = None,
) -> MapperContextPackAdapter:
    """Validate a Mapper projection and prove its canonical snapshot origin.

    Mapper owns the ContextPack schema.  The Dev CLI only consumes the
    additive ``source_snapshot`` provenance required for a safe integrated
    dispatch; it does not reinterpret or regenerate Mapper's projection.
    """

    if not isinstance(payload, Mapping) or payload.get("schema") != MAPPER_CONTEXT_PACK_SCHEMA:
        raise MapperContextError(
            "UNSUPPORTED_CONTEXT_PACK_SCHEMA", "a Mapper context-pack/v1 payload is required"
        )
    raw_pack_hash = payload.get("pack_hash")
    if raw_pack_hash is not None and (
        not isinstance(raw_pack_hash, str) or _SHA256_RE.fullmatch(raw_pack_hash) is None
    ):
        raise MapperContextError("CONTEXT_PACK_HASH_INVALID", "Mapper pack_hash must be SHA-256")
    provenance = payload.get("source_snapshot")
    if provenance is None:
        if execution_context is None:
            raise MapperContextError(
                "CONTEXT_PACK_PROVENANCE_REQUIRED",
                "ContextPack needs source_snapshot or a Mapper execution-context envelope",
            )
    else:
        if not isinstance(provenance, Mapping):
            raise MapperContextError("CONTEXT_PACK_INVALID", "ContextPack.source_snapshot must be an object")
        expected = {
            "snapshot_id": snapshot.view.snapshot_id,
            "revision": snapshot.view.revision,
            "source_digest": snapshot.source_digest,
            "root_hash": snapshot.view.root_hash,
        }
        for field, value in expected.items():
            if provenance.get(field) != value:
                raise MapperContextError(
                    "CONTEXT_PACK_ORIGIN_MISMATCH",
                    f"ContextPack source_snapshot.{field} does not match the canonical snapshot",
                )
    if _contains_sensitive_key(payload):
        raise MapperContextError(
            "CONTEXT_PACK_SENSITIVE_DATA", "ContextPack contains a forbidden sensitive field"
        )
    fidelity = _required_mapping(payload, "fidelity")
    if payload.get("needs_broader_context") is True or fidelity.get("gate") != "ready":
        raise MapperContextError(
            "CONTEXT_PACK_FIDELITY_INSUFFICIENT",
            "ContextPack requires explicit broader-context refresh before an effect",
        )
    budget = payload.get("serialization_budget")
    if budget is not None:
        if not isinstance(budget, Mapping):
            raise MapperContextError("CONTEXT_PACK_BUDGET_INVALID", "serialization_budget must be an object")
        token_budget = budget.get("token_budget")
        estimated_tokens = budget.get("estimated_tokens")
        if (
            not isinstance(token_budget, int)
            or isinstance(token_budget, bool)
            or token_budget < 0
            or not isinstance(estimated_tokens, int)
            or isinstance(estimated_tokens, bool)
            or estimated_tokens < 0
        ):
            raise MapperContextError(
                "CONTEXT_PACK_BUDGET_INVALID", "ContextPack token budget values must be integers"
            )
        if estimated_tokens > token_budget:
            raise MapperContextError(
                "CONTEXT_PACK_BUDGET_EXCEEDED", "ContextPack exceeds its declared token budget"
            )
    files = payload.get("files")
    if not isinstance(files, list):
        raise MapperContextError("CONTEXT_PACK_INVALID", "ContextPack.files must be an array")
    for entry in files:
        if (
            not isinstance(entry, Mapping)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("snapshot_hash"), str)
            or _SHA256_RE.fullmatch(str(entry["snapshot_hash"])) is None
        ):
            raise MapperContextError(
                "CONTEXT_PACK_FILE_INVALID", "every ContextPack file needs path and snapshot_hash"
            )
        relative = PurePosixPath(str(entry["path"]).translate({ord("\\"): "/"}))
        if relative.is_absolute() or ".." in relative.parts:
            raise MapperContextError(
                "CONTEXT_ROOT_PATH_MISMATCH",
                f"unsafe ContextPack source path: {entry['path']}",
            )
    payload_bytes = _canonical_json_bytes(payload)
    # Issue #301 compatibility: schema-compatible legacy packs may omit the
    # raw field; bind their canonical projection digest as the identity.
    pack_hash = raw_pack_hash or hashlib.sha256(payload_bytes).hexdigest()
    frozen = _freeze(json.loads(payload_bytes.decode("utf-8")))
    if not isinstance(frozen, Mapping):
        raise MapperContextError("CONTEXT_PACK_INVALID", "canonical ContextPack is not an object")
    frozen_files = frozen["files"]
    return MapperContextPackAdapter(
        payload_bytes=payload_bytes,
        payload=frozen,
        pack_hash=pack_hash,
        projection_digest=hashlib.sha256(payload_bytes).hexdigest(),
        files=tuple(item for item in frozen_files if isinstance(item, Mapping)),
    )


def load_mapper_execution_context(
    payload: Any,
    *,
    snapshot: MapperContextAdapter,
    pack: MapperContextPackAdapter,
) -> Mapping[str, Any]:
    """Validate Mapper's task envelope as the provenance for a ContextPack.

    The Mapper owns this envelope and its hash.  Dev CLI only checks the
    public validator and the three cross-payload identities it consumes.
    """
    if not isinstance(payload, Mapping) or payload.get("schema") != MAPPER_EXECUTION_CONTEXT_SCHEMA:
        raise MapperContextError(
            "UNSUPPORTED_EXECUTION_CONTEXT_SCHEMA",
            "a Mapper execution-context/v1 payload is required",
        )
    try:
        module = importlib.import_module("simplicio_mapper.execution_context")
        validate = module.validate_execution_context
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        raise MapperContextError(
            "MAPPER_EXECUTION_CONTEXT_API_UNAVAILABLE",
            "installed Mapper execution-context validator API is unavailable",
        ) from exc
    try:
        errors = validate(payload)
    except Exception as exc:  # external producer boundary; normalize its failure
        raise MapperContextError(
            "MAPPER_EXECUTION_CONTEXT_VALIDATOR_FAILED",
            "Mapper execution-context validator failed",
        ) from exc
    if not isinstance(errors, list) or errors:
        raise MapperContextError(
            "MAPPER_EXECUTION_CONTEXT_REJECTED",
            "Mapper rejected the execution-context envelope",
            reasons=tuple(
                MappingProxyType({"code": str(error), "path": "$.execution_context"}) for error in errors
            )
            if isinstance(errors, list)
            else (),
        )
    repository = _required_mapping(payload, "repository")
    expected = {
        "snapshot_id": snapshot.view.snapshot_id,
        "root_hash": snapshot.view.root_hash,
        "context_pack_hash": pack.pack_hash,
    }
    for field, value in expected.items():
        if repository.get(field) != value:
            raise MapperContextError(
                "CONTEXT_EXECUTION_ORIGIN_MISMATCH",
                f"execution-context repository.{field} does not match the supplied snapshot/pack",
            )
    return MappingProxyType(dict(payload))


def bind_mapper_context(
    snapshot_payload: Any,
    pack_payload: Any,
    *,
    source_root: str | None = None,
    execution_context_payload: Any | None = None,
) -> ContextBinding:
    """Validate snapshot + projection and derive their shared content handle."""

    snapshot = load_mapper_context(snapshot_payload, source_root=source_root)
    pack = load_mapper_context_pack(
        pack_payload,
        snapshot=snapshot,
        execution_context=execution_context_payload,
    )
    if execution_context_payload is not None:
        load_mapper_execution_context(
            execution_context_payload,
            snapshot=snapshot,
            pack=pack,
        )
    producer = snapshot.payload.get("producer")
    mapper_version = producer.get("version") if isinstance(producer, Mapping) else None
    if not isinstance(mapper_version, str) or not mapper_version:
        try:
            from simplicio_mapper import __version__ as mapper_version
        except ImportError as exc:
            raise MapperContextError(
                "MAPPER_VERSION_UNAVAILABLE", "Mapper producer version is unavailable"
            ) from exc
    fast_provenance = any(
        key in snapshot.payload
        for key in ("base_generation", "overlay_generation", "engine", "capability_digest", "source_hashes")
    )
    handle = ContextHandle(
        snapshot_id=snapshot.view.snapshot_id,
        revision=snapshot.view.revision,
        source_digest=snapshot.source_digest,
        pack_hash=pack.pack_hash,
        mapper_version=mapper_version,
        source_root_identity=snapshot.view.root_hash,
        projection_digest=pack.projection_digest,
        generation=str(snapshot.payload.get("generation") or snapshot.view.revision),
        repository=str(snapshot.payload.get("repository") or MAPPER_CONTRACT_OWNER),
        commit=str(snapshot.payload.get("commit") or MAPPER_CONTRACT_COMMIT),
        overlay=str(snapshot.payload.get("overlay") or ""),
        context_schema=MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
        base_generation=(
            str(
                snapshot.payload.get("base_generation")
                or snapshot.payload.get("generation")
                or snapshot.view.revision
            )
            if fast_provenance
            else ""
        ),
        overlay_generation=(
            str(snapshot.payload.get("overlay_generation") or snapshot.payload.get("overlay") or "")
            if fast_provenance
            else ""
        ),
        engine=str(snapshot.payload.get("engine") or ""),
        capability_digest=str(snapshot.payload.get("capability_digest") or ""),
        source_hashes=tuple(
            sorted(
                (str(item.get("path") or ""), str(item.get("sha256") or item.get("content_hash") or ""))
                for item in (snapshot.payload.get("source_hashes") or [])
                if isinstance(item, Mapping)
            )
        ),
    )
    handle.validate_engine_binding()
    return ContextBinding(snapshot=snapshot, pack=pack, context_handle=handle)


def verify_context_sources(
    binding: ContextBinding,
    *,
    source_root: str,
    paths: tuple[str, ...] | list[str] | None = None,
    expected_generation: str | None = None,
    delta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed when projected sources changed before effect dispatch.

    ``paths`` is a causal verification set supplied by the compiler. An
    absent set intentionally falls back to the complete ContextPack for old
    Mapper producers; this keeps the safety proof stronger than the fast path.
    """

    root = Path(source_root).resolve()
    if expected_generation is not None and binding.context_handle.generation != expected_generation:
        raise MapperContextError(
            "GENERATION_DRIFT",
            "context generation does not match the generation admitted for this attempt",
        )
    requested = {str(path).replace("\\", "/") for path in paths or ()}
    available = {str(entry["path"]).replace("\\", "/") for entry in binding.pack.files}
    unmatched = sorted(requested - available)
    if unmatched:
        raise MapperContextError(
            "CONTEXT_CAUSAL_PATH_UNBOUND",
            "causal verification path is absent from the bound ContextPack: " + ", ".join(unmatched),
        )
    verification_paths = requested
    fallback_reason: str | None = None
    engine = "python-bytes"
    delta_status = "unavailable"
    if delta is None:
        # A pre-delta Mapper producer has no causal invalidation proof. Keep
        # the safe compatibility path observable in the receipt instead of
        # silently treating a local causal set as a complete proof.
        verification_paths = set()
        fallback_reason = "delta_unavailable_full_verification"
        delta_status = "unavailable"
    else:
        delta_status, delta_reason, affected = _admit_mapper_delta(
            delta,
            binding.context_handle,
        )
        if delta_reason is not None:
            verification_paths = set()
            fallback_reason = delta_reason
        elif not requested:
            verification_paths = set()
            fallback_reason = "causal_set_absent_full_verification"
            delta_status = "accepted_without_causal_set"
        else:
            dirty = requested & affected
            if not dirty:
                # An accepted Mapper delta outside the plan's causal set does
                # not invalidate this attempt, so no source bytes are read.
                verification_paths = set()
                fallback_reason = "delta_no_causal_intersection"
                delta_status = "accepted_no_causal_intersection"
            else:
                verification_paths = dirty
                engine = "mapper-delta"
                fallback_reason = None
                delta_status = "accepted_causal_intersection"
    full_scan = fallback_reason is not None and fallback_reason != "delta_no_causal_intersection"
    entries = [
        entry
        for entry in binding.pack.files
        if full_scan or str(entry["path"]).replace("\\", "/") in verification_paths
    ]
    metrics: dict[str, Any] = {
        "files_considered": len(entries),
        "files_hashed": 0,
        "bytes_read": 0,
        "generation": binding.context_handle.generation,
        "paths_requested": sorted(requested),
        "paths_unmatched": [],
        "engine": engine,
        "fallback_reason": fallback_reason,
        "delta_status": delta_status,
    }
    for entry in entries:
        raw_path = str(entry["path"]).replace("\\", "/")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise MapperContextError(
                "CONTEXT_ROOT_PATH_MISMATCH", f"unsafe ContextPack source path: {raw_path}"
            )
        candidate = (root / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise MapperContextError(
                "CONTEXT_ROOT_PATH_MISMATCH", f"ContextPack source escapes root: {raw_path}"
            ) from exc
        try:
            content = candidate.read_bytes()
        except OSError as exc:
            raise MapperContextError(
                "SOURCE_DRIFT", f"ContextPack source is missing or unreadable: {raw_path}"
            ) from exc
        metrics["files_hashed"] += 1
        metrics["bytes_read"] += len(content)
        actual = hashlib.sha256(content).hexdigest()
        if actual != entry["snapshot_hash"]:
            raise MapperContextError("SOURCE_DRIFT", f"ContextPack source changed: {raw_path}")
    return metrics


def _admit_mapper_delta(
    delta: Mapping[str, Any],
    handle: ContextHandle,
) -> tuple[str, str | None, set[str]]:
    """Validate and admit Mapper's public graph-delta envelope.

    The schema is loaded from the installed Mapper package at runtime. Dev
    CLI owns neither the producer schema nor its event model, so it does not
    copy either into this repository. Any unavailable, malformed, stale, or
    ambiguous envelope falls back to the complete ContextPack verification.

    That includes the Mapper package itself refusing to resolve its own
    schema (``simplicio_mapper.contract.ContractError``, e.g. an install
    layout where the schema file the package expects is missing) —
    ``ContractError`` is a ``RuntimeError`` subclass, so it is caught here
    alongside the other "validator unavailable" cases rather than left to
    propagate past this fail-open boundary.
    """

    try:
        contract = importlib.import_module("simplicio_mapper.contract")
        # One path: Mapper's own `find_contract_root()` resolves the
        # versioned contracts tree via `importlib.resources` against the
        # installed `simplicio_mapper` package -- correct for both a real
        # wheel install and an editable/dev install, since the contracts
        # now live at `simplicio_mapper/contracts/` (in-package data)
        # rather than beside the package. This module does not resolve the
        # schema location itself; it only calls Mapper's own public API.
        package_root = contract.find_contract_root()
        schema = contract.load_schema(_MAPPER_GRAPH_DELTA_SCHEMA, package_root)
        errors = contract.validate_instance(dict(delta), schema)
    except (
        ImportError,
        ModuleNotFoundError,
        OSError,
        TypeError,
        ValueError,
        AttributeError,
        RuntimeError,
    ) as exc:
        return "unavailable", f"delta_validator_unavailable_full_verification:{type(exc).__name__}", set()
    if errors:
        return "invalid", "delta_invalid_full_verification", set()
    if (
        delta.get("event_type") != "delta"
        or delta.get("mode") != "incremental"
        or delta.get("full_rescan") is not False
        or (delta.get("fallback") or {}).get("required") is True
    ):
        return "ambiguous", "delta_requires_resync_full_verification", set()
    base_revision = delta.get("base_revision")
    generations = {
        str(value)
        for value in (
            getattr(handle, "generation", ""),
            getattr(handle, "revision", ""),
            getattr(handle, "base_generation", ""),
        )
        if value
    }
    if not isinstance(base_revision, str) or base_revision not in generations:
        return "stale", "delta_base_generation_mismatch_full_verification", set()
    if delta.get("scan_revision") == base_revision:
        return "ambiguous", "delta_same_generation_ambiguous_full_verification", set()
    raw_paths = delta.get("affected_paths")
    if not isinstance(raw_paths, list) or any(not isinstance(path, str) for path in raw_paths):
        return "invalid", "delta_affected_paths_invalid_full_verification", set()
    affected = {path.replace("\\", "/") for path in raw_paths if path}
    return "accepted", None, affected


def load_mapper_context(payload: Any, *, source_root: str | None = None) -> MapperContextAdapter:
    """Validate and adapt a canonical Mapper snapshot without altering it.

    The old Dev CLI shape is deliberately rejected even when it claims the
    canonical schema id.  Standalone callers that need non-Mapper context
    must use :data:`DEV_CLI_FALLBACK_CONTEXT_SCHEMA`; this function will not
    reinterpret it as Mapper context.
    """
    if _is_legacy_shadow(payload):
        raise MapperContextError(
            "LEGACY_CONTEXT_SNAPSHOT_REJECTED",
            "the retired Dev CLI snapshot shape cannot claim Mapper's schema id",
        )
    if not isinstance(payload, Mapping) or payload.get("schema") != MAPPER_CONTEXT_SNAPSHOT_SCHEMA:
        is_fallback = (
            isinstance(payload, Mapping) and payload.get("schema") == DEV_CLI_FALLBACK_CONTEXT_SCHEMA
        )
        code = "FALLBACK_CONTEXT_NOT_CANONICAL" if is_fallback else "UNSUPPORTED_CONTEXT_SCHEMA"
        raise MapperContextError(code, "a canonical Mapper context-snapshot/v1 payload is required")

    manifest = _read_manifest()
    validate_context_payload, canonical_json = _mapper_api()
    try:
        report = validate_context_payload(payload, source_root=source_root)
    except Exception as exc:  # Mapper is an external producer boundary; never leak its implementation error.
        raise MapperContextError(
            "MAPPER_VALIDATOR_FAILED", "Mapper validator failed while checking context"
        ) from exc
    reasons = report.get("reason_codes") if isinstance(report, Mapping) else None
    normalized_reasons = tuple(
        MappingProxyType({str(key): str(value) for key, value in reason.items()})
        for reason in reasons or ()
        if isinstance(reason, Mapping)
    )
    if not isinstance(report, Mapping) or report.get("valid") is not True:
        raise MapperContextError(
            "MAPPER_CONTEXT_REJECTED",
            "Mapper rejected the canonical context payload",
            reasons=normalized_reasons,
        )
    try:
        payload_bytes = bytes(canonical_json(payload))
        frozen_payload = _freeze(json.loads(payload_bytes.decode("utf-8")))
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise MapperContextError(
            "CANONICAL_PAYLOAD_UNAVAILABLE", "canonical Mapper payload cannot be preserved"
        ) from exc
    if not isinstance(frozen_payload, Mapping):  # defensive: Mapper accepted an object above.
        raise MapperContextError("CANONICAL_PAYLOAD_UNAVAILABLE", "canonical Mapper payload is not an object")
    freshness = frozen_payload["freshness"]
    fidelity = frozen_payload["fidelity"]
    graph = frozen_payload["graph"]
    view = MapperContextView(
        snapshot_id=str(frozen_payload["snapshot_id"]),
        revision=str(frozen_payload["revision"]),
        root_hash=str(frozen_payload["root_hash"]),
        graph_hash=str(freshness["graph_hash"]),
        freshness=freshness,
        fidelity=fidelity,
        source_handles=_source_handles(graph),
        source_set=tuple(str(item) for item in frozen_payload["source_set"]),
        needs_broader_context=bool(frozen_payload["needs_broader_context"]),
    )
    return MapperContextAdapter(
        payload_bytes=payload_bytes, payload=frozen_payload, view=view, manifest=manifest
    )


__all__ = [
    "ContextBinding",
    "ContextBindingCache",
    "ContextHandle",
    "DEV_CLI_CONTEXT_HANDLE_SCHEMA",
    "DEV_CLI_FALLBACK_CONTEXT_SCHEMA",
    "MAPPER_CONTRACT_COMMIT",
    "MAPPER_CONTRACT_MANIFEST_SHA256",
    "MAPPER_CONTEXT_PACK_SCHEMA",
    "MAPPER_CONTEXT_SNAPSHOT_SCHEMA",
    "MAPPER_EXECUTION_CONTEXT_SCHEMA",
    "MapperContextAdapter",
    "MapperContextError",
    "MapperContextPackAdapter",
    "MapperContextView",
    "bind_mapper_context",
    "load_mapper_context",
    "load_mapper_context_pack",
    "load_mapper_execution_context",
    "verify_context_sources",
]
