"""Changed-path delta handoff bound to a canonical Fast snapshot."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Iterable

from .adapters import parse_path
from .snapshot import Snapshot, source_files
from .workspace import (
    MANIFEST_SCHEMA,
    OVERLAY_SCHEMA,
    EffectiveSnapshot,
    GenerationId,
    Overlay,
    WorkspaceStore,
    _atomic_json,
    _canonical_json,
    _hash_source,
)

DELTA_SCHEMA = "simplicio.fast.delta/v1"
HANDOFF_SCHEMA = "simplicio.fast.handoff/v1"
SOURCE_SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".rs", ".cs"}


class DeltaError(ValueError):
    """A delta cannot be safely composed with its canonical base."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


@dataclass(frozen=True, slots=True)
class Delta:
    schema: str
    delta_generation: str
    base_generation: str
    base_commit: str
    base_config_fingerprint: str
    base_schema: str
    base_snapshot_sha256: str
    worktree_id: str
    changed: dict[str, dict[str, object]]
    created_at: str
    delta_sha256: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.schema,
                self.delta_generation,
                self.base_generation,
                self.base_commit,
                self.base_config_fingerprint,
                self.base_schema,
                self.base_snapshot_sha256,
                self.worktree_id,
                self.created_at,
                self.delta_sha256,
            )
        ):
            raise DeltaError("delta_field_invalid")
        if not isinstance(self.changed, dict):
            raise DeltaError("delta_shape_invalid")
        try:
            GenerationId(self.delta_generation)
            GenerationId(self.base_generation)
        except ValueError as error:
            raise DeltaError("delta_generation_invalid") from error
        if self.schema != DELTA_SCHEMA:
            raise DeltaError("delta_schema_mismatch")
        if self.base_schema != MANIFEST_SCHEMA:
            raise DeltaError("base_schema_mismatch")
        for field in (self.base_snapshot_sha256, self.delta_sha256):
            if not _is_digest(field):
                raise DeltaError("delta_digest_invalid")
        for path, record in self.changed.items():
            _validate_record(path, record)
        object.__setattr__(self, "changed", deepcopy(self.changed))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Delta":
        if not isinstance(value, dict):
            raise DeltaError("delta_shape_invalid")
        if value.get("schema") != DELTA_SCHEMA:
            raise DeltaError("delta_schema_mismatch")
        required = (
            "delta_generation",
            "base_generation",
            "base_commit",
            "base_config_fingerprint",
            "base_schema",
            "base_snapshot_sha256",
            "worktree_id",
            "created_at",
            "delta_sha256",
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise DeltaError("delta_field_missing", missing[0])
        if any(not isinstance(value[key], str) for key in required):
            raise DeltaError("delta_field_invalid")
        changed = value.get("changed")
        if not isinstance(changed, dict):
            raise DeltaError("delta_shape_invalid")
        normalized_changed: dict[str, dict[str, object]] = {}
        for path, record in changed.items():
            if not isinstance(path, str) or not isinstance(record, dict):
                raise DeltaError("delta_record_invalid")
            normalized = _normal_path(path)
            if normalized != path:
                raise DeltaError("delta_record_invalid")
            _validate_record(path, record)
            normalized_changed[path] = record
        return cls(
            schema=str(value["schema"]),
            delta_generation=str(value["delta_generation"]),
            base_generation=str(value["base_generation"]),
            base_commit=str(value["base_commit"]),
            base_config_fingerprint=str(value["base_config_fingerprint"]),
            base_schema=str(value["base_schema"]),
            base_snapshot_sha256=str(value["base_snapshot_sha256"]),
            worktree_id=str(value["worktree_id"]),
            changed=normalized_changed,
            created_at=str(value["created_at"]),
            delta_sha256=str(value["delta_sha256"]),
        )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_record(path: str, record: object) -> None:
    if not isinstance(record, dict):
        raise DeltaError("delta_record_invalid", path)
    required = {"sha256", "tombstone", "symbols"}
    if not required.issubset(record):
        raise DeltaError("delta_record_invalid", path)
    tombstone = record["tombstone"]
    symbols = record["symbols"]
    digest = record["sha256"]
    if not isinstance(tombstone, bool) or not isinstance(symbols, list):
        raise DeltaError("delta_record_invalid", path)
    if not all(isinstance(symbol, dict) for symbol in symbols):
        raise DeltaError("delta_record_invalid", path)
    if tombstone:
        if digest is not None or symbols:
            raise DeltaError("delta_record_invalid", path)
    elif not _is_digest(digest):
        raise DeltaError("delta_record_invalid", path)


def _normal_path(value: str) -> str:
    candidate = str(value).replace("\\", "/")
    if candidate.startswith("/") or (len(candidate) > 1 and candidate[1] == ":"):
        raise DeltaError("delta_path_invalid", f"invalid changed path: {value}")
    candidate = candidate.strip("/")
    if (
        not candidate
        or candidate in {".", ".."}
        or candidate.startswith("../")
        or "/../" in candidate
    ):
        raise DeltaError("delta_path_invalid", f"invalid changed path: {value}")
    if candidate.startswith(".simplicio/") or candidate == ".simplicio":
        raise DeltaError(
            "delta_path_derived", f"derived path is not a source delta: {value}"
        )
    return candidate


def _git_dir(root: Path) -> Path | None:
    marker = root / ".git"
    try:
        if marker.is_dir():
            return marker.resolve()
        content = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content.lower().startswith("gitdir:"):
        return None
    path = Path(content[7:].strip())
    return (root / path if not path.is_absolute() else path).resolve()


def _git_common_dir(root: Path) -> Path | None:
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    commondir = git_dir / "commondir"
    try:
        if commondir.is_file():
            content = commondir.read_text(encoding="utf-8").strip()
            path = Path(content)
            git_dir = (git_dir / path if not path.is_absolute() else path).resolve()
        return git_dir if git_dir.is_dir() else None
    except OSError:
        return None


def _git_commit(root: Path) -> str:
    git_dir = _git_dir(root)
    common_dir = _git_common_dir(root)
    if git_dir is None or common_dir is None:
        return "unknown"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            reference = head[5:]
            ref_path = common_dir / reference
            if ref_path.is_file():
                head = ref_path.read_text(encoding="utf-8").strip()
            else:
                packed_refs = common_dir / "packed-refs"
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    commit, _, packed_ref = line.partition(" ")
                    if packed_ref == reference:
                        head = commit
                        break
    except OSError:
        return "unknown"
    return (
        head
        if len(head) == 40 and all(c in "0123456789abcdef" for c in head)
        else "unknown"
    )


def _base_snapshot(
    store: WorkspaceStore, base_generation: str
) -> tuple[object, Path, str]:
    base = store.manifest(base_generation)
    if base.schema != MANIFEST_SCHEMA:
        raise DeltaError("base_schema_mismatch")
    base_root = Path(base.root).resolve() if base.root else None
    if base_root != store.root:
        base_common_dir = _git_common_dir(base_root) if base_root is not None else None
        store_common_dir = _git_common_dir(store.root)
        canonical_commit = (
            _git_commit(base_root) if base_root is not None else "unknown"
        )
        expected_commit = base.commit if base.commit != "unknown" else canonical_commit
        same_commit = (
            expected_commit != "unknown"
            and canonical_commit == expected_commit
            and _git_commit(store.root) == expected_commit
        )
        same_repository = (
            base_common_dir is not None and base_common_dir == store_common_dir
        )
        if not same_commit or not same_repository:
            raise DeltaError("base_root_mismatch")
    if not _is_digest(base.snapshot_sha256) or not _is_digest(base.source_tree_sha256):
        raise DeltaError("base_artifact_digest_missing")
    if _digest(base.source_hashes) != base.source_tree_sha256:
        raise DeltaError("base_source_tree_digest_mismatch")
    directory = (store.base_dir / base_generation).resolve()
    relative_snapshot = Path(base.snapshot)
    if relative_snapshot.is_absolute() or ".." in relative_snapshot.parts:
        raise DeltaError("base_snapshot_path_invalid")
    snapshot_path = (directory / relative_snapshot).resolve()
    if not snapshot_path.is_relative_to(directory):
        raise DeltaError("base_snapshot_path_invalid")
    if not snapshot_path.is_file():
        raise DeltaError("base_artifact_missing")
    actual = store.cached_validated_base(base_generation, base, snapshot_path)
    if actual is None:
        actual = _hash_source(snapshot_path)
        store.remember_validated_base(base_generation, base, snapshot_path, actual)
    if actual != base.snapshot_sha256:
        raise DeltaError("base_artifact_digest_mismatch")
    return base, snapshot_path, actual


def _delta_identity(delta: Delta) -> dict[str, object]:
    return {
        "schema": DELTA_SCHEMA,
        "base_generation": delta.base_generation,
        "base_commit": delta.base_commit,
        "base_config_fingerprint": delta.base_config_fingerprint,
        "base_schema": delta.base_schema,
        "base_snapshot_sha256": delta.base_snapshot_sha256,
        "worktree_id": delta.worktree_id,
        "changed": delta.changed,
    }


def _verify_delta(delta: Delta) -> None:
    digest = _digest(_delta_identity(delta))
    if digest != delta.delta_generation or digest != delta.delta_sha256:
        raise DeltaError("delta_digest_mismatch")


def _validate_delta_base(
    base_generation: str,
    delta: Delta,
    base,
    snapshot_sha256: str,
    config_fingerprint: str | None,
) -> None:
    if delta.base_generation != base_generation:
        raise DeltaError("base_generation_mismatch")
    if delta.base_commit != base.commit:
        raise DeltaError("base_commit_mismatch")
    if delta.base_config_fingerprint != base.config_fingerprint:
        raise DeltaError("config_fingerprint_mismatch")
    if config_fingerprint is not None and config_fingerprint != base.config_fingerprint:
        raise DeltaError("config_fingerprint_mismatch")
    if (
        delta.base_schema != base.schema
        or delta.base_snapshot_sha256 != snapshot_sha256
    ):
        raise DeltaError("base_artifact_digest_mismatch")


def _validate_composed_sources(
    store: WorkspaceStore,
    base,
    delta: Delta,
    scoped_paths: list[str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    if scoped_paths is None:
        current_hashes = {
            path.relative_to(store.root).as_posix(): store.source_hash(path)
            for path in source_files(store.root)
        }
    else:
        current_hashes = {}
        root = store.root.resolve()
        for relative in scoped_paths:
            path = (root / relative).resolve()
            if path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES:
                current_hashes[relative] = store.source_hash(path)
    expected_hashes = _composed_source_hashes(store, base, delta)
    verification_paths = (
        sorted(set(current_hashes) | set(expected_hashes))
        if scoped_paths is None
        else scoped_paths
    )
    for relative in verification_paths:
        if current_hashes.get(relative) == expected_hashes.get(relative):
            continue
        if relative not in delta.changed:
            raise DeltaError("delta_source_unlisted", relative)
        raise DeltaError("delta_source_stale", relative)
    return current_hashes, expected_hashes


def create_delta(
    store: WorkspaceStore,
    base_generation: str,
    worktree_id: str,
    changed_paths: Iterable[str] | None = None,
    *,
    config_fingerprint: str | None = None,
    _validated_base: tuple[object, Path, str] | None = None,
) -> Delta:
    store._worktree_id(worktree_id)
    if _validated_base is None:
        base, _, snapshot_sha256 = _base_snapshot(store, base_generation)
    else:
        base, _, snapshot_sha256 = _validated_base
    if config_fingerprint is not None and config_fingerprint != base.config_fingerprint:
        raise DeltaError("config_fingerprint_mismatch")
    requested = (
        None
        if changed_paths is None
        else sorted({_normal_path(path) for path in changed_paths})
    )
    if requested is None:
        current_paths = {
            path.relative_to(store.root).as_posix(): path
            for path in source_files(store.root)
        }
    else:
        current_paths = {}
        root = store.root.resolve()
        for relative in requested:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise DeltaError("delta_path_invalid", relative)
            if path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES:
                current_paths[relative] = path
    if requested is not None:
        missing = [
            path
            for path in requested
            if path not in current_paths and path not in base.source_hashes
        ]
        if missing:
            raise DeltaError("delta_path_missing", missing[0])
    candidates = sorted(
        set(current_paths) | set(base.source_hashes)
        if requested is None
        else set(requested)
    )
    changed: dict[str, dict[str, object]] = {}
    for relative in candidates:
        path = current_paths.get(relative)
        if path is None:
            if relative in base.source_hashes:
                changed[relative] = {"sha256": None, "tombstone": True, "symbols": []}
            continue
        digest = store.source_hash(path)
        if base.source_hashes.get(relative) == digest:
            continue
        changed[relative] = {
            "sha256": digest,
            "tombstone": False,
            "symbols": [asdict(symbol) for symbol in parse_path(path, relative)],
        }
    identity = {
        "schema": DELTA_SCHEMA,
        "base_generation": base_generation,
        "base_commit": base.commit,
        "base_config_fingerprint": base.config_fingerprint,
        "base_schema": base.schema,
        "base_snapshot_sha256": snapshot_sha256,
        "worktree_id": worktree_id,
        "changed": changed,
    }
    generation = _digest(identity)
    delta = Delta(
        DELTA_SCHEMA,
        generation,
        base_generation,
        base.commit,
        base.config_fingerprint,
        base.schema,
        snapshot_sha256,
        worktree_id,
        changed,
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        generation,
    )
    path = store.delta_dir / worktree_id / f"{generation}.json"
    if path.is_file():
        try:
            return load_delta(store, worktree_id, generation)
        except DeltaError:
            pass
    _atomic_json(path, delta.to_dict())
    store._receipt(
        "delta",
        {
            "base_generation": base_generation,
            "delta_generation": generation,
            "worktree_id": worktree_id,
            "changed_files": sorted(changed),
        },
    )
    return delta


def load_delta(store: WorkspaceStore, worktree_id: str, generation: str) -> Delta:
    store._worktree_id(worktree_id)
    GenerationId(generation)
    path = store.delta_dir / worktree_id / f"{generation}.json"
    cached = store.cached_delta(worktree_id, generation, path)
    if isinstance(cached, Delta):
        return cached
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DeltaError("delta_missing") from error
    delta = Delta.from_dict(value)
    if delta.delta_generation != generation or delta.worktree_id != worktree_id:
        raise DeltaError("delta_identity_mismatch")
    _verify_delta(delta)
    store.remember_delta(worktree_id, generation, path, delta)
    return delta


def compose_delta(
    store: WorkspaceStore,
    base_generation: str,
    worktree_id: str,
    delta_generation: str,
    *,
    config_fingerprint: str | None = None,
    changed_paths: Iterable[str] | None = None,
    _validated_base: tuple[object, Path, str] | None = None,
) -> EffectiveSnapshot:
    if _validated_base is None:
        base, snapshot_path, snapshot_sha256 = _base_snapshot(store, base_generation)
    else:
        base, snapshot_path, snapshot_sha256 = _validated_base
    delta = load_delta(store, worktree_id, delta_generation)
    _validate_delta_base(
        base_generation,
        delta,
        base,
        snapshot_sha256,
        config_fingerprint,
    )
    scoped_paths = (
        None
        if changed_paths is None
        else sorted({_normal_path(path) for path in changed_paths})
    )
    _current_hashes, _expected_hashes = _validate_composed_sources(
        store, base, delta, scoped_paths
    )
    overlay = Overlay(
        OVERLAY_SCHEMA,
        delta.delta_generation,
        base_generation,
        worktree_id,
        delta.changed,
        delta.created_at,
    )
    return EffectiveSnapshot(store.root, snapshot_path, base, overlay)


def _composed_source_hashes(
    store: WorkspaceStore, base, delta: Delta
) -> dict[str, str]:
    hashes = dict(base.source_hashes)
    for relative, record in delta.changed.items():
        if bool(record.get("tombstone")):
            hashes.pop(relative, None)
        else:
            hashes[relative] = str(record["sha256"])
    return hashes


def handoff(
    store: WorkspaceStore,
    base_generation: str,
    worktree_id: str,
    changed_paths: Iterable[str] | None = None,
    *,
    delta_generation: str | None = None,
    config_fingerprint: str | None = None,
    parity_snapshot: Path | None = None,
) -> dict[str, object]:
    scoped_paths = (
        None
        if changed_paths is None
        else sorted({_normal_path(path) for path in changed_paths})
    )
    cold_start = perf_counter()
    cpu_start = time.process_time()
    base_stage_start = perf_counter()
    base, snapshot_path, snapshot_sha256 = _base_snapshot(store, base_generation)
    if scoped_paths is None:
        with Snapshot(snapshot_path) as canonical:
            canonical_file_count = len(canonical.files())
    else:
        canonical_file_count = len(base.source_hashes)
    base_stage_ms = (perf_counter() - base_stage_start) * 1000
    cold_ms = (perf_counter() - cold_start) * 1000
    incremental_start = perf_counter()
    delta_stage_start = perf_counter()
    delta = (
        load_delta(store, worktree_id, delta_generation)
        if delta_generation
        else create_delta(
            store,
            base_generation,
            worktree_id,
            scoped_paths,
            config_fingerprint=config_fingerprint,
            _validated_base=(base, snapshot_path, snapshot_sha256),
        )
    )
    incremental_ms = (perf_counter() - incremental_start) * 1000
    delta_stage_ms = (perf_counter() - delta_stage_start) * 1000
    unchanged_delta = scoped_paths is not None and not delta.changed
    validated_current: dict[str, str] | None = None
    snapshot_validation_stage_start = perf_counter()
    if scoped_paths is not None:
        store.validate_snapshot(snapshot_path, snapshot_sha256)
        _validate_delta_base(
            base_generation,
            delta,
            base,
            snapshot_sha256,
            config_fingerprint,
        )
        if not unchanged_delta:
            validated_current, _ = _validate_composed_sources(
                store, base, delta, scoped_paths
            )
    snapshot_validation_ms = (
        perf_counter() - snapshot_validation_stage_start
    ) * 1000
    warm_start = perf_counter()
    compose_stage_start = perf_counter()
    if unchanged_delta:
        composed_symbol_count = None
        composed_symbol_count_reason = "unchanged_delta_not_materialized"
    elif scoped_paths is None:
        with compose_delta(
            store,
            base_generation,
            worktree_id,
            delta.delta_generation,
            config_fingerprint=config_fingerprint,
            changed_paths=scoped_paths,
            _validated_base=(base, snapshot_path, snapshot_sha256),
        ) as composed:
            composed_symbol_count: int | None = len(composed.symbols())
        composed_symbol_count_reason = None
    else:
        composed_symbol_count = None
        composed_symbol_count_reason = "scoped_query_not_materialized"
    compose_stage_ms = (perf_counter() - compose_stage_start) * 1000
    warm_ms = (perf_counter() - warm_start) * 1000
    parity_stage_start = perf_counter()
    if unchanged_delta:
        merged = base.source_hashes
        if validated_current is None:
            root = store.root.resolve()
            current = {}
            for relative in scoped_paths:
                path = (root / relative).resolve()
                if path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES:
                    current[relative] = store.source_hash(path)
        else:
            current = validated_current
    else:
        merged = _composed_source_hashes(store, base, delta)
        if scoped_paths is None:
            current = {
                path.relative_to(store.root).as_posix(): store.source_hash(path)
                for path in source_files(store.root)
            }
        else:
            current = validated_current or {}
    target = current
    parity_snapshot_hash = None
    if parity_snapshot is not None:
        with Snapshot(Path(parity_snapshot)) as candidate:
            target = {
                path: digest.hex()
                for path, digest in candidate.files()
                if scoped_paths is None or path in scoped_paths
            }
            parity_snapshot_hash = candidate.sha256
    if scoped_paths is None:
        parity = merged == target
        parity_scope = "full_source_tree"
    else:
        parity = all(
            current.get(relative) == merged.get(relative) for relative in scoped_paths
        )
        parity_scope = "explicit_changed_paths"
    parity_stage_ms = (perf_counter() - parity_stage_start) * 1000
    source_tree_sha256 = (
        base.source_tree_sha256 if unchanged_delta else _digest(merged)
    )
    cache_reuse = (
        len(base.source_hashes)
        if unchanged_delta
        else len(set(base.source_hashes) - set(delta.changed))
    )
    return {
        "schema": HANDOFF_SCHEMA,
        "status": "pass" if parity else "parity_mismatch",
        "base_generation": base_generation,
        "delta_generation": delta.delta_generation,
        "base_commit": base.commit,
        "config_fingerprint": base.config_fingerprint,
        "snapshot_hash": snapshot_sha256,
        "snapshot_sha256": snapshot_sha256,
        "delta_sha256": delta.delta_sha256,
        "mapped_bytes": snapshot_path.stat().st_size,
        "cpu_ms": round((time.process_time() - cpu_start) * 1000, 3),
        "parity_snapshot_hash": parity_snapshot_hash,
        "parity": parity,
        "parity_result": {
            "source_tree_sha256": source_tree_sha256,
            "target_tree_sha256": _digest(target),
            "scope": parity_scope,
            "canonical_file_count": canonical_file_count,
            "composed_symbol_count": composed_symbol_count,
            "composed_symbol_count_reason": composed_symbol_count_reason,
        },
        "changed_paths": sorted(delta.changed),
        "files_parsed": sum(
            1 for record in delta.changed.values() if not bool(record.get("tombstone"))
        ),
        "cache_reuse": cache_reuse,
        "timings_ms": {
            "cold_ms": round(cold_ms, 3),
            "warm_ms": round(warm_ms, 3),
            "incremental_ms": round(incremental_ms, 3),
        },
        "stage_timings_ms": {
            "base_validation_and_open": round(base_stage_ms, 3),
            "delta_load_or_create": round(delta_stage_ms, 3),
            "snapshot_structural_validation": round(snapshot_validation_ms, 3),
            "compose_and_validate": round(compose_stage_ms, 3),
            "source_verification_and_parity": round(parity_stage_ms, 3),
        },
    }
