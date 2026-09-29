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


# The listing of every installed skill is shown to the model on every turn, so by default only the one skill that runs a task
# is installed; the others (orient, review, compress, learn, autoresearch, prism, mapper, dev-cli, the tasks alias) are opt-in.
CORE_SKILLS = ("simplicio-loop",)


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
    all_skills: bool = False,
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
            action = {
                "host": item,
                "kind": kind,
                "destination": dest,
                "owner": "simplicio-loop",
            }
            if kind == "skills":
                action["skills"] = "all" if all_skills else list(CORE_SKILLS)
            actions.append(action)
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


def _previous_receipt(root: Path) -> dict[str, Any] | None:
    marker = root / ".simplicio-loop" / "install-ownership.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and payload.get("owner") == "simplicio-loop" else None


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def apply_plan(
    plan: Mapping[str, Any],
    *,
    dry_run: bool = False,
    bundle: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(plan["target"])
    owned: list[str] = []
    removed: list[str] = []
    written = 0
    source = Path(bundle) if bundle else _bundle_root()
    skills_src = source / "skills"
    hooks_src = source / "hooks"
    if not skills_src.is_dir():
        raise InstallError("bundled skills not found in the installed package.")
    previous = _previous_receipt(root)
    for action in plan.get("actions") or []:
        dest = root / action["destination"]
        kind = action["kind"]
        if kind == "skills":
            selection = action.get("skills", "all")
            entries = sorted(item.name for item in skills_src.iterdir()) if selection == "all" else list(selection)
            missing = [name for name in entries if not (skills_src / name).exists()]
            if missing:
                raise InstallError(f"bundled skill not found: {', '.join(missing)}")
            if previous and not dry_run:  # an earlier install of this package wrote skills that were not asked for this time
                before = {Path(rel).name for rel in previous.get("paths") or [] if Path(rel).parent.as_posix() == action["destination"]}
                if action["destination"] in (previous.get("paths") or []):  # the older receipt owned the whole folder
                    before |= {item.name for item in skills_src.iterdir()}
                for name in sorted(before - set(entries)):
                    if (dest / name).exists():
                        _remove(dest / name)
                        removed.append(f"{action['destination']}/{name}")
            if not dry_run:
                for name in entries:
                    item = skills_src / name
                    if item.is_dir():
                        for file in item.rglob("*"):
                            if file.is_file():
                                out = dest / name / file.relative_to(item)
                                out.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(file, out)
                                written += 1
                    else:
                        dest.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest / name)
                        written += 1
            owned.extend(f"{action['destination']}/{name}" for name in entries)
            continue
        src = hooks_src if kind == "hooks" else None
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
        "removed": removed,
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
        elif path.is_dir() and (rel.endswith("skills") or rel == "hooks" or "skills/" in rel):
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
