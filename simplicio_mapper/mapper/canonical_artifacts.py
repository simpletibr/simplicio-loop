"""Canonical metadata and digest rules for public Mapper artifacts.

The five public ``simplicio.*-index/v1``/``simplicio.project-map/v1``
artifacts share one envelope.  This module is deliberately small and pure
enough to be used by both the synchronous and asynchronous Python pipelines.
It does not make a parser or backend claim parity; the caller supplies the
capability/degradation facts observed during the run.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any

import orjson

from .. import __version__

CANONICAL_SCHEMA_VERSION = "v1"
CANONICAL_DIGEST_PREFIX = "sha256:"

CAPABILITY_NAMES = ("files", "symbols", "relationships", "precedent", "architecture")
CAPABILITY_STATES = ("full", "partial", "empty", "unsupported")
_OMISSION_DIRS = {
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "output",
    "target",
    "test-results",
    "playwright-report",
}
_OMISSION_SCAN_DIRS = {".git", ".simplicio", ".venv", "venv", "__pycache__"}

_ARTIFACT_CAPABILITIES: dict[str, dict[str, str]] = {
    "project_map": {
        "files": "files",
        "symbols": "unsupported",
        "relationships": "unsupported",
        "precedent": "unsupported",
        "architecture": "architecture",
    },
    "symbol_index": {
        "files": "unsupported",
        "symbols": "symbols",
        "relationships": "unsupported",
        "precedent": "unsupported",
        "architecture": "unsupported",
    },
    "call_graph": {
        "files": "unsupported",
        "symbols": "unsupported",
        "relationships": "edges",
        "precedent": "unsupported",
        "architecture": "unsupported",
    },
    "precedent_index": {
        "files": "unsupported",
        "symbols": "unsupported",
        "relationships": "unsupported",
        "precedent": "items",
        "architecture": "unsupported",
    },
    "architecture_inventory": {
        "files": "files",
        "symbols": "symbols",
        "relationships": "relationships",
        "precedent": "unsupported",
        "architecture": "modules",
    },
}


def _run_git(cwd: str, args: list[str], timeout: float = 2.0) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _repository_id(cwd: str) -> str:
    top_level = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    is_repository_root = top_level is not None and os.path.realpath(top_level) == os.path.realpath(cwd)
    remote = _run_git(cwd, ["config", "--get", "remote.origin.url"]) if is_repository_root else None
    if remote:
        seed = f"remote:{remote.strip()}"
    else:
        common_dir = _run_git(cwd, ["rev-parse", "--git-common-dir"]) if is_repository_root else None
        seed = f"git-common-dir:{os.path.realpath(os.path.join(cwd, common_dir))}" if common_dir else f"path:{os.path.realpath(cwd)}"
    return CANONICAL_DIGEST_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _source_generation(cwd: str) -> dict[str, Any]:
    top_level = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    is_repository_root = top_level is not None and os.path.realpath(top_level) == os.path.realpath(cwd)
    revision = _run_git(cwd, ["rev-parse", "HEAD"]) if is_repository_root else None
    status = (
        _run_git(cwd, ["status", "--porcelain", "--untracked-files=all"], timeout=3.0)
        if is_repository_root
        else None
    )
    if is_repository_root:
        return {
            "kind": "git-working-tree",
            "revision": revision,
            "dirty": bool(status),
        }
    return {
        "kind": "filesystem",
        "revision": None,
        "dirty": False,
    }


def _semantic_value(value: Any, key: str | None = None) -> Any:
    """Remove run-local fields before hashing semantic artifact content.

    ``root``, ``generated_at`` and per-file ``last_modified`` are operational
    observations, not repository semantics.  Object keys are sorted by
    ``orjson``; arrays are intentionally left in producer-defined canonical
    order and are documented per artifact in the contract.
    """
    if key in {"generated_at", "last_modified"}:
        return None
    if key == "root":
        return "<repository-root>"
    if isinstance(value, dict):
        return {
            child_key: _semantic_value(child_value, child_key)
            for child_key, child_value in value.items()
            if child_key != "producer" and child_key not in {"generated_at", "last_modified"}
        }
    if isinstance(value, list):
        return [_semantic_value(item, key) for item in value]
    return value


def canonical_digest(artifact: dict[str, Any]) -> str:
    """Return the v1 digest of semantic content, excluding producer metadata."""
    semantic = _semantic_value(artifact)
    encoded = orjson.dumps(semantic, option=orjson.OPT_SORT_KEYS)
    return CANONICAL_DIGEST_PREFIX + hashlib.sha256(encoded).hexdigest()


def _capability_state(
    payload: dict[str, Any],
    capability: str,
    source_field: str,
    degraded_paths: list[str],
    omitted_paths: list[str],
) -> str:
    if source_field == "unsupported":
        return "unsupported"
    value = payload.get(source_field)
    count = len(value) if isinstance(value, (list, dict, str)) else int(bool(value))
    if count == 0:
        return "empty"
    if capability == "relationships":
        coverage = payload.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        relation_coverage = payload.get("relationship_coverage")
        relation_coverage = relation_coverage if isinstance(relation_coverage, dict) else coverage
        if relation_coverage.get("truncated") or relation_coverage.get("status") == "degraded":
            return "partial"
    if degraded_paths or omitted_paths:
        return "partial"
    return "full"


def _capability_coverage(
    artifact_name: str,
    payload: dict[str, Any],
    degraded_paths: list[str],
    omitted_paths: list[str],
) -> dict[str, str]:
    sources = _ARTIFACT_CAPABILITIES[artifact_name]
    return {
        capability: _capability_state(
            payload,
            capability,
            sources[capability],
            degraded_paths,
            omitted_paths,
        )
        for capability in CAPABILITY_NAMES
    }


def _metadata(
    cwd: str,
    artifact_name: str,
    payload: dict[str, Any],
    source_generation: dict[str, Any],
    degraded_paths: list[str],
    omitted_paths: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "component": "simplicio-mapper",
        "version": __version__,
        "backend": "python",
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "repository_id": _repository_id(cwd),
        "source_generation": source_generation,
        "capability_coverage": _capability_coverage(
            artifact_name, payload, degraded_paths, omitted_paths
        ),
        "degraded_paths": sorted(set(degraded_paths)),
        "omitted_paths": sorted(set(omitted_paths)),
        "canonical_digest": "",
    }
    return metadata


def _paths_from_degraded(degraded: dict[str, Any]) -> tuple[list[str], list[str]]:
    degraded_paths: list[str] = []
    omitted_paths: list[str] = []
    for path in degraded.get("skipped_large_files", []) or []:
        normalized = str(path).replace(os.sep, "/")
        omitted_paths.append(f"files:{normalized}")
    if degraded.get("git_timeout"):
        degraded_paths.append("metadata:git-status")
    if degraded.get("git_status_unavailable"):
        degraded_paths.append("metadata:git-status")
    return degraded_paths, omitted_paths


def _known_omitted_paths(cwd: str) -> list[str]:
    """Report generated directories and symlinks the mapper intentionally skips."""
    omitted: list[str] = []

    def visit(directory: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            relative = os.path.relpath(entry.path, cwd).replace(os.sep, "/")
            if entry.is_symlink():
                omitted.append(f"symlink:{relative}")
            elif entry.is_dir(follow_symlinks=False):
                if entry.name in _OMISSION_DIRS:
                    omitted.append(f"generated:{relative}")
                elif entry.name not in _OMISSION_SCAN_DIRS:
                    visit(entry.path)

    visit(cwd)
    return omitted


def attach_canonical_metadata(
    cwd: str,
    artifacts: dict[str, dict[str, Any]],
    degraded: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Attach the required producer envelope to all five public artifacts."""
    degraded_paths, omitted_paths = _paths_from_degraded(degraded or {})
    omitted_paths.extend(_known_omitted_paths(cwd))
    generation = _source_generation(cwd)
    for artifact_name, payload in artifacts.items():
        metadata = _metadata(
            cwd,
            artifact_name,
            payload,
            generation,
            degraded_paths,
            omitted_paths,
        )
        payload["producer"] = metadata
        metadata["canonical_digest"] = canonical_digest(payload)
    return artifacts


__all__ = [
    "CANONICAL_DIGEST_PREFIX",
    "CANONICAL_SCHEMA_VERSION",
    "CAPABILITY_NAMES",
    "CAPABILITY_STATES",
    "attach_canonical_metadata",
    "canonical_digest",
]
