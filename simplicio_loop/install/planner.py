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
OWNERSHIP_SCHEMA = "simplicio.loop-install-ownership/v2"
RECEIPT = Path(".simplicio-loop") / "install-ownership.json"
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


def _put(path: Path, data: bytes, source, changes: dict, root: Path, dry_run: bool, made: set) -> None:
    """Classify one file (created, updated or unchanged) and write it only when it differs. `made` collects the
    directories this write creates, so uninstall can remove exactly those again."""
    rel = path.relative_to(root).as_posix()
    if path.is_file() and path.read_bytes() == data:
        changes["unchanged"] += 1
        return
    changes["updated" if path.is_file() else "created"].append(rel)
    if dry_run:
        return
    parent = path.parent
    while parent != root and not parent.exists():
        made.add(parent.relative_to(root).as_posix())
        parent = parent.parent
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


def _previous_receipt(root: Path) -> dict[str, list[str]]:
    """What an earlier install registered, so a second host installed later does not drop the first one's files.
    A receipt of another schema is not read: install rewrites it, and its paths are not trusted."""
    empty = {"paths": [], "dirs": []}
    marker = root / RECEIPT
    if not marker.is_file():
        return empty
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if payload.get("owner") != "simplicio-loop" or payload.get("schema") != OWNERSHIP_SCHEMA:
        return empty
    return {"paths": list(payload.get("paths") or []), "dirs": list(payload.get("dirs") or [])}


def apply_plan(
    plan: Mapping[str, Any],
    *,
    dry_run: bool = False,
    bundle: Any = None,  # a path, or any importlib.resources Traversable; None = the bundle of this package
) -> dict[str, Any]:
    """Copy the bundled skills and hooks into the plan's target. Idempotent: a file that is already identical is not
    rewritten. `changes` says what was created, what was updated, how many were unchanged and what was left alone
    (files in the target that Loop does not own, and entry files that already exist).

    The ownership receipt registers exactly the files Loop wrote or found identical, the entry files it created, and
    the directories it created. uninstall removes only those.
    """
    root = Path(plan["target"])
    owned: list[str] = []
    made: set[str] = set()
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
        if src is None:  # an entry file (AGENTS.md ...): written once, never overwritten
            if dest.exists():
                changes["left_alone"].append(dest.relative_to(root).as_posix())
            else:
                body = (f"# simplicio-loop {plan['version']} ({action['host']})\n"
                        "Load `.claude/skills/simplicio-loop/SKILL.md`.\n")
                _put(dest, body.encode("utf-8"), None, changes, root, dry_run, made)
                owned.append(dest.relative_to(root).as_posix())
            continue
        top = set()
        for parts, node in _files(src):
            top.add(parts[0])
            file_path = dest.joinpath(*parts)
            _put(file_path, node.read_bytes(), node, changes, root, dry_run, made)
            owned.append(file_path.relative_to(root).as_posix())
        if dest.is_dir():
            changes["left_alone"] += [child.relative_to(root).as_posix() for child in sorted(dest.iterdir())
                                      if child.name not in top and child.name != "__pycache__"]
    if not (root / RECEIPT.parent).exists():  # the receipt's own directory is one more thing install creates
        made.add(RECEIPT.parent.as_posix())
    previous = _previous_receipt(root)
    ownership = {
        "schema": OWNERSHIP_SCHEMA,
        "owner": "simplicio-loop",
        "version": plan["version"],
        "digest": plan["digest"],
        "paths": sorted(set(owned) | set(previous["paths"])),
        "dirs": sorted(made | set(previous["dirs"])),
    }
    body = (json.dumps(ownership, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _put(root / RECEIPT, body, None, changes, root, dry_run, made)
    pending = len(changes["created"]) + len(changes["updated"])
    return {
        "schema": SCHEMA,
        "status": "dry_run" if dry_run else "applied",
        "written": 0 if dry_run else pending,
        "up_to_date": pending == 0,
        "changes": changes,
        "owned": sorted(owned),
        "ownership": ownership,
        "digest": plan["digest"],
    }


def _receipt_path(root: Path, rel: str) -> Path:
    """A receipt path is relative and stays under the target; anything else is a receipt that cannot be trusted."""
    parts = Path(rel).parts
    if not rel or Path(rel).is_absolute() or ".." in parts:
        raise InstallError(f"ownership receipt path escapes the target: {rel}")
    return root.joinpath(*parts)


def _read_receipt(root: Path) -> dict[str, Any]:
    marker = root / RECEIPT
    if not marker.is_file():
        raise InstallError("no Loop ownership receipt; refusing to uninstall unmanaged files")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"ownership receipt is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("owner") != "simplicio-loop":
        raise InstallError("ownership receipt is not Loop-owned")
    if payload.get("schema") != OWNERSHIP_SCHEMA:
        raise InstallError(f"ownership receipt uses an obsolete schema ({payload.get('schema')}); run "
                           "`simplicio-loop install` once to rewrite it, then uninstall")
    return payload


def uninstall(target: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove the files the receipt registers, then the registered directories that are empty by then. A directory
    that holds anything Loop did not register (a user's skill, rule or hook) is kept, and so is every directory that
    install did not create. `dry_run` returns the same lists and touches nothing; then `removed` is what would go.
    """
    root = Path(target).resolve()
    receipt = _read_receipt(root)
    files = sorted({RECEIPT.as_posix(), *(receipt.get("paths") or [])})
    gone: set[str] = set()
    removed: list[str] = []
    skipped: list[str] = []
    for rel in files:
        path = _receipt_path(root, rel)
        if path.is_file():
            removed.append(rel)
            gone.add(rel)
        elif path.exists():  # a directory where a file was registered: not Loop's to delete
            skipped.append(rel)
    removed_dirs: list[str] = []
    kept: list[str] = []
    for rel in sorted(set(receipt.get("dirs") or []), key=lambda item: item.count("/"), reverse=True):
        path = _receipt_path(root, rel)
        if not path.is_dir():
            continue
        if all(child.relative_to(root).as_posix() in gone for child in path.iterdir()):
            removed_dirs.append(rel)
            gone.add(rel)
        else:
            kept.append(rel)
    if not dry_run:
        for rel in removed:
            _receipt_path(root, rel).unlink()
        for rel in removed_dirs:
            _receipt_path(root, rel).rmdir()
    return {
        "schema": OWNERSHIP_SCHEMA,
        "status": "dry_run" if dry_run else "removed",
        "removed": removed,
        "removed_dirs": removed_dirs,
        "kept": kept,
        "skipped": skipped,
    }


def verify_plan(plan: Mapping[str, Any], expected_version: str = __version__) -> dict[str, Any]:
    if plan.get("version") != expected_version:
        raise InstallError(
            f"descriptor version mismatch: plan={plan.get('version')} wheel={expected_version}"
        )
    return {"ok": True, "version": expected_version, "digest": plan.get("digest")}
