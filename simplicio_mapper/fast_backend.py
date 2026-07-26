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
SUPPORTED_SNAPSHOT_SCHEMAS = {"simplicio.context-snapshot/v1"}
SUPPORTED_EDGE_KINDS = {"calls", "imports", "references", "defined_in", "depends_on"}


@dataclass(frozen=True)
class BackendResolution:
    artifacts: dict[str, dict]
    receipt: dict[str, Any]


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
    "diagnose_fast",
    "resolve_backend",
    "write_backend_receipt",
]
