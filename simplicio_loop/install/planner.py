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
from typing import Any, Mapping

from .. import __version__

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


def _bundle_root() -> Path:
    return Path(__file__).resolve().parents[1] / "_bundle"


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
    bundle: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(plan["target"])
    owned: list[str] = []
    written = 0
    source = Path(bundle) if bundle else _bundle_root()
    skills_src = source / "skills"
    hooks_src = source / "hooks"
    if not skills_src.is_dir():
        raise InstallError("bundled skills not found in the installed package.")
    for action in plan.get("actions") or []:
        dest = root / action["destination"]
        kind = action["kind"]
        src = skills_src if kind == "skills" else hooks_src if kind == "hooks" else None
        if src is None:
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    dest.write_text(
                        f"# simplicio-loop {plan['version']} ({action['host']})\n"
                        "Load `.claude/skills/simplicio-loop/SKILL.md`.\n",
                        encoding="utf-8",
                    )
                    written += 1
            owned.append(action["destination"])
            continue
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
            for item in src.rglob("*"):
                if item.is_file():
                    out = dest / item.relative_to(src)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, out)
                    written += 1
        owned.append(action["destination"])
    ownership = {
        "schema": OWNERSHIP_SCHEMA,
        "owner": "simplicio-loop",
        "version": plan["version"],
        "digest": plan["digest"],
        "paths": owned,
    }
    marker = root / ".simplicio-loop" / "install-ownership.json"
    if not dry_run:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(ownership, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "schema": SCHEMA,
        "status": "dry_run" if dry_run else "applied",
        "written": 0 if dry_run else written,
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
