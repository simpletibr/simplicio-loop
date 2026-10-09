"""Single host-aware install planner for the simplicio-loop wheel.

`scripts/install_lib.py` remains the repo checkout entry. This module is what
the packaged `simplicio-loop install` command uses so the wheel is not a
Claude-only generic copy.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterator, Mapping

from .. import __version__, distribution

SCHEMA = "simplicio.loop-install-plan/v1"
OWNERSHIP_SCHEMA = "simplicio.loop-install-ownership/v1"
HOSTS = (
    "claude", "codex", "cursor", "vscode", "grok", "kiro",
    "antigravity", "opencode", "gemini", "aider", "simplicio_agent", "openclaw",
)
HOST_LAYOUT = {
    "claude": {".claude/skills": "skills", "hooks": "hooks"},
    "cursor": {".claude/skills": "skills", "hooks": "hooks"},
    "codex": {".claude/skills": "skills", "AGENTS.md": "entry"},
    "vscode": {".claude/skills": "skills", ".github/copilot-instructions.md": "entry"},
    "grok": {".claude/skills": "skills", "AGENTS.md": "entry"},
    "kiro": {".claude/skills": "skills", ".kiro/steering/simplicio-loop.md": "entry"},
}


class InstallError(RuntimeError):
    """Host unknown, version drift, or unsafe uninstall."""


def _digest(value: Any) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _bundle_root():
    return distribution.bundle_root()  # importlib.resources: the same call works from a wheel, a checkout and a binary


def _files(node, prefix: tuple = ()) -> Iterator[tuple]:
    """(path parts, Traversable) of every file under `node`, sorted; compiled caches are never shipped."""
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        if child.name == "__pycache__" or child.name.endswith(".pyc"):
            continue
        if child.is_dir():
            yield from _files(child, prefix + (child.name,))
        else:
            yield prefix + (child.name,), child


def _put(path: Path, data: bytes, source, changes: dict, root: Path, dry_run: bool) -> None:
    """Classify one file (created, updated or unchanged) and write it only when it differs."""
    rel = path.relative_to(root).as_posix()
    if path.is_file() and path.read_bytes() == data:
        changes["unchanged"] += 1
        return
    changes["updated" if path.is_file() else "created"].append(rel)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if isinstance(source, Path):  # keep the executable bit of a hook
        shutil.copymode(source, path)


def plan_install(
    target: str | Path,
    *,
    host: str = "claude",
    globally: bool = False,
    version: str = __version__,
) -> dict[str, Any]:
    if host not in HOSTS and host != "all":
        raise InstallError(f"unknown host: {host}")
    hosts = list(HOSTS) if host == "all" else [host]
    root = Path(target).resolve()
    actions = []
    for item in hosts:
        layout = HOST_LAYOUT.get(item, {".claude/skills": "skills"})
        if globally:
            layout = {".claude/skills": "skills", ".claude/hooks": "hooks"}
        for dest, kind in layout.items():
            actions.append({
                "host": item,
                "kind": kind,
                "destination": dest,
                "owner": "simplicio-loop",
            })
    plan = {
        "schema": SCHEMA,
        "version": version,
        "target": str(root),
        "scope": "global" if globally else "project",
        "hosts": hosts,
        "actions": actions,
        "entrypoint": "simplicio-loop=simplicio_loop.cli:main",
    }
    plan["digest"] = _digest({key: plan[key] for key in ("schema", "version", "hosts", "actions", "scope")})
    return plan


def apply_plan(
    plan: Mapping[str, Any],
    *,
    dry_run: bool = False,
    bundle: Any = None,  # a path, or any importlib.resources Traversable; None = the bundle of this package
) -> dict[str, Any]:
    """Copy the bundled skills and hooks into the plan's target. Idempotent: a file that is already identical is not
    rewritten. `changes` says what was created, what was updated, how many were unchanged and what was left alone
    (files in the target that Loop does not own, and entry files that already exist).
    """
    root = Path(plan["target"])
    owned: list[str] = []
    changes: dict[str, Any] = {"created": [], "updated": [], "unchanged": 0, "left_alone": []}
    source = Path(bundle) if isinstance(bundle, str) else bundle if bundle is not None else _bundle_root()
    skills_src = source.joinpath("skills")
    hooks_src = source.joinpath("hooks")
    if not skills_src.is_dir():
        raise InstallError("bundled skills not found in the installed package.")
    for action in plan.get("actions") or []:
        dest = root / action["destination"]
        kind = action["kind"]
        src = skills_src if kind == "skills" else hooks_src if kind == "hooks" else None
        owned.append(action["destination"])
        if src is None:  # an entry file (AGENTS.md ...): written once, never overwritten
            if dest.exists():
                changes["left_alone"].append(dest.relative_to(root).as_posix())
            else:
                body = (f"# simplicio-loop {plan['version']} ({action['host']})\n"
                        "Load `.claude/skills/simplicio-loop/SKILL.md`.\n")
                _put(dest, body.encode("utf-8"), None, changes, root, dry_run)
            continue
        top = set()
        for parts, node in _files(src):
            top.add(parts[0])
            _put(dest.joinpath(*parts), node.read_bytes(), node, changes, root, dry_run)
        if dest.is_dir():
            changes["left_alone"] += [child.relative_to(root).as_posix() for child in sorted(dest.iterdir())
                                      if child.name not in top and child.name != "__pycache__"]
    ownership = {
        "schema": OWNERSHIP_SCHEMA,
        "owner": "simplicio-loop",
        "version": plan["version"],
        "digest": plan["digest"],
        "paths": owned,
    }
    marker = root / ".simplicio-loop" / "install-ownership.json"
    body = (json.dumps(ownership, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _put(marker, body, None, changes, root, dry_run)
    pending = len(changes["created"]) + len(changes["updated"])
    return {
        "schema": SCHEMA,
        "status": "dry_run" if dry_run else "applied",
        "written": 0 if dry_run else pending,
        "up_to_date": pending == 0,
        "changes": changes,
        "owned": owned,
        "ownership": ownership,
        "digest": plan["digest"],
    }


def uninstall(target: str | Path) -> dict[str, Any]:
    root = Path(target).resolve()
    marker = root / ".simplicio-loop" / "install-ownership.json"
    if not marker.is_file():
        raise InstallError("no Loop ownership receipt; refusing to uninstall unmanaged files")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if payload.get("owner") != "simplicio-loop":
        raise InstallError("ownership receipt is not Loop-owned")
    removed = []
    for rel in payload.get("paths") or []:
        path = root / rel
        if path.is_file():
            path.unlink()
            removed.append(rel)
        elif path.is_dir() and (rel.endswith("skills") or rel == "hooks"):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(rel)
    marker.unlink()
    return {"schema": OWNERSHIP_SCHEMA, "status": "removed", "removed": removed}


def verify_plan(plan: Mapping[str, Any], expected_version: str = __version__) -> dict[str, Any]:
    if plan.get("version") != expected_version:
        raise InstallError(
            f"descriptor version mismatch: plan={plan.get('version')} wheel={expected_version}"
        )
    return {"ok": True, "version": expected_version, "digest": plan.get("digest")}
