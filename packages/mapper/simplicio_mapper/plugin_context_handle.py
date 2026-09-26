"""Versioned, content-addressed plugin context handles (#578/#603).

Mapper produces ``PluginContextHandle/v1`` and ``/v2``. Runtime only stores
the digest. Fast may materialize a derived packet. This module never executes
effects and never observes or claims provider prompt-cache state.

Version 1 remains the default for existing callers. Version 2 adds explicit
producer, generation, local-map-cache, and coverage fields while keeping the
handle bounded and deterministic. A v2 ``provider_prompt_cache`` is always
``null``: provider cache telemetry belongs to the runtime/provider boundary,
not to the mapper.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .context_cache import (
    LAYER_RENDERED_PACK,
    LAYER_SELECTED_CONTEXT,
    ContextCache,
    ContextCacheKey,
)

SCHEMA = "simplicio.plugin.context-handle/v1"
SCHEMA_V2 = "simplicio.plugin.context-handle/v2"
GENERATOR = "plugin-context-handle/1"
GENERATOR_V2 = "plugin-context-handle/2"
V2_CACHE_SCOPE = "local_mapper_artifact"
V2_CACHE_LAYER = "mapper_l1"
V2_CACHE_STATUSES = ("hit", "miss", "rebuilt", "stale", "unavailable", "error")
V2_COVERAGE_STATUSES = ("complete", "partial", "best_effort", "unproven")
_HANDLES: dict[str, dict[str, Any]] = {}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(root: Path, rel: str) -> str:
    path = root / rel
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _select_files(root: Path, changed: list[str], budget: int) -> list[dict[str, Any]]:
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        files.append(rel)
    if changed:
        preferred = [item for item in files if item in changed]
        dependents = [item for item in files if item not in changed]
        files = preferred + dependents
    selected: list[dict[str, Any]] = []
    used = 0
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        tokens = max(1, len(text) // 4)
        if selected and used + tokens > budget:
            break
        selected.append(
            {
                "path": rel,
                "sha256": _file_sha(root, rel),
                "span": {"start_line": 1, "end_line": text.count("\n") + 1},
                "tokens": tokens,
            }
        )
        used += tokens
    return selected


def _select_files_with_coverage(
    root: Path,
    changed: list[str],
    budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select bounded file spans and retain the omitted set for v2 coverage.

    The v1 path intentionally keeps its historical shape. V2 must not imply
    completeness when the token budget caused files to be omitted, so it uses
    this parallel selector that returns both selected and omitted descriptors.
    """
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        files.append(relative.as_posix())
    if changed:
        preferred = [item for item in files if item in changed]
        dependents = [item for item in files if item not in changed]
        files = preferred + dependents

    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used = 0
    for index, rel in enumerate(files):
        path = root / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        tokens = max(1, len(text) // 4)
        descriptor = {
            "path": rel,
            "sha256": _file_sha(root, rel),
            "span": {"start_line": 1, "end_line": text.count("\n") + 1},
            "tokens": tokens,
        }
        if selected and used + tokens > budget:
            omitted.extend(
                {
                    "path": later,
                    "sha256": _file_sha(root, later),
                }
                for later in files[index:]
            )
            break
        selected.append(descriptor)
        used += tokens
    return selected, omitted


def _sha256_prefixed(value: Any) -> str:
    return "sha256:" + _digest(value)


def _schema_major(value: Any) -> int | None:
    if not isinstance(value, str) or not value.startswith("simplicio.plugin.context-handle/v"):
        return None
    raw = value.rsplit("/v", 1)[-1].split(".", 1)[0]
    try:
        return int(raw)
    except ValueError:
        return None


def validate_plugin_context_handle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate v1/v2 handles without importing sibling repositories.

    The major version is fail-closed. A dotted minor (for example ``v2.1``)
    is accepted as additive-compatible as long as the v2 required fields are
    still structurally valid.
    """
    if not isinstance(payload, Mapping):
        return {"valid": False, "reason": "payload_not_object"}
    schema = payload.get("schema")
    major = _schema_major(schema)
    if major not in (1, 2):
        return {"valid": False, "reason": "unknown_schema_major"}
    if major == 1:
        required = ("schema", "status", "handle", "digest")
        if any(key not in payload for key in required):
            return {"valid": False, "reason": "missing_required_v1"}
        if payload.get("status") not in {"ready", "rejected"}:
            return {"valid": False, "reason": "invalid_status_v1"}
        return {"valid": True, "major": 1}

    required = ("schema", "context_id", "producer", "generation", "local_map_cache", "coverage")
    if any(key not in payload for key in required):
        return {"valid": False, "reason": "missing_required_v2"}
    if payload.get("provider_prompt_cache") not in (None,):
        return {"valid": False, "reason": "provider_cache_claim_forbidden"}
    producer = payload.get("producer")
    generation = payload.get("generation")
    local_cache = payload.get("local_map_cache")
    coverage = payload.get("coverage")
    if not isinstance(producer, Mapping) or producer.get("component") != "simplicio-mapper":
        return {"valid": False, "reason": "invalid_producer"}
    if not isinstance(generation, Mapping) or not isinstance(generation.get("id"), str):
        return {"valid": False, "reason": "invalid_generation"}
    if not isinstance(local_cache, Mapping) or local_cache.get("scope") != V2_CACHE_SCOPE:
        return {"valid": False, "reason": "invalid_local_cache_scope"}
    if local_cache.get("layer") != V2_CACHE_LAYER or local_cache.get("status") not in V2_CACHE_STATUSES:
        return {"valid": False, "reason": "invalid_local_cache"}
    if not isinstance(coverage, Mapping) or coverage.get("status") not in V2_COVERAGE_STATUSES:
        return {"valid": False, "reason": "invalid_coverage"}
    if not isinstance(coverage.get("omitted_count"), int) or coverage["omitted_count"] < 0:
        return {"valid": False, "reason": "invalid_coverage_count"}
    if coverage.get("status") == "complete" and coverage["omitted_count"] != 0:
        return {"valid": False, "reason": "complete_with_omissions"}
    return {"valid": True, "major": 2}


def _cache(root: Path) -> ContextCache:
    path = root / ".simplicio-loop" / "plugin-context-handle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return ContextCache(path)


def build_plugin_context_handle(
    root: str | Path,
    *,
    task_intent: Mapping[str, Any] | None = None,
    ref: str = "",
    changed_files: list[str] | None = None,
    token_budget: int = 512,
    fidelity: str = "spans",
    dirty: bool = False,
    schema_version: int = 1,
    producer_commit: str | None = None,
    artifact_digest: str | None = None,
    untracked_files: list[str] | None = None,
) -> dict[str, Any]:
    if schema_version == 2:
        return build_plugin_context_handle_v2(
            root,
            task_intent=task_intent,
            ref=ref,
            changed_files=changed_files,
            token_budget=token_budget,
            fidelity=fidelity,
            dirty=dirty,
            producer_commit=producer_commit,
            artifact_digest=artifact_digest,
            untracked_files=untracked_files,
        )
    if schema_version != 1:
        raise ValueError(f"unsupported plugin context handle major: {schema_version}")
    root_path = Path(root)
    intent = dict(task_intent or {})
    changed = list(changed_files or [])
    files = _select_files(root_path, changed, token_budget)
    identity = ContextCacheKey.for_files(
        str(root_path),
        [item["path"] for item in files],
        repo_identity=f"{root_path}:{ref}:{'dirty' if dirty else 'clean'}",
        mapper_schema_version=GENERATOR,
        query_task_hash=_digest(intent),
        token_budget=token_budget,
        renderer=fidelity,
        output_format="plugin-handle",
    )
    handle_id = identity.content_hash()
    cache = _cache(root_path)
    cached, _receipt = cache.get_entry(LAYER_RENDERED_PACK, identity)
    if cached is not None and not dirty:
        payload = dict(cached)
        payload["cache"] = {"hit": True, "key": handle_id}
        _HANDLES[handle_id] = payload
        return payload
    summary = {
        "files": len(files),
        "tokens": sum(item["tokens"] for item in files),
        "fidelity": fidelity,
        "task": str(intent.get("goal") or intent.get("fingerprint") or ""),
    }
    payload = {
        "schema": SCHEMA,
        "status": "ready",
        "handle": handle_id,
        "ref": ref,
        "dirty": dirty,
        "generation": GENERATOR,
        "summary": summary,
        "spans": files,
        "provenance": [{"path": item["path"], "sha256": item["sha256"]} for item in files],
        "token_budget": token_budget,
        "serialized_tokens": summary["tokens"],
        "digest": _digest({"handle": handle_id, "spans": files, "ref": ref}),
        "invalidation": {
            "content_hashes": [item["sha256"] for item in files],
            "changed_files": changed,
        },
        "cache": {"hit": False, "key": handle_id},
        "fidelity": {
            "requested": fidelity,
            "delivered": "spans" if files else "empty",
            "abstained": not files,
        },
    }
    cache.put(LAYER_RENDERED_PACK, identity, {k: v for k, v in payload.items() if k != "cache"})
    _HANDLES[handle_id] = payload
    return payload


def build_plugin_context_handle_v2(
    root: str | Path,
    *,
    task_intent: Mapping[str, Any] | None = None,
    ref: str = "",
    changed_files: list[str] | None = None,
    token_budget: int = 512,
    fidelity: str = "spans",
    dirty: bool = False,
    producer_commit: str | None = None,
    artifact_digest: str | None = None,
    untracked_files: list[str] | None = None,
) -> dict[str, Any]:
    """Build the bounded v2 handle while preserving v1 as the default API."""
    root_path = Path(root)
    intent = dict(task_intent or {})
    changed = sorted(set(changed_files or []))
    untracked = sorted(set(untracked_files or []))
    selected, omitted = _select_files_with_coverage(root_path, changed, token_budget)
    all_rows = sorted(
        [{"path": item["path"], "sha256": item["sha256"]} for item in selected]
        + omitted,
        key=lambda item: item["path"],
    )
    generation_basis = {
        "schema": "simplicio.repository-generation/v2",
        "scope": "working_tree",
        "ref": ref,
        "dirty_content_included": bool(dirty),
        "changed_files": changed,
        "untracked_files": untracked,
        "files": all_rows,
    }
    generation_id = _sha256_prefixed(generation_basis)
    producer = {
        "component": "simplicio-mapper",
        "version": _package_version(),
        "commit": producer_commit or (ref or None),
        "artifact_digest": artifact_digest,
    }
    cache_identity = ContextCacheKey.for_files(
        str(root_path),
        [item["path"] for item in all_rows],
        repo_identity=f"{ref}:plugin-context-handle/v2",
        mapper_schema_version=GENERATOR_V2,
        query_task_hash=_digest(intent),
        token_budget=token_budget,
        renderer=fidelity,
        output_format="plugin-handle-v2",
    )
    selected_identity = ContextCacheKey.for_files(
        str(root_path),
        [item["path"] for item in all_rows],
        repo_identity=f"{ref}:plugin-context-handle/v2",
        mapper_schema_version=GENERATOR_V2,
        query_task_hash=_digest(intent),
        token_budget=token_budget,
        renderer="selected-context-v2",
        output_format="plugin-selected-context-v2",
    )
    cache_key = "sha256:" + cache_identity.content_hash()
    cached: dict[str, Any] | None = None
    cache_receipt: dict[str, Any] | None = None
    cache_status = "rebuilt" if dirty else "miss"
    cache_reason = "dirty_rebuild" if dirty else "cache_miss"
    cache: ContextCache | None = None
    try:
        cache = _cache(root_path)
        if not dirty:
            cached, _receipt = cache.get_entry(
                LAYER_RENDERED_PACK,
                cache_identity,
                expected_generation=generation_id,
            )
            cache_receipt = _receipt.to_dict()
            if _receipt.outcome == "corrupt":
                cache_status = "stale"
                cache_reason = "corrupt_entry_recomputed"
        if cached is not None:
            payload = dict(cached)
            payload["local_map_cache"] = {
                "scope": V2_CACHE_SCOPE,
                "layer": V2_CACHE_LAYER,
                "status": "hit",
                "key": cache_key,
                "reason": "cache_hit",
                "receipt": cache_receipt,
                "lookup_receipt": cache_receipt,
            }
            _HANDLES[str(payload["context_id"])]=payload
            return payload
    except (OSError, ValueError, TypeError):
        cache_status = "unavailable"
        cache_reason = "cache_unavailable"

    coverage_status = "complete" if not omitted else "partial"
    summary = {
        "files": len(selected),
        "tokens": sum(item["tokens"] for item in selected),
        "fidelity": fidelity,
        "task": str(intent.get("goal") or intent.get("fingerprint") or ""),
    }
    stable = {
        "schema": SCHEMA_V2,
        "producer": producer,
        "generation": {
            "schema": "simplicio.repository-generation/v2",
            "id": generation_id,
            "scope": "working_tree",
            "dirty_content_included": bool(dirty),
            "untracked_files": untracked,
        },
        "coverage": {
            "status": coverage_status,
            "truncated": bool(omitted),
            "omitted_count": len(omitted),
        },
        "spans": selected,
        "changed_files": changed,
        "ref": ref,
        "token_budget": token_budget,
    }
    context_id = _sha256_prefixed(stable)
    payload = {
        **stable,
        "context_id": context_id,
        "status": "ready",
        "handle": context_id,
        "summary": summary,
        "provenance": [{"path": item["path"], "sha256": item["sha256"]} for item in selected],
        "token_budget": token_budget,
        "serialized_tokens": summary["tokens"],
        "digest": _digest(stable),
        "invalidation": {
            "content_hashes": [item["sha256"] for item in all_rows],
            "changed_files": changed,
            "untracked_files": untracked,
        },
        "local_map_cache": {
            "scope": V2_CACHE_SCOPE,
            "layer": V2_CACHE_LAYER,
            "status": cache_status,
            "key": cache_key,
            "reason": cache_reason,
            "receipt": cache_receipt,
            "lookup_receipt": cache_receipt,
        },
        "provider_prompt_cache": None,
        "fidelity": {
            "requested": fidelity,
            "delivered": "spans" if selected else "empty",
            "abstained": not selected,
        },
    }
    validation = validate_plugin_context_handle(payload)
    if not validation["valid"]:
        raise ValueError(f"invalid v2 context handle: {validation['reason']}")
    try:
        if cache is None:
            raise OSError("cache unavailable")
        cache.put(
            LAYER_SELECTED_CONTEXT,
            selected_identity,
            {"generation": generation_id, "spans": selected},
            generation=generation_id,
        )
        cache.put(
            LAYER_RENDERED_PACK,
            cache_identity,
            {key: value for key, value in payload.items() if key != "local_map_cache"},
            generation=generation_id,
        )
        receipts = cache.receipts()
        if receipts:
            write_receipt = receipts[-1]
            payload["local_map_cache"]["write_receipt"] = write_receipt
            if cache_status != "stale":
                payload["local_map_cache"]["receipt"] = write_receipt
    except (OSError, ValueError, TypeError):
        payload["local_map_cache"] = {
            **payload["local_map_cache"],
            "status": "unavailable",
            "reason": "cache_write_unavailable",
        }
    _HANDLES[context_id] = payload
    return payload


def _package_version() -> str:
    try:
        from . import __version__

        return str(__version__)
    except (ImportError, AttributeError):
        return "unknown"


def project_v1_handle_to_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a legacy v1 handle into the conservative v2 vocabulary."""
    check = validate_plugin_context_handle(payload)
    if not check["valid"] or check.get("major") != 1:
        raise ValueError(f"cannot project invalid v1 handle: {check['reason']}")
    spans = [item for item in payload.get("spans", []) if isinstance(item, Mapping)]
    dirty = bool(payload.get("dirty"))
    generation_id = _sha256_prefixed(
        {
            "schema": "simplicio.repository-generation/v2",
            "scope": "working_tree",
            "ref": str(payload.get("ref") or ""),
            "dirty_content_included": dirty,
            "files": [
                {"path": item.get("path", ""), "sha256": item.get("sha256", "")}
                for item in spans
            ],
        }
    )
    projected = {
        "schema": SCHEMA_V2,
        "status": payload.get("status", "ready"),
        "context_id": _sha256_prefixed({"legacy_handle": payload.get("handle", ""), "generation": generation_id}),
        "handle": payload.get("handle"),
        "producer": {
            "component": "simplicio-mapper",
            "version": _package_version(),
            "commit": payload.get("ref") or None,
            "artifact_digest": None,
        },
        "generation": {
            "schema": "simplicio.repository-generation/v2",
            "id": generation_id,
            "scope": "working_tree",
            "dirty_content_included": dirty,
        },
        "local_map_cache": {
            "scope": V2_CACHE_SCOPE,
            "layer": V2_CACHE_LAYER,
            "status": "hit" if payload.get("cache", {}).get("hit") else "miss",
            "key": str(payload.get("cache", {}).get("key") or payload.get("handle") or ""),
            "reason": "projected_from_v1",
        },
        "coverage": {
            "status": "complete" if spans else "unproven",
            "truncated": False,
            "omitted_count": 0,
        },
        "spans": spans,
        "provenance": payload.get("provenance", []),
        "provider_prompt_cache": None,
        "digest": _digest({"legacy": dict(payload), "generation": generation_id}),
    }
    return projected


def fetch_plugin_context_handle(handle: str, *, expected_digest: str = "") -> dict[str, Any]:
    payload = _HANDLES.get(handle)
    if payload is None:
        return {"schema": SCHEMA, "status": "rejected", "reason": "unknown_handle", "handle": handle}
    if expected_digest and payload.get("digest") != expected_digest:
        return {"schema": SCHEMA, "status": "rejected", "reason": "tampered_or_stale", "handle": handle}
    validation = validate_plugin_context_handle(payload)
    if not validation["valid"]:
        return {
            "schema": payload.get("schema", SCHEMA),
            "status": "rejected",
            "reason": validation["reason"],
            "handle": handle,
        }
    return payload


def invalidate_plugin_context_handles() -> None:
    _HANDLES.clear()
