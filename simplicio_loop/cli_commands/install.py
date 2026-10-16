"""`install` and `update`: install the bundled skills and hooks, and self-update.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import json
import shutil

from ._base import impl

from .. import __version__
from .. import setup_cli

def _copy_tree(src: Path, dst: Path) -> int:
    """Copy every file under src into dst, preserving structure. Returns file count."""
    count = 0
    for item in src.rglob("*"):
        if item.is_file():
            out = dst / item.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out)
            count += 1
    return count


def _resync_hosts(root: Path, apply: bool) -> dict:
    """Skills and host rules of every host that ALREADY has them (#1480): refresh them, or only list what is stale."""
    from ..host_rules import resync_installed_rules, stale_rules
    from ..host_rules import resync_installed_rules, stale_rules
    from ..skill_sync import resync_installed_skills, stale_skills
    stale_s, stale_r = stale_skills(root), stale_rules(root)
    skills_counts: dict[str, int] = {}
    for entry in stale_s:
        skills_counts[entry["host"]] = skills_counts.get(entry["host"], 0) + 1
    rules_counts: dict[str, int] = {}
    for entry in stale_r:
        rules_counts[entry["surface"]] = rules_counts.get(entry["surface"], 0) + 1

    if apply:  # skills first: the rule sync rewrites the rule ref inside the installed loop skill
        skills, rules = resync_installed_skills(root), resync_installed_rules(root)
        return {"skills": skills["synced"], "rules": rules["synced"],
                "skills_counts": skills_counts, "rules_counts": rules_counts,
                "errors": skills["errors"] + rules["errors"],
                "pending": 0}
    return {"skills": sorted({entry["host"] for entry in stale_s}),
            "rules": [entry["surface"] for entry in stale_r],
            "skills_counts": skills_counts, "rules_counts": rules_counts,
            "errors": [], "pending": len(stale_s) + len(stale_r)}


def _install_lines(result: dict, host: str, head: str, resync: Optional[dict],
                   prune_project: Optional[dict] = None) -> list:
    changes = result["changes"]
    owned_files = sorted(set(result.get("owned") or []))
    lines = [f"simplicio-loop {__version__} {head}:", f"  host   -> {host}", f"  owned  -> {len(owned_files)} files",
             f"  changed -> {len(changes['created'])} created, {len(changes['updated'])} updated, "
             f"{changes['unchanged']} unchanged"]
    for label in ("created", "updated"):
        lines += [f"    {label}: {path}" for path in changes[label][:8]]
        if len(changes[label]) > 8:
            lines.append(f"    {label}: ... and {len(changes[label]) - 8} more")
    if changes["left_alone"]:
        left = changes["left_alone"]
        total = len(left)
        prefix = f"  left alone -> {total} not owned by Loop: "
        shown_items: list[str] = []
        cur_len = len(prefix)
        for i, item in enumerate(left):
            sep = ", " if shown_items else ""
            added = len(sep) + len(item)
            if i >= 5 or (shown_items and cur_len + added + 12 > 80):
                break
            shown_items.append(item)
            cur_len += added
        shown = ", ".join(shown_items)
        more = total - len(shown_items)
        lines.append(prefix + shown + (f" (+{more} more)" if more > 0 else ""))
    if resync is not None and (resync["skills"] or resync["rules"] or resync["errors"]):
        is_stale = head.startswith(("check", "dry_run"))
        verb = ("stale (installed host copies differing from package, pending update)"
                if is_stale else
                "resynced (installed host copies refreshed to match package)")
        skills_counts = resync.get("skills_counts") or {}
        rules_counts = resync.get("rules_counts") or {}
        if skills_counts:
            skills_str = ", ".join(f"{h} ({skills_counts[h]})" for h in sorted(skills_counts))
        else:
            skills_str = ", ".join(resync["skills"]) or "-"
        if rules_counts:
            rules_str = ", ".join(f"{r} ({rules_counts[r]})" for r in sorted(rules_counts))
        else:
            rules_str = ", ".join(resync["rules"]) or "-"
        lines.append(f"  {verb} -> skills: {skills_str}; rules: {rules_str}")
        lines += [f"  resync error: {err['host']}: {err['error']}" for err in resync["errors"]]
    if prune_project is not None:
        verb = "would prune" if head.startswith(("check", "dry_run")) else "pruned"
        removed_list = prune_project.get("removed") or []
        n_pruned = len(removed_list)
        if n_pruned > 0:
            prefix = f"  {verb} project copies -> {n_pruned} stale files: "
            shown_items = []
            cur_len = len(prefix)
            for i, item in enumerate(removed_list):
                sep = ", " if shown_items else ""
                added = len(sep) + len(item)
                if i >= 5 or (shown_items and cur_len + added + 12 > 80):
                    break
                shown_items.append(item)
                cur_len += added
            more = n_pruned - len(shown_items)
            lines.append(prefix + ", ".join(shown_items) + (f" (+{more} more)" if more > 0 else ""))
        else:
            lines.append("  project copies -> 0 stale files found")
    return lines


def install(target: Path, globally: bool, host: str = "claude",
            dry_run: bool = False, uninstall: bool = False, verify: bool = False,
            check: bool = False, as_json: bool = False,
            prune_project_copies: bool = False) -> int:
    from ..install.planner import InstallError, apply_plan, plan_install
    from ..install.planner import prune_project_copies as prune_fn
    from ..install.planner import uninstall as remove_owned
    from ..install.planner import verify_plan

    root = Path.home() if globally else target
    if uninstall:
        try:
            payload = remove_owned(root, dry_run=dry_run)
        except InstallError as exc:
            print(f"error: {exc}", flush=True)
            return 1
        verb = "would remove" if dry_run else "removed"
        print(f"simplicio-loop uninstall {'dry_run (nothing removed)' if dry_run else 'applied'}: "
              f"{verb} {len(payload['removed'])} files, {len(payload['removed_dirs'])} empty directories")
        print("\n".join(f"  {verb}: {rel}" for rel in payload["removed"] + [f"{rel}/" for rel in payload["removed_dirs"]]))
        if payload["kept"]:
            print(f"  kept (not empty, holds files Loop did not install): {', '.join(payload['kept'])}")
        if globally:
            print("  not removed (outside the ownership receipt): the simplicio-* skills and Loop rule files that "
                  "install --global refreshes in other hosts; remove them by hand")
        return 0
    try:
        plan = plan_install(root, host=host, globally=globally)
        if verify:
            verify_plan(plan)
            print(f"simplicio-loop install plan ok host={host} digest={plan['digest']}")
            return 0
        result = apply_plan(plan, dry_run=dry_run or check, bundle=impl().BUNDLE)
    except InstallError as exc:
        print(f"error: {exc}", flush=True)
        return 1
    resync = _resync_hosts(root, apply=not (dry_run or check)) if globally else None
    prune_result = prune_fn(target, dry_run=dry_run or check) if (globally and prune_project_copies) else None
    pending = not result["up_to_date"] or bool(resync and resync["pending"])
    if as_json:
        payload = {**result, "host": host, "version": __version__, "resynced": resync}
        if prune_result is not None:
            payload["pruned_project"] = prune_result
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 10 if check and pending else 0
    if check:
        head = "check: changes pending" if pending else "check: up to date"
    elif dry_run:
        head = "dry_run (nothing written)"
    else:
        head = "already up to date" if result["up_to_date"] else "installed"
    print("\n".join(_install_lines(result, host, head, resync, prune_project=prune_result)))
    if not (dry_run or check):
        print("")
        print("Use it in your agent runtime (Claude Code, Cursor, ...):")
        print("  /simplicio-loop finish all the open issues")
        setup_cli.after_install()
    return 10 if check and pending else 0


def add_install(sub):
    p_install = sub.add_parser("install", help="install bundled skills + hooks into a runtime")
    p_install.add_argument("--target", default=".", help="project directory to install into")
    p_install.add_argument("--global", dest="globally", action="store_true",
                           help="install into ~/.claude instead of the project")
    p_install.add_argument("--host", default="claude", help="host id or 'all'")
    p_install.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    p_install.add_argument("--check", action="store_true",
                           help="write nothing; exit 0 when the install is up to date, 10 when changes are pending")
    p_install.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    p_install.add_argument("--verify", action="store_true", help="validate plan version/digest")
    p_install.add_argument("--uninstall", action="store_true", help="remove only what install registered; with --dry-run, list it and remove nothing")
    p_install.add_argument("--prune-project-copies", action="store_true",
                           help="detect and remove stale project-scope copies when installing globally")


def add_update(sub):
    p_update = sub.add_parser("update", help="install the latest GitHub release of simpletibr/simplicio-loop")
    p_update.add_argument("--check", action="store_true",
                          help="change nothing; exit 0 when up to date, 10 when an update is available, 2 on error")
    p_update.add_argument("--dry-run", action="store_true", help="print what would run; change nothing")
    p_update.add_argument("--force", action="store_true",
                          help="reinstall even when already on the latest release; allows a downgrade")
