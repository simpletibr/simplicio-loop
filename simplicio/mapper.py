"""Structured mapper artifact loading for simplicio-dev-cli.

The mapper repo produces optional JSON artifacts. This module keeps their
consumer contract small, deterministic, and backward compatible with projects
that only have source files.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .utils.serialization import loads


PROJECT_MAP_CANDIDATES = (
    ".simplicio/project-map.json",
    "project-map.json",
    ".mapper/project-map.json",
)
PRECEDENT_INDEX_CANDIDATES = (
    ".simplicio/precedent-index.json",
    "precedent-index.json",
    ".mapper/precedent-index.json",
)


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        data = loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_artifact(root: str | os.PathLike[str], candidates: tuple[str, ...]) -> tuple[Path, dict[str, Any]] | None:
    base = Path(root)
    for rel in candidates:
        path = base / rel
        if not path.exists():
            continue
        data = _safe_json(path)
        if data is not None:
            return path, data
    return None


def load_project_map(root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]] | None:
    return load_artifact(root, PROJECT_MAP_CANDIDATES)


def load_precedent_index(root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]] | None:
    return load_artifact(root, PRECEDENT_INDEX_CANDIDATES)


def artifact_status(root: str | os.PathLike[str]) -> dict[str, Any]:
    base = Path(root).resolve()
    project_map_loaded = load_project_map(base)
    precedent_loaded = load_precedent_index(base)

    payload: dict[str, Any] = {
        "root": str(base),
        "project_map": {"present": False, "path": None, "schema": None},
        "precedent_index": {"present": False, "path": None, "schema": None},
    }

    if project_map_loaded is not None:
        map_path, project_map = project_map_loaded
        payload["project_map"] = {
            "present": True,
            "path": str(map_path),
            "schema": project_map.get("schema"),
            "generated_at": project_map.get("generated_at"),
            "entry_points": _as_list(project_map.get("entry_points")),
            "test_files": _as_list(project_map.get("test_files")),
            "config_files": _as_list(project_map.get("config_files")),
            "recent_changes": [
                item
                for item in _as_list(project_map.get("recent_changes"))
                if isinstance(item, dict)
            ],
            "module_names": [
                str(module.get("name"))
                for module in _as_list(project_map.get("modules"))
                if isinstance(module, dict) and module.get("name")
            ],
        }

    if precedent_loaded is not None:
        precedent_path, precedent_index = precedent_loaded
        raw_items = precedent_index.get("items", precedent_index.get("precedents", []))
        payload["precedent_index"] = {
            "present": True,
            "path": str(precedent_path),
            "schema": precedent_index.get("schema"),
            "items": len([item for item in _as_list(raw_items) if isinstance(item, dict)]),
        }

    return payload


def inspect_target(
    root: str | os.PathLike[str],
    target: str,
    *,
    goal: str = "",
    limit: int = 8,
    precedent_limit: int = 3,
) -> dict[str, Any]:
    base = Path(root).resolve()
    artifacts = artifact_status(base)
    payload: dict[str, Any] = {
        "root": str(base),
        "target": target,
        "goal": goal,
        "artifacts": artifacts,
        "relevant_files": [],
        "precedents": rank_precedents(base, f"{goal} {target}", k=precedent_limit),
        "context": build_mapper_context(base, target, goal=goal),
    }

    loaded_map = load_project_map(base)
    if loaded_map is None:
        return payload

    _map_path, project_map = loaded_map
    entries = _file_entries(project_map)
    payload["relevant_files"] = rank_entries(entries, target=target, query=goal, limit=limit)
    return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _file_entries(project_map: dict[str, Any]) -> list[dict[str, Any]]:
    files = project_map.get("files", [])
    if isinstance(files, dict):
        entries = []
        for path, meta in files.items():
            item = dict(meta or {}) if isinstance(meta, dict) else {}
            item.setdefault("path", path)
            entries.append(item)
        return entries
    return [f for f in files if isinstance(f, dict)]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_./-]+", text.lower()) if len(t) > 2}


def _entry_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("path", "language", "summary", "change_type"):
        value = entry.get(key)
        if value:
            parts.append(str(value))
    for key in ("roles", "tags", "imports", "exports"):
        parts.extend(str(v) for v in _as_list(entry.get(key)))
    return " ".join(parts)


def rank_entries(entries: list[dict[str, Any]], *, target: str = "", query: str = "", limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = _tokens(f"{target} {query}")
    ranked: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        path = str(entry.get("path", ""))
        score = float(entry.get("importance", entry.get("score", 0)) or 0)
        if target and path == target:
            score += 5
        if target and (path.endswith(target) or target.endswith(path)):
            score += 2
        overlap = query_tokens & _tokens(_entry_text(entry))
        score += len(overlap) * 0.5
        if any(role in _as_list(entry.get("roles")) for role in ("entrypoint", "test", "config")):
            score += 0.25
        if score > 0:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("path", ""))))
    return [entry for _score, entry in ranked[:limit]]


def rank_precedents(root: str | os.PathLike[str], task: str, *, stack: str = "", k: int = 2) -> list[dict[str, Any]]:
    loaded = load_precedent_index(root)
    if loaded is None:
        return []
    _path, index = loaded
    raw_items = index.get("items", index.get("precedents", []))
    items = [item for item in raw_items if isinstance(item, dict)]
    ranked = rank_entries(items, target=stack, query=task, limit=k)
    return ranked[:k]


def _read_target_fallback(root: Path, target: str) -> str:
    try:
        text = (root / target).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return "(mapper: target not read)"
    deps = [
        line
        for line in text.splitlines()
        if line.strip().startswith(("import", "using", "from", "require(", "const "))
    ][:15]
    return "File: {target}\nDependencies:\n{deps}".format(
        target=target,
        deps="\n".join(deps) if deps else "(none detected)",
    )


def build_mapper_context(root: str | os.PathLike[str], target: str, *, goal: str = "") -> str:
    base = Path(root)
    loaded_map = load_project_map(base)
    if loaded_map is None:
        return _read_target_fallback(base, target)

    map_path, project_map = loaded_map
    entries = _file_entries(project_map)
    relevant = rank_entries(entries, target=target, query=goal, limit=8)
    precedents = rank_precedents(base, f"{goal} {target}", k=3)

    lines = [
        f"Mapper artifact: {map_path.relative_to(base)}",
        f"Schema: {project_map.get('schema', 'unknown')}",
    ]
    generated_at = project_map.get("generated_at")
    if generated_at:
        lines.append(f"Generated: {generated_at}")

    arch = project_map.get("architecture", {})
    signals = arch.get("signals") if isinstance(arch, dict) else None
    if signals:
        lines.append("Architecture signals: " + ", ".join(str(s) for s in _as_list(signals)[:10]))

    for key, label in (("entry_points", "Entry points"), ("test_files", "Tests"), ("config_files", "Config")):
        values = _as_list(project_map.get(key))[:8]
        if values:
            lines.append(f"{label}: " + ", ".join(str(v) for v in values))

    modules = _as_list(project_map.get("modules"))[:5]
    if modules:
        lines.append("Modules:")
        for module in modules:
            if isinstance(module, dict):
                name = module.get("name", "(unnamed)")
                files = ", ".join(str(f) for f in _as_list(module.get("files"))[:5])
                lines.append(f"- {name}: {files}".rstrip(": "))

    if relevant:
        lines.append("Relevant files:")
        for entry in relevant:
            path = entry.get("path", "(unknown)")
            roles = ",".join(str(r) for r in _as_list(entry.get("roles")))
            imports = ",".join(str(i) for i in _as_list(entry.get("imports"))[:6])
            bits = [f"path={path}"]
            if entry.get("language"):
                bits.append(f"lang={entry['language']}")
            if roles:
                bits.append(f"roles={roles}")
            if imports:
                bits.append(f"imports={imports}")
            lines.append("- " + " | ".join(bits))

    recent = _as_list(project_map.get("recent_changes"))[:6]
    if recent:
        lines.append("Recent changes:")
        for item in recent:
            if isinstance(item, dict):
                lines.append(f"- {item.get('path', '?')} ({item.get('status', 'changed')})")

    if precedents:
        lines.append("Precedent candidates:")
        for item in precedents:
            loc = f"{item.get('path', '(unknown)')}:{item.get('line', 1)}"
            summary = item.get("summary") or item.get("change_type") or "similar code"
            lines.append(f"- {loc} — {summary}")

    fallback = _read_target_fallback(base, target)
    return "\n".join(lines + ["", "Target fallback:", fallback])
