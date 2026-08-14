"""Plugin v1 content-addressed context handle (#578).

Mapper produces ``PluginContextHandle/v1``. Runtime only stores the digest.
Fast may materialize a derived packet. This module never executes effects.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .context_cache import (
    LAYER_RENDERED_PACK,
    ContextCache,
    ContextCacheKey,
)

SCHEMA = "simplicio.plugin.context-handle/v1"
GENERATOR = "plugin-context-handle/1"
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


def _cache(root: Path) -> ContextCache:
    path = root / ".simplicio" / "plugin-context-handle.json"
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
) -> dict[str, Any]:
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


def fetch_plugin_context_handle(handle: str, *, expected_digest: str = "") -> dict[str, Any]:
    payload = _HANDLES.get(handle)
    if payload is None:
        return {"schema": SCHEMA, "status": "rejected", "reason": "unknown_handle", "handle": handle}
    if expected_digest and payload.get("digest") != expected_digest:
        return {"schema": SCHEMA, "status": "rejected", "reason": "tampered_or_stale", "handle": handle}
    return payload


def invalidate_plugin_context_handles() -> None:
    _HANDLES.clear()
