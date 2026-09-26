"""Plugin v1 permission-aware capability projection (#579).

Mapper observes the project and emits ``ProjectCapabilityProjection/v1``.
It does not choose a route, effect, skill, or conclusion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.plugin.project-capability-projection/v1"
GENERATOR = "plugin-orientation/1"
PRECEDENCE = ("user", "repo", "subdir")
_CACHE: dict[str, dict[str, Any]] = {}

_KIND_FILES = (
    ("skill", ".skills"),
    ("agent", ".agents"),
    ("command", ".claude/commands"),
    ("mcp", ".mcp.json"),
    ("config", "AGENTS.md"),
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _file_sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _permission_decision(name: str, permissions: Mapping[str, Any] | None) -> tuple[str, str]:
    if not permissions:
        return "unknown", "permissions_absent"
    allow = {str(item) for item in permissions.get("allow", [])}
    deny = {str(item) for item in permissions.get("deny", [])}
    if name in deny:
        return "deny", "explicit_deny"
    if name in allow:
        return "allow", "explicit_allow"
    if allow or deny:
        return "unknown", "not_listed"
    return "unknown", "permissions_empty"


def _capability_name(path: Path) -> str:
    if path.stem.lower() in {"skill", "agents", "readme", "command"}:
        return path.parent.name
    return path.stem or path.name


def _scope_for(root: Path, path: Path) -> str:
    try:
        first = path.relative_to(root).parts[0]
    except ValueError:
        return "repo"
    if first.startswith(".") or first in {"AGENTS.md", ".mcp.json"}:
        return "repo"
    return "subdir"


def _iter_named_files(root: Path, relative: str, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if relative in {"AGENTS.md", ".mcp.json"}:
        target = root / relative
        if target.is_file():
            rows.append(_descriptor(root, target, kind, target.stem or target.name, "repo"))
        return rows
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        marker = relative.strip("/")
        if f"/{marker}/" not in f"/{rel}" and not rel.startswith(marker + "/"):
            continue
        rows.append(_descriptor(root, path, kind, _capability_name(path), _scope_for(root, path)))
    return rows


def _descriptor(root: Path, path: Path, kind: str, name: str, scope: str) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    text = _read_text(path)
    return {
        "kind": kind,
        "name": name,
        "scope": scope,
        "path": rel,
        "line": 1,
        "sha256": _file_sha(path),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "injection_ignored": "ignore previous" in text.lower() or "system prompt" in text.lower(),
    }


def _discover(root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for kind, relative in _KIND_FILES:
        found.extend(_iter_named_files(root, relative, kind))
    user_home = Path.home() / ".simplicio-loop" / "capabilities.json"
    if user_home.is_file():
        payload = json.loads(_read_text(user_home) or "{}")
        for item in payload.get("capabilities", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            found.append(
                {
                    "kind": str(item.get("kind") or "skill"),
                    "name": str(item["name"]),
                    "scope": "user",
                    "path": user_home.as_posix(),
                    "line": 1,
                    "sha256": _file_sha(user_home),
                    "text_sha256": hashlib.sha256(_canonical(item)).hexdigest(),
                    "injection_ignored": False,
                }
            )
    return found


def _apply_precedence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {scope: index for index, scope in enumerate(PRECEDENCE)}
    winners: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        key = (row["kind"], row["name"])
        existing = winners.get(key)
        if existing is None:
            winners[key] = row
            continue
        if rank[row["scope"]] < rank[existing["scope"]]:
            conflicts.append({"name": row["name"], "kept": row["scope"], "dropped": existing["scope"]})
            winners[key] = row
        else:
            conflicts.append({"name": row["name"], "kept": existing["scope"], "dropped": row["scope"]})
    ordered = sorted(winners.values(), key=lambda item: (item["kind"], item["name"]))
    for row in ordered:
        row["conflicts"] = [item for item in conflicts if item["name"] == row["name"]]
    return ordered


def cache_key(
    *,
    repo: str,
    ref: str,
    permissions: Mapping[str, Any] | None,
    producers: Mapping[str, Any] | None,
    host: str,
) -> str:
    return _digest(
        {
            "repo": repo,
            "ref": ref,
            "permissions": permissions or {},
            "producers": producers or {},
            "host": host,
            "generator": GENERATOR,
        }
    )


def project_capabilities_for_plugin(
    root: str | Path,
    *,
    ref: str = "",
    host: str = "",
    task_intent: Mapping[str, Any] | None = None,
    permissions: Mapping[str, Any] | None = None,
    producers: Mapping[str, Any] | None = None,
    dirty: bool = False,
    proven_ref: bool = True,
    token_budget: int = 2048,
) -> dict[str, Any]:
    """Build a bounded, permission-aware projection. Never selects a route."""

    root_path = Path(root)
    repo = str(root_path)
    key = cache_key(repo=repo, ref=ref, permissions=permissions, producers=producers, host=host)
    cached = _CACHE.get(key)
    if cached is not None and not dirty:
        hit = dict(cached)
        hit["cache"] = {"hit": True, "key": key}
        return hit
    if not proven_ref or not root_path.is_dir():
        payload = {
            "schema": SCHEMA,
            "status": "abstained",
            "reason": "unproven_ref" if not proven_ref else "missing_root",
            "host": host,
            "ref": ref,
            "dirty": dirty,
            "capabilities": [],
            "digest": _digest({"status": "abstained", "ref": ref}),
            "cache": {"hit": False, "key": key},
            "route": None,
            "effect": None,
        }
        return payload
    winners = _apply_precedence(_discover(root_path))
    capabilities: list[dict[str, Any]] = []
    for row in winners:
        decision, reason = _permission_decision(row["name"], permissions)
        item = {
            "kind": row["kind"],
            "name": row["name"],
            "scope": row["scope"],
            "applicability": "project",
            "permission": decision,
            "permission_reason": reason,
            "provenance": {
                "path": row["path"],
                "line": row["line"],
                "sha256": row["sha256"],
                "ref": ref,
            },
            "confidence": 0.9 if decision == "allow" else 0.4 if decision == "unknown" else 0.1,
            "evidence": ["source_file", reason],
            "conflicts": row.get("conflicts") or [],
            "injection_ignored": row["injection_ignored"],
        }
        if task_intent and task_intent.get("goal"):
            goal = str(task_intent["goal"]).lower()
            item["task_overlap"] = row["name"].lower() in goal
        capabilities.append(item)
    visible = [item for item in capabilities if item["permission"] != "deny"]
    denied = [item for item in capabilities if item["permission"] == "deny"]
    summary = {
        "visible": len(visible),
        "denied": len(denied),
        "unknown": sum(1 for item in capabilities if item["permission"] == "unknown"),
    }
    payload = {
        "schema": SCHEMA,
        "status": "ready",
        "host": host,
        "ref": ref,
        "dirty": dirty,
        "task_fingerprint": str((task_intent or {}).get("fingerprint") or ""),
        "producers": dict(producers or {}),
        "capabilities": visible,
        "denied": [
            {"name": item["name"], "permission_reason": item["permission_reason"], "provenance": item["provenance"]}
            for item in denied
        ],
        "summary": summary,
        "handles": {"details": f"projection:{key[:16]}"},
        "digest": _digest({"capabilities": visible, "denied": denied, "ref": ref}),
        "cache": {"hit": False, "key": key},
        "token_budget": token_budget,
        "route": None,
        "effect": None,
    }
    _CACHE[key] = {k: v for k, v in payload.items() if k != "cache"}
    return payload


def invalidate_projection_cache(key: str | None = None) -> None:
    if key is None:
        _CACHE.clear()
        return
    _CACHE.pop(key, None)
