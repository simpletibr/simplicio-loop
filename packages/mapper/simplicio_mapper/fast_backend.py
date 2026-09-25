"""Simplicio Fast adapter behind the Mapper's canonical ContextGraph contract."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FAST_MANIFEST_SCHEMA = "simplicio.fast-context/v1"
FAST_RECEIPT_SCHEMA = "simplicio.mapper-fast-backend-receipt/v1"
FAST_HANDLE_SCHEMA = "simplicio.fast-context-handle/v1"
SUPPORTED_SNAPSHOT_SCHEMAS = {"simplicio.context-snapshot/v1"}
SUPPORTED_EDGE_KINDS = {"calls", "imports", "references", "defined_in", "depends_on"}


@dataclass(frozen=True)
class BackendResolution:
    artifacts: dict[str, dict]
    receipt: dict[str, Any]


@dataclass(frozen=True)
class FastContextHandle:
    """Stable, engine-neutral identity for a Fast context projection.

    The handle is deliberately semantic: consumers bind to repository/commit,
    generations, schema and capability/source digests.  It never carries mmap
    offsets, segment paths, or any other implementation detail that would make
    a Python and Rust projection incompatible.
    """

    repository: str
    commit: str
    base_generation: str
    overlay_generation: str = ""
    engine: str = ""
    capability_digest: str = ""
    source_hashes: tuple[tuple[str, str], ...] = ()
    schema: str = FAST_HANDLE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "repository": self.repository,
            "commit": self.commit,
            "base_generation": self.base_generation,
            "overlay_generation": self.overlay_generation or None,
            "engine": self.engine or None,
            "capability_digest": self.capability_digest or None,
            "source_hashes": {key: value for key, value in self.source_hashes},
        }
        return payload

    @property
    def digest(self) -> str:
        return _stable_hash(self.to_dict())

    def validate(self) -> None:
        if self.schema != FAST_HANDLE_SCHEMA:
            raise ValueError("unsupported Fast context handle schema")
        for name in ("repository", "commit", "base_generation"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Fast context handle requires {name}")
        if self.engine and self.engine not in {"python", "rust"}:
            raise ValueError("Fast context handle engine must be python or rust")
        hashes = dict(self.source_hashes)
        for path, digest in hashes.items():
            if not path or "/" not in path and path.startswith("."):
                raise ValueError("Fast context handle source hash key must be a logical path")
            if not isinstance(digest, str) or len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError(f"invalid source hash for {path}")
        if any("offset" in key.casefold() or "mmap" in key.casefold() for key in self.to_dict()):
            raise ValueError("Fast context handle cannot expose storage offsets")

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, Any],
        *,
        repository: str,
        commit: str,
        overlay_generation: str = "",
        engine: str = "",
    ) -> "FastContextHandle":
        projections = manifest.get("projections") if isinstance(manifest.get("projections"), Mapping) else {}
        source_hashes: dict[str, str] = {}
        for item in projections.get("files") or []:
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path") or "")
            digest = str(item.get("content_hash") or item.get("source_hash") or item.get("sha256") or "")
            if path and digest:
                source_hashes[path] = digest.removeprefix("sha256:")
        handle = cls(
            repository=str(repository),
            commit=str(commit),
            base_generation=str(manifest.get("generation") or ""),
            overlay_generation=str(overlay_generation),
            engine=str(engine),
            capability_digest=_stable_hash(manifest.get("capabilities") or {}),
            source_hashes=tuple(sorted(source_hashes.items())),
        )
        handle.validate()
        return handle


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _capability_error(manifest: Mapping[str, Any]) -> str | None:
    if manifest.get("schema") != FAST_MANIFEST_SCHEMA:
        return "fast_schema_incompatible"
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return "fast_capabilities_missing"
    snapshots = set(capabilities.get("snapshot_schemas") or [])
    if not snapshots.intersection(SUPPORTED_SNAPSHOT_SCHEMAS):
        return "context_snapshot_schema_unsupported"
    unsupported_edges = set(capabilities.get("edge_kinds") or []) - SUPPORTED_EDGE_KINDS
    if unsupported_edges:
        return "edge_capability_unsupported:" + ",".join(sorted(unsupported_edges))
    if not isinstance(manifest.get("generation"), str) or not manifest["generation"]:
        return "fast_generation_missing"
    if not isinstance(manifest.get("projections"), Mapping):
        return "fast_projections_missing"
    return None


def _translate(manifest: Mapping[str, Any], local: Mapping[str, dict]) -> dict[str, dict]:
    projections = manifest["projections"]
    files = list(projections.get("files") or [])
    symbols = list(projections.get("symbols") or [])
    edges = list(projections.get("edges") or [])
    if not files:
        raise ValueError("fast_files_projection_empty")
    project_map = {
        **dict(local.get("project_map") or {}),
        "files": files,
    }
    symbol_index = {
        **dict(local.get("symbol_index") or {}),
        "symbols": symbols,
        "counts": {"symbols": len(symbols)},
    }
    call_graph = {
        **dict(local.get("call_graph") or {}),
        "edges": edges,
        "counts": {"edges": len(edges)},
    }
    architecture = projections.get("architecture_inventory")
    return {
        "project_map": project_map,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
        "architecture_inventory": (
            dict(architecture)
            if isinstance(architecture, Mapping)
            else dict(local.get("architecture_inventory") or {})
        ),
    }


def resolve_backend(
    *,
    root: str,
    local_artifacts: Mapping[str, dict],
    mode: str = "auto",
    manifest_path: str = "",
) -> BackendResolution:
    selected_mode = (mode or "auto").strip().casefold()
    if selected_mode not in {"auto", "fast", "mapper"}:
        raise ValueError(f"unsupported context backend: {mode}")
    resolved_path = manifest_path or os.environ.get("SIMPLICIO_FAST_CONTEXT_MANIFEST", "")
    receipt: dict[str, Any] = {
        "schema": FAST_RECEIPT_SCHEMA,
        "requested_backend": selected_mode,
        "selected_backend": "mapper",
        "status": "fallback" if selected_mode != "mapper" else "ok",
        "reason": "mapper_backend_selected" if selected_mode == "mapper" else "fast_manifest_absent",
        "generation": None,
        "manifest_path": resolved_path or None,
        "capabilities": None,
        "projection_hash": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if selected_mode == "mapper":
        return BackendResolution(dict(local_artifacts), receipt)
    manifest = _read_json(resolved_path) if resolved_path else {}
    error = _capability_error(manifest) if manifest else "fast_manifest_absent"
    if error is None:
        try:
            artifacts = _translate(manifest, local_artifacts)
        except ValueError as exc:
            error = str(exc)
        else:
            context_handle = None
            repository = manifest.get("repository")
            commit = manifest.get("commit") or manifest.get("source_commit")
            if repository and commit:
                try:
                    context_handle = FastContextHandle.from_manifest(
                        manifest,
                        repository=str(repository),
                        commit=str(commit),
                        overlay_generation=str(manifest.get("overlay_generation") or ""),
                        engine=str(manifest.get("engine") or ""),
                    )
                except ValueError as exc:
                    receipt["reason"] = "fast_context_handle_invalid:" + str(exc)
                    receipt["status"] = "degraded"
                    return BackendResolution(dict(local_artifacts), receipt)
            receipt.update(
                {
                    "selected_backend": "fast",
                    "status": "ok",
                    "reason": "fast_projection_accepted",
                    "generation": manifest["generation"],
                    "capabilities": dict(manifest["capabilities"]),
                    "projection_hash": _stable_hash(manifest["projections"]),
                }
            )
            if context_handle is not None:
                receipt["context_handle"] = context_handle.to_dict()
                receipt["context_handle_digest"] = context_handle.digest
            return BackendResolution(artifacts, receipt)
    receipt["reason"] = error
    receipt["status"] = "degraded"
    return BackendResolution(dict(local_artifacts), receipt)


def write_backend_receipt(root: str, out: str, receipt: Mapping[str, Any]) -> str:
    path = Path(root, out, "fast-backend-receipt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return str(path)


def diagnose_fast(manifest_path: str = "") -> dict[str, Any]:
    resolved_path = manifest_path or os.environ.get("SIMPLICIO_FAST_CONTEXT_MANIFEST", "")
    manifest = _read_json(resolved_path) if resolved_path else {}
    error = _capability_error(manifest) if manifest else "fast_manifest_absent"
    return {
        "schema": "simplicio.mapper-fast-doctor/v1",
        "available": bool(manifest),
        "compatible": error is None,
        "reason": error or "compatible",
        "manifest_path": resolved_path or None,
        "generation": manifest.get("generation") if manifest else None,
        "capabilities": manifest.get("capabilities") if manifest else None,
    }


__all__ = [
    "BackendResolution",
    "FastContextHandle",
    "diagnose_fast",
    "resolve_backend",
    "write_backend_receipt",
]
